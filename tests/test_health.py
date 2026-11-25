from types import SimpleNamespace as NS

from inventor.health import checks, metrics
from inventor.pipeline import RunStats


def test_metrics_and_checks_flag_problems():
    st = RunStats(signals_by_source={"hackernews": 10}, candidates=10, verified=6,
                  rejected={"off_topic": 2, "quote_not_found": 2}, harvest_errors=["boom"])
    result = NS(stats=st, problems=[NS(kinds=["community", "paper"]), NS(kinds=["code"])])
    m = metrics(result, ["hackernews", "openalex"])
    assert m["quote_verified_rate"] == 0.75   # 6 of the 8 on-topic candidates
    assert m["off_topic_rate"] == 0.2 and m["source_coverage"] == 0.5 and m["triangulated_top10"] == 0.5
    failed = {c.metric for c in checks(m) if not c.ok}
    assert failed == {"quote_verified_rate", "source_coverage", "harvest_errors"}


def test_empty_run_does_not_divide_by_zero():
    m = metrics(NS(stats=RunStats(), problems=[]), [])
    assert m["quote_verified_rate"] == 1.0 and m["candidates_per_signal"] == 0.0
