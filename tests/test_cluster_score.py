from datetime import UTC, datetime, timedelta

from inventor.cluster import ClusterStats, reconcile
from inventor.models import ProblemCandidate, Signal
from inventor.score import components, total

NOW = datetime(2026, 11, 25, tzinfo=UTC)


def cand(i):
    return ProblemCandidate(id=i, signal_id="s", statement=f"problem {i}", who_has_it="x",
                            current_workaround="", evidence_quote="q" * 20, lenses=[], verified=True)


def sig(i, kind, age_days=30, **eng):
    return Signal(id=i, source=kind, kind=kind, url="u", title="t", text="x", query="q",
                  created_utc=NOW - timedelta(days=age_days), retrieved_utc=NOW, engagement=eng)


def test_reconcile_never_loses_or_invents_candidates():
    cands = [cand("c1"), cand("c2"), cand("c3")]
    stats = ClusterStats()
    groups = reconcile([{"title": "A", "statement": "a", "member_ids": ["c1", "c2", "c99"]},
                        {"title": "B", "statement": "b", "member_ids": ["c2"]}], cands, stats)
    assert [g.member_ids for g in groups] == [["c1", "c2"], ["c3"]]
    assert (stats.unknown_ids, stats.duplicate_ids, stats.left_out) == (1, 1, 1)


def test_score_is_deterministic_and_rewards_triangulation():
    one_kind = [sig("a", "community", points=50), sig("b", "community", points=50)]
    two_kinds = [sig("a", "community", points=50), sig("c", "paper", citations=50)]
    s1, s2 = total(components(one_kind, NOW)), total(components(two_kinds, NOW))
    assert s2 > s1
    assert total(components(two_kinds, NOW)) == s2  # same input, same score


def test_recency_and_missing_dates():
    fresh = components([sig("a", "code", age_days=0)], NOW)
    old = components([sig("a", "code", age_days=365)], NOW)
    rec = {c.name: c for c in fresh}["recency"].value, {c.name: c for c in old}["recency"].value
    assert rec == (1.0, 0.5)  # one-year half-life
    undated = sig("a", "code")
    undated.created_utc = None
    assert {c.name: c for c in components([undated], NOW)}["recency"].detail == "no dates"
