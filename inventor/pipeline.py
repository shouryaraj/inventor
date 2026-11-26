"""The run: harvest -> extract -> verify -> cluster -> score -> report.

Every stage writes its output to the run directory, so any number in the report
can be traced back to the raw signal it came from.
"""

from __future__ import annotations

import asyncio
import json
import re
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx
from pydantic import ValidationError

from inventor.cluster import ClusterStats, Group, cluster
from inventor.health import Check, checks, metrics
from inventor.lenses import EXTRACT_SCHEMA, EXTRACT_SYSTEM, LENSES, extract_prompt
from inventor.llm import MODELS, BudgetExceeded, LLMClient, LLMError, LLMRequest
from inventor.models import Problem, ProblemCandidate, Signal
from inventor.observe import Tracer
from inventor.score import components, total
from inventor.sources import SOURCES, http_client
from inventor.sources.base import now_utc
from inventor.verify import quote_in_text

SEEDS_DIR = Path(__file__).parent / "seeds"
_QUERY_STRING = re.compile(r"\?[^\s'\"]*")


def redact(message: str) -> str:
    """Drop URL query strings from an error message: they can hold API keys (OpenAlex takes one there)."""
    return _QUERY_STRING.sub("?…", message)


@dataclass
class Seed:
    name: str
    description: str
    queries: dict[str, list[str]]


def load_seed(name_or_path: str) -> Seed:
    path = Path(name_or_path)
    if not path.suffix:
        path = SEEDS_DIR / f"{name_or_path}.toml"
    raw = tomllib.loads(path.read_text())
    return Seed(raw["name"], raw.get("description", ""), raw["queries"])


@dataclass
class RunConfig:
    seed: Seed
    sources: list[str]
    backend: str = "claude-cli"
    limit_per_query: int = 10
    batch_size: int = 8
    out_dir: Path = Path("runs")
    use_cache: bool = True
    weights: dict[str, float] = field(default_factory=dict)


@dataclass
class RunStats:
    signals_by_source: dict[str, int] = field(default_factory=dict)
    harvest_errors: list[str] = field(default_factory=list)
    candidates: int = 0
    verified: int = 0
    rejected: dict[str, int] = field(default_factory=dict)
    extract_errors: list[str] = field(default_factory=list)
    cluster: ClusterStats = field(default_factory=ClusterStats)
    partial: str | None = None   # why the run stopped early, if it did
    llm_calls: int = 0
    llm_cache_hits: int = 0
    spent_usd: float = 0.0


async def harvest(cfg: RunConfig, client: httpx.AsyncClient, stats: RunStats, tracer: Tracer) -> list[Signal]:
    signals: dict[str, Signal] = {}
    for name in cfg.sources:
        source = SOURCES[name](client)
        for query in cfg.seed.queries.get(name, []):
            with tracer.span(f"search.{name}", as_type="retriever", input={"query": query}) as span:
                try:
                    found = await source.search(query, cfg.limit_per_query)
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:  # network, bad JSON, odd records
                    message = redact(f"{type(exc).__name__}: {exc}")
                    stats.harvest_errors.append(f"{name} {query!r}: {message}")
                    span.update(level="ERROR", status_message=message[:500])
                    continue
                span.update(output={"signals": len(found), "urls": [s.url for s in found]})
            for s in found:
                signals.setdefault(s.id, s)
    for s in signals.values():
        stats.signals_by_source[s.source] = stats.signals_by_source.get(s.source, 0) + 1
    return list(signals.values())


def check_candidates(items: list[dict], batch: list[Signal], first_index: int) -> list[ProblemCandidate]:
    """Turn raw model output into candidates and apply the deterministic gates."""
    by_id = {s.id: s for s in batch}
    out = []
    for item in items:
        try:
            c = ProblemCandidate(id=f"c{first_index + len(out):04d}", **{
                **item, "lenses": [lens for lens in item.get("lenses", []) if lens in LENSES]})
        except (ValidationError, TypeError, AttributeError) as exc:
            raise LLMError(f"model output did not match the extraction schema: {str(exc)[:300]}") from exc
        signal = by_id.get(c.signal_id)
        if signal is None:
            c.reject_reason = "unknown_signal"
        elif c.relevance not in ("core", "adjacent"):
            c.reject_reason = "off_topic"
        else:
            ok, reason = quote_in_text(c.evidence_quote, f"{signal.title} {signal.text}")
            c.verified, c.reject_reason = ok, reason
        out.append(c)
    return out


async def extract_batch(llm: LLMClient, model: str, batch: list[Signal], domain: str,
                        first_index: int = 1) -> list[ProblemCandidate]:
    """One model call over a batch, then the gates. Each call gets its own quality scores."""
    result = await llm.complete(LLMRequest(system=EXTRACT_SYSTEM, prompt=extract_prompt(batch, domain),
                                           model=model, schema=EXTRACT_SCHEMA), name="extract.batch")
    cands = check_candidates((result.data or {}).get("problems", []), batch, first_index)
    on_topic = [c for c in cands if c.reject_reason != "off_topic"]
    for name, value in (("candidates", len(cands)),
                        ("quote_verified_rate", sum(c.verified for c in on_topic) / len(on_topic) if on_topic else 1.0),
                        ("off_topic", sum(c.reject_reason == "off_topic" for c in cands))):
        llm.tracer.score_observation(result.trace_id, result.observation_id, name, value)
    return cands


async def extract(llm: LLMClient, model: str, signals: list[Signal], batch_size: int,
                  stats: RunStats, domain: str) -> list[ProblemCandidate]:
    batches = [signals[i:i + batch_size] for i in range(0, len(signals), batch_size)]

    async def one(batch: list[Signal]) -> list[ProblemCandidate]:
        try:
            return await extract_batch(llm, model, batch, domain)
        except BudgetExceeded as exc:
            stats.partial = str(exc)
        except LLMError as exc:
            stats.extract_errors.append(str(exc))
        return []

    candidates: list[ProblemCandidate] = []
    for batch_cands in await asyncio.gather(*(one(b) for b in batches)):
        for c in batch_cands:  # renumber in a stable order
            c.id = f"c{len(candidates) + 1:04d}"
            candidates.append(c)
    stats.candidates = len(candidates)
    stats.verified = sum(c.verified for c in candidates)
    for c in candidates:
        if c.reject_reason:
            stats.rejected[c.reject_reason] = stats.rejected.get(c.reject_reason, 0) + 1
    return candidates


def _jsonl(path: Path, rows) -> None:
    path.write_text("".join(r.model_dump_json() + "\n" for r in rows))


@dataclass
class RunResult:
    run_dir: Path
    signals: list[Signal]
    candidates: list[ProblemCandidate]
    problems: list[Problem]
    stats: RunStats
    metrics: dict[str, float] = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)
    trace_url: str | None = None


def build_problems(groups: list[Group], verified: list[ProblemCandidate], signals: list[Signal],
                   now: datetime, weights: dict[str, float]) -> list[Problem]:
    by_cand = {c.id: c for c in verified}
    by_signal = {s.id: s for s in signals}
    problems = []
    for i, g in enumerate(groups, 1):
        members = [by_cand[m] for m in g.member_ids]
        sig_ids = list(dict.fromkeys(c.signal_id for c in members))
        sigs = [by_signal[s] for s in sig_ids]
        parts = components(sigs, now, weights)
        problems.append(Problem(
            id=f"p{i:03d}", title=g.title, statement=g.statement,
            candidate_ids=g.member_ids, signal_ids=sig_ids,
            sources=sorted({s.source for s in sigs}), kinds=sorted({s.kind for s in sigs}),
            lenses=sorted({lens for c in members for lens in c.lenses}),
            relevance="core" if any(c.relevance == "core" for c in members) else "adjacent",
            score=total(parts), components=parts,
        ))
    problems.sort(key=lambda p: (-p.score, p.id))
    return problems


def new_run_dir(out_dir: Path, name: str) -> Path:
    """A fresh directory; a second run in the same second gets a suffix instead of overwriting the first."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for n in range(1, 1000):
        path = out_dir / (name if n == 1 else f"{name}-{n}")
        try:
            path.mkdir()
        except FileExistsError:
            continue
        return path
    raise RuntimeError(f"too many runs named {name!r} in {out_dir}")


async def run(cfg: RunConfig, llm: LLMClient, transport: httpx.AsyncBaseTransport | None = None,
              now: datetime | None = None) -> RunResult:
    from inventor.report import write_report

    now = now or now_utc()
    run_dir = new_run_dir(cfg.out_dir, f"{cfg.seed.name}-{now.strftime('%Y%m%dT%H%M%SZ')}")
    stats = RunStats()
    models = MODELS[cfg.backend]
    tracer = llm.tracer

    with tracer.trace("inventor.run", tags=[f"seed:{cfg.seed.name}", f"backend:{cfg.backend}"],
                      input={"seed": cfg.seed.name, "sources": cfg.sources, "limit": cfg.limit_per_query},
                      metadata={"run_dir": run_dir.name, "models": models}) as root:
        with tracer.span("harvest", as_type="chain") as span:
            async with http_client(transport) as client:
                signals = await harvest(cfg, client, stats, tracer)
            span.update(output={"by_source": stats.signals_by_source, "errors": len(stats.harvest_errors)})
        _jsonl(run_dir / "signals.jsonl", signals)

        with tracer.span("extract", as_type="chain", input={"signals": len(signals)}) as span:
            candidates = await extract(llm, models["fast"], signals, cfg.batch_size, stats, cfg.seed.description)
            span.update(output={"candidates": stats.candidates, "verified": stats.verified,
                                "rejected": stats.rejected, "errors": len(stats.extract_errors)})
        _jsonl(run_dir / "candidates.jsonl", candidates)

        verified = [c for c in candidates if c.verified]
        problems: list[Problem] = []
        if verified:
            with tracer.span("group", as_type="chain", input={"candidates": len(verified)}) as span:
                try:
                    groups, stats.cluster = await cluster(llm, models["fast"], verified)
                except (BudgetExceeded, LLMError) as exc:
                    stats.partial = stats.partial or f"clustering skipped: {exc}"
                    groups = [Group(c.statement[:80], c.statement, [c.id]) for c in verified]
                    span.update(level="WARNING", status_message=stats.partial)
                span.update(output={"groups": len(groups), **vars(stats.cluster)})
            with tracer.span("score", input={"groups": len(groups)}) as span:
                problems = build_problems(groups, verified, signals, now, cfg.weights)
                span.update(output=[{"title": p.title, "score": p.score, "kinds": p.kinds} for p in problems[:10]])

        stats.llm_calls, stats.spent_usd = llm.budget.calls, llm.budget.spent_usd
        stats.llm_cache_hits = llm.cache_hits
        (run_dir / "problems.json").write_text(json.dumps([p.model_dump() for p in problems], indent=2))
        result = RunResult(run_dir, signals, candidates, problems, stats)
        result.metrics = metrics(result, cfg.sources)
        result.checks = checks(result.metrics)
        (run_dir / "metrics.json").write_text(json.dumps(
            {"run": run_dir.name, "seed": cfg.seed.name, "backend": cfg.backend, "time_utc": now.isoformat(),
             "metrics": result.metrics, "failed_checks": [c.metric for c in result.checks if not c.ok]},
            indent=2))
        for name, value in result.metrics.items():
            root.score_trace(name=name, value=float(value))
        root.score_trace(name="health", value="ok" if all(c.ok for c in result.checks) else "warn",
                         data_type="CATEGORICAL",
                         comment="; ".join(f"{c.rule}: {c.why}" for c in result.checks if not c.ok) or None)
        root.update(output={"problems": len(problems), "report": f"{run_dir.name}/report.md"})
        result.trace_url = tracer.trace_url(root.trace_id)
    tracer.flush()
    write_report(result, cfg, now)
    return result
