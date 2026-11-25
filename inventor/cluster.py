"""Group candidates that describe the same underlying problem.

The LLM proposes groups; code enforces the invariants: every verified candidate
ends up in exactly one group, unknown ids are dropped, and anything the model
left out becomes its own group. The model can merge; it cannot lose or invent.
"""

from __future__ import annotations

from dataclasses import dataclass

from inventor.llm import LLMClient, LLMRequest
from inventor.models import ProblemCandidate

MAX_PER_CALL = 150

CLUSTER_SYSTEM = """You group problem statements that describe the same underlying problem.
Merge only when a single solution would address all members. Different user groups with the
same pain may be merged; similar topics with different pains must not be.
For each group write a short title (max 10 words) and one plain sentence stating the shared
problem, using only what the members say. Use the given ids exactly."""

CLUSTER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "statement": {"type": "string"},
                    "member_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "statement", "member_ids"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["groups"],
    "additionalProperties": False,
}


@dataclass
class Group:
    title: str
    statement: str
    member_ids: list[str]


@dataclass
class ClusterStats:
    unknown_ids: int = 0
    duplicate_ids: int = 0
    left_out: int = 0


def reconcile(proposed: list[dict], candidates: list[ProblemCandidate], stats: ClusterStats) -> list[Group]:
    known = {c.id: c for c in candidates}
    seen: set[str] = set()
    groups: list[Group] = []
    for g in proposed:
        ids = []
        for i in g.get("member_ids", []):
            if i not in known:
                stats.unknown_ids += 1
            elif i in seen:
                stats.duplicate_ids += 1
            else:
                ids.append(i)
                seen.add(i)
        if ids:
            groups.append(Group(g.get("title", "").strip() or known[ids[0]].statement[:80],
                                g.get("statement", "").strip() or known[ids[0]].statement, ids))
    for c in candidates:
        if c.id not in seen:
            stats.left_out += 1
            groups.append(Group(c.statement[:80], c.statement, [c.id]))
    return groups


async def cluster(llm: LLMClient, model: str, candidates: list[ProblemCandidate]) -> tuple[list[Group], ClusterStats]:
    stats = ClusterStats()
    groups: list[Group] = []
    for start in range(0, len(candidates), MAX_PER_CALL):
        chunk = candidates[start:start + MAX_PER_CALL]
        lines = "\n".join(f"{c.id}: {c.statement} (who: {c.who_has_it})" for c in chunk)
        result = await llm.complete(LLMRequest(system=CLUSTER_SYSTEM, prompt=f"Problem statements:\n{lines}",
                                               model=model, schema=CLUSTER_SCHEMA), name="group")
        groups += reconcile((result.data or {}).get("groups", []), chunk, stats)
    return groups, stats
