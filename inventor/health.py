"""Run health: the metrics a monitor should watch, and checks against thresholds.

Backend analogy: these are a service's golden signals with simple alert rules.
Each run writes `metrics.json`; with Langfuse on, the same numbers become trace
scores, so they can be charted over time on a dashboard. All values come from
code. The thresholds are engineering defaults chosen for this project, not
industry standards. Tune them once you have a history of runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# metric -> (comparison, threshold, why it matters)
CHECKS: dict[str, tuple[str, float, str]] = {
    "quote_verified_rate": ("<", 0.90, "the model is quoting text that is not in its source"),
    "off_topic_rate": (">", 0.40, "the seed's queries land outside the domain"),
    "candidates_per_signal": ("<", 0.10, "extraction finds almost nothing; prompt or sources may be broken"),
    "source_coverage": ("<", 1.0, "a requested source returned no signals"),
    "harvest_errors": (">", 0, "a source API call failed"),
    "extract_errors": (">", 0, "a model call failed or returned unusable output"),
    "partial": (">", 0, "the run stopped early (budget or failure)"),
}


@dataclass
class Check:
    metric: str
    value: float
    ok: bool
    rule: str
    why: str


def metrics(result: Any, requested_sources: list[str]) -> dict[str, float]:
    st = result.stats
    signals = sum(st.signals_by_source.values())
    off_topic = st.rejected.get("off_topic", 0)
    on_topic = st.candidates - off_topic
    top = result.problems[:10]
    calls = st.llm_calls + st.llm_cache_hits
    return {
        "signals": signals,
        "candidates": st.candidates,
        "verified": st.verified,
        # Of the on-topic candidates, how many quotes exist verbatim in their source.
        "quote_verified_rate": round(st.verified / on_topic, 4) if on_topic else 1.0,
        "off_topic_rate": round(off_topic / st.candidates, 4) if st.candidates else 0.0,
        "candidates_per_signal": round(st.candidates / signals, 4) if signals else 0.0,
        "problems": len(result.problems),
        "triangulated_top10": round(sum(len(p.kinds) >= 2 for p in top) / len(top), 4) if top else 0.0,
        "source_coverage": round(sum(1 for s in requested_sources if st.signals_by_source.get(s)) /
                                 len(requested_sources), 4) if requested_sources else 0.0,
        "harvest_errors": len(st.harvest_errors),
        "extract_errors": len(st.extract_errors),
        "partial": 1 if st.partial else 0,
        "llm_calls": st.llm_calls,
        "cache_hit_rate": round(st.llm_cache_hits / calls, 4) if calls else 0.0,
        "spend_usd": round(st.spent_usd, 6),
    }


def checks(m: dict[str, float]) -> list[Check]:
    out = []
    for metric, (op, threshold, why) in CHECKS.items():
        value = m[metric]
        bad = value < threshold if op == "<" else value > threshold
        out.append(Check(metric, value, not bad, f"{metric} {op} {threshold:g}", why))
    return out
