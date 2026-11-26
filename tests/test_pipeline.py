import asyncio
import json
from datetime import UTC, datetime

import httpx
from conftest import FakeBackend, json_transport

from inventor.llm import Budget, LLMClient
from inventor.pipeline import RunConfig, Seed, redact, run
from inventor.sources.base import Source

HN = {"hits": [
    {"objectID": "1",
     "comment_text": "Our nutrient dosing pump has no feedback, so we check the EC by hand twice a day.",
     "story_title": "Ask HN: hydroponics", "points": 30, "created_at": "2026-09-01T00:00:00Z"},
    {"objectID": "2", "comment_text": "Great launch, congratulations to the team!",
     "story_title": "Show HN: a farm", "points": 5, "created_at": "2026-09-01T00:00:00Z"},
]}


def respond(request):
    if "problems" in json.dumps(request.schema):
        return {"problems": [
            {"signal_id": "hackernews:1", "statement": "Growers cannot see if dosing worked.",
             "who_has_it": "hydroponic growers", "current_workaround": "manual EC checks",
             "evidence_quote": "we check the EC by hand twice a day",
             "lenses": ["workaround", "norman_feedback"], "relevance": "core"},
            {"signal_id": "hackernews:1", "statement": "Fabricated problem.", "who_has_it": "x",
             "current_workaround": "", "evidence_quote": "the pump caught fire on Tuesday night",
             "lenses": ["doesnt_work", "not_a_lens"], "relevance": "core"},
            {"signal_id": "hackernews:2", "statement": "Off-topic.", "who_has_it": "x",
             "current_workaround": "", "evidence_quote": "Great launch, congratulations to the team",
             "lenses": [], "relevance": "off_topic"},
            {"signal_id": "hackernews:999", "statement": "Wrong id.", "who_has_it": "x",
             "current_workaround": "", "evidence_quote": "we check the EC by hand", "lenses": [],
             "relevance": "core"},
        ]}
    ids = [line.split(":")[0] for line in request.prompt.splitlines()[1:]]
    return {"groups": [{"title": "No dosing feedback", "statement": "Dosing has no feedback.", "member_ids": ids}]}


def test_end_to_end_keeps_only_verified_evidence(tmp_path):
    cfg = RunConfig(seed=Seed("test", "test seed", {"hackernews": ["hydroponics"]}), sources=["hackernews"],
                    backend="claude-cli", out_dir=tmp_path)
    llm = LLMClient(FakeBackend(respond), Budget(1.0, 10))
    result = asyncio.run(run(cfg, llm, transport=json_transport({"hn.algolia.com": HN}),
                             now=datetime(2026, 11, 25, tzinfo=UTC)))
    st = result.stats
    assert st.signals_by_source == {"hackernews": 2}
    assert (st.candidates, st.verified) == (4, 1)
    assert st.rejected == {"quote_not_found": 1, "unknown_signal": 1, "off_topic": 1}
    [p] = result.problems
    assert p.signal_ids == ["hackernews:1"] and p.lenses == ["norman_feedback", "workaround"]
    report = (result.run_dir / "report.md").read_text()
    assert "we check the EC by hand twice a day" in report and "caught fire" not in report
    for f in ("signals.jsonl", "candidates.jsonl", "problems.json"):
        assert (result.run_dir / f).exists()


def test_budget_exhaustion_gives_partial_run_not_crash(tmp_path):
    cfg = RunConfig(seed=Seed("test", "", {"hackernews": ["hydroponics"]}), sources=["hackernews"],
                    out_dir=tmp_path, batch_size=1)
    llm = LLMClient(FakeBackend(respond), Budget(1.0, max_calls=1), concurrency=1)
    result = asyncio.run(run(cfg, llm, transport=json_transport({"hn.algolia.com": HN})))
    assert result.stats.partial and "call cap" in result.stats.partial
    assert "Partial run" in (result.run_dir / "report.md").read_text()


def test_harvest_errors_never_include_query_strings(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "SECRET123")
    monkeypatch.setattr(Source, "backoff_s", 0)
    cfg = RunConfig(seed=Seed("test", "", {"openalex": ["greenhouse"]}), sources=["openalex"], out_dir=tmp_path)
    transport = httpx.MockTransport(lambda request: httpx.Response(500, request=request))
    result = asyncio.run(run(cfg, LLMClient(FakeBackend(respond), Budget(1.0, 10)), transport=transport))
    assert result.stats.harvest_errors and "500" in result.stats.harvest_errors[0]
    assert "SECRET123" not in (result.run_dir / "report.md").read_text()
    assert "SECRET123" not in redact("for url 'https://api.openalex.org/works?api_key=SECRET123&x=1'")


def test_bad_source_response_is_recorded_not_fatal(tmp_path):
    cfg = RunConfig(seed=Seed("test", "", {"hackernews": ["hydroponics"]}), sources=["hackernews"], out_dir=tmp_path)
    broken = {"hits": [{"comment_text": "no objectID here, the record is malformed"}]}
    result = asyncio.run(run(cfg, LLMClient(FakeBackend(respond), Budget(1.0, 10)),
                             transport=json_transport({"hn.algolia.com": broken})))
    assert result.stats.harvest_errors and "KeyError" in result.stats.harvest_errors[0]
    assert (result.run_dir / "report.md").exists()


def test_malformed_model_output_fails_the_batch_not_the_run(tmp_path):
    def bad(request):
        if "problems" in json.dumps(request.schema):
            return {"problems": [{"signal_id": "hackernews:1"}]}  # required fields missing
        return {"groups": []}

    cfg = RunConfig(seed=Seed("test", "", {"hackernews": ["hydroponics"]}), sources=["hackernews"], out_dir=tmp_path)
    result = asyncio.run(run(cfg, LLMClient(FakeBackend(bad), Budget(1.0, 10)),
                             transport=json_transport({"hn.algolia.com": HN})))
    assert result.stats.extract_errors and "extraction schema" in result.stats.extract_errors[0]
    assert (result.run_dir / "report.md").exists()


def test_runs_in_the_same_second_do_not_overwrite(tmp_path):
    now = datetime(2026, 11, 25, tzinfo=UTC)
    cfg = RunConfig(seed=Seed("test", "", {"hackernews": ["hydroponics"]}), sources=["hackernews"], out_dir=tmp_path)
    dirs = {asyncio.run(run(cfg, LLMClient(FakeBackend(respond), Budget(1.0, 10)),
                            transport=json_transport({"hn.algolia.com": HN}), now=now)).run_dir for _ in range(2)}
    assert len(dirs) == 2
