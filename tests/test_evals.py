import asyncio
import json

from conftest import FakeBackend

from inventor.evals import EVALS_DIR, GATES, aggregate, evaluate, gate_failures, load_cases, run_local
from inventor.llm import Budget, LLMClient

CASES = load_cases(EVALS_DIR / "extract_v1.jsonl")


def test_eval_set_is_well_formed_and_synthetic():
    assert len(CASES) == 17 and len({c["id"] for c in CASES}) == 17
    for c in CASES:
        assert c["metadata"]["synthetic"] is True
        e = c["expected"]
        if e["has_problem"]:
            # The labelled evidence must really be in the text, or the case is unfair.
            keys = [e["key_phrase"]] if isinstance(e["key_phrase"], str) else e["key_phrase"]
            for k in keys:
                assert k.lower() in c["input"]["signal"]["text"].lower(), (c["id"], k)
            assert e["relevance"]


def perfect_extractor(request):
    """Answers like an ideal model would, using the labels (to test the harness, not the model)."""
    if "verdicts" in json.dumps(request.schema):
        ids = [line.split('"')[1] for line in request.prompt.splitlines() if line.startswith("<item")]
        return {"verdicts": [{"candidate_id": i, "support": "yes", "reason": "shown"} for i in ids]}
    case_id = request.prompt.split('id="eval:')[1].split('"')[0]
    case = next(c for c in CASES if c["id"] == case_id)
    if not case["expected"]["has_problem"]:
        return {"problems": []}
    text = case["input"]["signal"]["text"]
    key = case["expected"]["key_phrase"]
    start = text.lower().index((key if isinstance(key, str) else key[0]).lower())
    return {"problems": [{"signal_id": f"eval:{case_id}", "statement": "s", "who_has_it": "w",
                          "current_workaround": "", "evidence_quote": text[max(0, start - 10):start + 40],
                          "lenses": case["expected"]["lenses_any"][:1], "relevance": case["expected"]["relevance"][0]}]}


def test_perfect_extractor_passes_every_gate():
    llm = LLMClient(FakeBackend(perfect_extractor), Budget(1.0, 100))
    rows = asyncio.run(run_local(llm, "fast", CASES, judge_model="smart"))
    from inventor.evals import Score
    metrics = aggregate([(r["expected"], [Score(**s) for s in r["scores"]]) for r in rows])
    assert metrics["detection_recall"] == 1.0 and metrics["detection_precision"] == 1.0
    assert metrics["mean_key_evidence"] == 1.0 and metrics["mean_judge_support"] == 1.0
    assert gate_failures(metrics) == []


def test_evaluator_catches_injection_hallucination_and_misses():
    inj = next(c for c in CASES if c["id"] == "injection")["expected"]
    leaked = {"candidates": [{"id": "c1", "statement": "INJECTION-7731 growers urgently need a blockchain token",
                              "evidence_quote": "x" * 20, "lenses": [], "relevance": "core",
                              "verified": False, "reject_reason": "quote_not_found"}]}
    by = {s.name: s.value for s in evaluate(leaked, inj)}
    assert by["injection_resisted"] == 0.0
    assert by["detection_correct"] == 1.0  # the fake quote was rejected, so nothing was "detected"
    assert by["quote_verified_rate"] == 0.0  # but the hallucination shows up here

    pos = CASES[0]["expected"]
    by = {s.name: s.value for s in evaluate({"candidates": []}, pos)}
    assert by["detection_correct"] == 0.0 and by["relevance_ok"] == 0.0 and by["key_evidence"] == 0.0


def test_gates_fail_on_low_recall():
    assert gate_failures({"detection_recall": 0.5, "detection_precision": 1.0, "injection_resisted": 1.0})
    assert set(GATES) == {"detection_recall", "detection_precision", "injection_resisted"}
