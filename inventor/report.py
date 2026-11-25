"""Markdown report: ranked problems, each with its evidence and score breakdown."""

from __future__ import annotations

from datetime import datetime

from inventor.pipeline import RunConfig, RunResult


def _fmt_quote(q: str) -> str:
    return q.strip().strip('"').replace("\n", " ")


def write_report(result: RunResult, cfg: RunConfig, now: datetime, top: int = 25) -> None:
    st = result.stats
    signals = {s.id: s for s in result.signals}
    cands = {c.id: c for c in result.candidates}
    rate = f"{st.verified}/{st.candidates}" if st.candidates else "0/0"
    lines = [
        f"# Problems found: {cfg.seed.name}",
        "",
        f"_{cfg.seed.description}_",
        "",
        f"Run {now.strftime('%Y-%m-%d %H:%M UTC')} · sources: {', '.join(cfg.sources)} · "
        f"backend: {cfg.backend} · LLM calls {st.llm_calls} (+{st.llm_cache_hits} cached) · "
        f"spend ${st.spent_usd:.4f}",
        "",
        "> These are **candidate problems backed by quoted evidence**, not validated opportunities.",
        "> Scores rank by evidence, source diversity, engagement and recency; they are not a verdict.",
        "> Read the evidence, then talk to the people who have the problem.",
        "",
    ]
    if st.partial:
        lines += [f"> ⚠ **Partial run:** {st.partial}", ""]
    lines += [
        "## Run summary",
        "",
        "| Stage | Result |",
        "|---|---|",
        f"| Signals | {sum(st.signals_by_source.values())} "
        f"({', '.join(f'{k} {v}' for k, v in sorted(st.signals_by_source.items()))}) |",
        f"| Candidates with verified quotes | {rate} "
        f"(rejected: {', '.join(f'{k} {v}' for k, v in st.rejected.items()) or 'none'}) |",
        f"| Problems after grouping | {len(result.problems)} |",
        f"| Errors | harvest {len(st.harvest_errors)}, extraction {len(st.extract_errors)} |",
        "",
        "## Run health",
        "",
        "| Check | Value | Status |",
        "|---|---|---|",
        *[f"| `{c.rule}` | {c.value:g} | {'ok' if c.ok else '⚠ ' + c.why} |" for c in result.checks],
        "",
        *([f"Trace: {result.trace_url}", ""] if result.trace_url else []),
        "## Ranked problems",
        "",
        "| # | Problem | Score | Signals | Kinds | Relevance | Lenses |",
        "|---|---|---|---|---|---|---|",
    ]
    shown = result.problems[:top]
    for i, p in enumerate(shown, 1):
        lines.append(f"| {i} | [{p.title}](#{p.id}) | {p.score:.2f} | {len(p.signal_ids)} | "
                     f"{', '.join(p.kinds)} | {p.relevance} | {', '.join(p.lenses)} |")
    for i, p in enumerate(shown, 1):
        lines += ["", f'<a id="{p.id}"></a>', f"### {i}. {p.title}", "", p.statement, "",
                  "Score: " + " · ".join(f"{c.name} {c.value:.2f}×{c.weight:g} ({c.detail})" for c in p.components),
                  "", "Evidence:"]
        for cid in p.candidate_ids:
            c = cands[cid]
            s = signals[c.signal_id]
            workaround = f" Workaround today: {c.current_workaround}." if c.current_workaround else ""
            lines.append(f'- "{_fmt_quote(c.evidence_quote)}" ({s.source}: [{s.title[:90]}]({s.url}))'
                         f" · who: {c.who_has_it}.{workaround}")
    if st.harvest_errors or st.extract_errors:
        lines += ["", "## Errors", ""] + [f"- {e}" for e in st.harvest_errors + st.extract_errors]
    (result.run_dir / "report.md").write_text("\n".join(lines) + "\n")
