"""Deterministic, explainable scoring. It ranks problems; it does not judge them.

Every component is normalised to 0..1 and shown with the reason behind it, so a
reader can disagree with a weight instead of trusting a black-box number.
The LLM supplies no numbers here.
"""

from __future__ import annotations

import math
from datetime import datetime

from inventor.models import ScoreComponent, Signal

DEFAULT_WEIGHTS: dict[str, float] = {
    "evidence": 1.0,       # how many independent signals
    "triangulation": 1.5,  # how many kinds of source agree (forums, code, papers, startups)
    "engagement": 1.0,     # points, comments, reactions, citations
    "recency": 0.5,        # how fresh the evidence is
}
ALL_KINDS = ("community", "code", "paper", "startup")
EVIDENCE_SATURATION = 8         # signals
ENGAGEMENT_SATURATION = 1000    # summed engagement units
RECENCY_HALF_LIFE_DAYS = 365.0


def components(signals: list[Signal], now: datetime, weights: dict[str, float] | None = None) -> list[ScoreComponent]:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    n = len(signals)
    kinds = sorted({s.kind for s in signals})
    engagement = sum(sum(s.engagement.values()) for s in signals)
    ages = [(now - s.created_utc).total_seconds() / 86400 for s in signals if s.created_utc]
    recency = sum(0.5 ** (max(a, 0) / RECENCY_HALF_LIFE_DAYS) for a in ages) / len(ages) if ages else 0.0
    return [
        ScoreComponent(name="evidence", weight=w["evidence"],
                       value=min(1.0, math.log2(1 + n) / math.log2(1 + EVIDENCE_SATURATION)),
                       detail=f"{n} signal(s)"),
        ScoreComponent(name="triangulation", weight=w["triangulation"], value=len(kinds) / len(ALL_KINDS),
                       detail=f"kinds: {', '.join(kinds)}"),
        ScoreComponent(name="engagement", weight=w["engagement"],
                       value=min(1.0, math.log10(1 + engagement) / math.log10(1 + ENGAGEMENT_SATURATION)),
                       detail=f"{engagement} total (points+comments+reactions+citations)"),
        ScoreComponent(name="recency", weight=w["recency"], value=recency,
                       detail=f"median age {sorted(ages)[len(ages) // 2]:.0f} days" if ages else "no dates"),
    ]


def total(parts: list[ScoreComponent]) -> float:
    weight = sum(p.weight for p in parts)
    return round(sum(p.value * p.weight for p in parts) / weight, 4) if weight else 0.0
