"""Command line.

    inventor sources                       list sources (and Langfuse) and whether they are usable
    inventor run --seed cea                harvest, extract, verify, group, score, report
    inventor eval [--judge] [--gate]       run the extraction eval set (locally or in Langfuse)
    inventor history                       health metrics of past runs, oldest first

A `.env` file in the working directory is read at start-up; it never overrides
variables that are already set.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from inventor.llm import BACKENDS, MODELS, Budget, LLMClient, make_backend
from inventor.observe import langfuse_configured, load_env_file, make_tracer
from inventor.pipeline import RunConfig, load_seed, run
from inventor.sources import SOURCES


def cmd_sources(_: argparse.Namespace) -> int:
    for name, cls in SOURCES.items():
        ok, note = cls.available()
        print(f"{'✔' if ok else '✘'} {name:<15} {cls.kind:<10} {note}")
    ok, note = langfuse_configured()
    print(f"{'✔' if ok else '✘'} {'langfuse':<15} {'tracing':<10} {note}")
    return 0


def _client(args: argparse.Namespace, out: Path) -> LLMClient:
    return LLMClient(make_backend(args.backend), Budget(args.budget_usd, args.max_calls),
                     cache_dir=None if args.no_cache else out / ".cache", concurrency=args.concurrency,
                     tracer=make_tracer(enabled=not args.no_trace))


def cmd_run(args: argparse.Namespace) -> int:
    seed = load_seed(args.seed)
    sources = args.sources.split(",") if args.sources else [s for s in seed.queries if s in SOURCES]
    unknown = [s for s in sources if s not in SOURCES]
    if unknown:
        print(f"unknown source(s): {', '.join(unknown)}; see `inventor sources`", file=sys.stderr)
        return 2
    disabled = [s for s in sources if not SOURCES[s].available()[0]]
    sources = [s for s in sources if s not in disabled]
    if disabled:
        print(f"skipping (no credentials): {', '.join(disabled)}")

    out = Path(args.out)
    cfg = RunConfig(seed=seed, sources=sources, backend=args.backend, limit_per_query=args.limit,
                    out_dir=out, use_cache=not args.no_cache)
    llm = _client(args, out)
    result = asyncio.run(run(cfg, llm))
    st = result.stats
    print(f"signals:    {sum(st.signals_by_source.values())} {dict(sorted(st.signals_by_source.items()))}")
    print(f"candidates: {st.candidates}, verified {st.verified}, rejected {st.rejected or '{}'}")
    print(f"problems:   {len(result.problems)}")
    print(f"llm:        {st.llm_calls} calls (+{st.llm_cache_hits} cached), ${st.spent_usd:.4f}")
    if st.partial:
        print(f"partial:    {st.partial}")
    if st.harvest_errors or st.extract_errors:
        print(f"errors:     {len(st.harvest_errors)} harvest, {len(st.extract_errors)} extraction (see report)")
    failed = [c for c in result.checks if not c.ok]
    print(f"health:     {'ok' if not failed else f'{len(failed)} check(s) failed'}")
    for c in failed:
        print(f"  ⚠ {c.rule} (value {c.value:g}): {c.why}")
    print(f"report:     {result.run_dir / 'report.md'}")
    if result.trace_url:
        print(f"trace:      {result.trace_url}")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from inventor.evals import (
        EVALS_DIR,
        Score,
        aggregate,
        gate_failures,
        load_cases,
        prompt_version,
        run_langfuse,
        run_local,
    )

    path = Path(args.dataset) if args.dataset.endswith(".jsonl") else EVALS_DIR / f"{args.dataset}.jsonl"
    cases = load_cases(path)
    if args.only:
        cases = [c for c in cases if c["metadata"]["category"] in args.only.split(",")]
    out = Path(args.out)
    llm = _client(args, out)
    models = MODELS[args.backend]
    judge_model = models["smart"] if args.judge else None
    version = prompt_version()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_name = f"prompt-{version}-{models['fast']}-{stamp}"
    url = None
    if llm.tracer.enabled:
        rows, url = run_langfuse(llm, models["fast"], cases, judge_model, path.stem, run_name,
                                 {"prompt_version": version, "model": models["fast"], "backend": args.backend,
                                  "judge_model": judge_model or "none"})
    else:
        rows = asyncio.run(run_local(llm, models["fast"], cases, judge_model))

    metrics = aggregate([(r["expected"], [Score(**s) for s in r["scores"]]) for r in rows])
    run_dir = out / "evals" / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "results.json").write_text(json.dumps(
        {"run_name": run_name, "dataset": path.name, "prompt_version": version, "metrics": metrics,
         "spend_usd": round(llm.budget.spent_usd, 6), "llm_calls": llm.budget.calls,
         "cache_hits": llm.cache_hits, "cases": rows}, indent=2))

    print(f"eval {path.stem}: {len(rows)} cases · prompt {version} · model {models['fast']}"
          f"{' · judge ' + judge_model if judge_model else ''}")
    print(f"{'case':<28} {'category':<18} {'want':<5} {'got':<4} failed checks")
    for r in sorted(rows, key=lambda r: r["id"] or ""):
        by = {s["name"]: s["value"] for s in r["scores"]}
        bad = [n for n, v in by.items() if n not in ("detected", "judge_support", "quote_verified_rate") and v < 1]
        if "judge_support" in by and by["judge_support"] < 1:
            bad.append(f"judge_support={by['judge_support']:.2f}")
        print(f"{r['id']:<28} {r['category']:<18} {str(r['expected']['has_problem'])[0]:<5} "
              f"{'T' if by.get('detected') else 'F':<4} {', '.join(bad) or '-'}")
    print("metrics: " + ", ".join(f"{k} {v:g}" for k, v in metrics.items()))
    print(f"llm: {llm.budget.calls} calls (+{llm.cache_hits} cached), ${llm.budget.spent_usd:.4f}")
    print(f"results: {run_dir / 'results.json'}")
    if url:
        print(f"experiment: {url}")
    if args.gate:
        failures = gate_failures(metrics)
        for f in failures:
            print(f"GATE FAILED: {f}")
        return 1 if failures else 0
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    rows = []
    for f in sorted(Path(args.out).glob("*/metrics.json")):
        data = json.loads(f.read_text())
        rows.append(data)
    if not rows:
        print(f"no runs with metrics.json under {args.out}/")
        return 0
    cols = ["signals", "candidates", "quote_verified_rate", "off_topic_rate", "problems", "triangulated_top10",
            "spend_usd"]
    print(f"{'run':<28} " + " ".join(f"{c[:12]:>12}" for c in cols) + "  failed checks")
    for d in rows:
        m = d["metrics"]
        print(f"{d['run']:<28} " + " ".join(f"{m.get(c, float('nan')):>12g}" for c in cols)
              + "  " + (", ".join(d["failed_checks"]) or "-"))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="inventor", description="Find real problems worth solving, with evidence.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sources", help="list sources and their availability").set_defaults(func=cmd_sources)
    r = sub.add_parser("run", help="run the problem-finding pipeline for a seed")
    r.add_argument("--seed", required=True, help="seed name (inventor/seeds/<name>.toml) or path to a .toml")
    r.add_argument("--sources", help="comma-separated subset of sources (default: all the seed has queries for)")
    r.add_argument("--backend", choices=BACKENDS, default="claude-cli")
    r.add_argument("--budget-usd", type=float, default=2.0, help="hard spend cap for this run")
    r.add_argument("--max-calls", type=int, default=200, help="hard cap on LLM calls for this run")
    r.add_argument("--limit", type=int, default=10, help="results per query per source")
    r.add_argument("--concurrency", type=int, default=4)
    r.add_argument("--out", default="runs")
    r.add_argument("--no-cache", action="store_true", help="ignore and do not write the LLM response cache")
    r.add_argument("--no-trace", action="store_true", help="do not send traces to Langfuse even if configured")
    r.set_defaults(func=cmd_run)

    e = sub.add_parser("eval", help="run the extraction eval set")
    e.add_argument("--dataset", default="extract_v1", help="name in evals/ or path to a .jsonl file")
    e.add_argument("--only", help="comma-separated categories to run")
    e.add_argument("--judge", action="store_true", help="also ask the smart model whether quotes support statements")
    e.add_argument("--gate", action="store_true", help="exit 1 if run metrics fall below the gates in evals.py")
    e.add_argument("--backend", choices=BACKENDS, default="claude-cli")
    e.add_argument("--budget-usd", type=float, default=0.5)
    e.add_argument("--max-calls", type=int, default=100)
    e.add_argument("--concurrency", type=int, default=4)
    e.add_argument("--out", default="runs")
    e.add_argument("--no-cache", action="store_true", help="fresh model calls (use to measure run-to-run variation)")
    e.add_argument("--no-trace", action="store_true", help="run locally even if Langfuse is configured")
    e.set_defaults(func=cmd_eval)

    h = sub.add_parser("history", help="health metrics of past runs")
    h.add_argument("--out", default="runs")
    h.set_defaults(func=cmd_history)
    args = parser.parse_args(argv)
    load_env_file()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
