"""Data model. Provenance is the point: every problem traces back to signals with URLs.

Signal           raw evidence from one source (a post, an issue, an abstract, a company)
ProblemCandidate one problem the LLM read out of one signal, with a verbatim quote
Problem          candidates grouped into one problem, scored by deterministic code
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SourceKind = Literal["community", "code", "paper", "startup"]


class Signal(BaseModel):
    id: str                      # "<source>:<native id>", stable across runs
    source: str
    kind: SourceKind
    url: str
    title: str
    text: str                    # excerpt, HTML stripped, no author names
    query: str                   # the search query that found it
    created_utc: datetime | None = None
    retrieved_utc: datetime
    engagement: dict[str, int] = Field(default_factory=dict)  # points, comments, reactions, citations


class ProblemCandidate(BaseModel):
    id: str
    signal_id: str
    statement: str
    who_has_it: str
    current_workaround: str      # "" when the signal shows none
    evidence_quote: str
    lenses: list[str]
    relevance: str = "core"      # core | adjacent | off_topic (the model's judgement, not a fact)
    verified: bool = False
    reject_reason: str | None = None


class ScoreComponent(BaseModel):
    name: str
    value: float                 # 0..1 after normalisation
    weight: float
    detail: str                  # human-readable "why", e.g. "3 signals from 2 kinds"


class Problem(BaseModel):
    id: str
    title: str
    statement: str
    candidate_ids: list[str]
    signal_ids: list[str]
    sources: list[str]
    kinds: list[str]
    lenses: list[str]
    relevance: str = "core"      # "core" if any member is core, else "adjacent"
    score: float = 0.0
    components: list[ScoreComponent] = Field(default_factory=list)
