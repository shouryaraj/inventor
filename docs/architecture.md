# Architecture

```
seed (domain + queries)
   │
   ▼
harvest     sources/*  ── Signal(id, source, kind, url, title, text, created, engagement)  → signals.jsonl
   │
   ▼
extract     LLM, batched, JSON schema ── ProblemCandidate(statement, who, workaround, quote, lenses, relevance)
   │
   ▼
verify      code: quote must appear in its signal; relevance must be core/adjacent         → candidates.jsonl
   │
   ▼
group       LLM proposes groups; code guarantees each candidate is in exactly one group
   │
   ▼
score       code: evidence, triangulation, engagement, recency (each shown with its reason) → problems.json
   │
   ▼
report      markdown with ranked problems, quotes and links                                → report.md
```

## Boundaries

| Layer | Who decides | Can it invent? |
|---|---|---|
| Harvest | source APIs | no |
| Extract | model | yes, so the next layer checks it |
| Verify | code | no |
| Group | model proposes, code reconciles | cannot lose or invent members |
| Score | code | no |

## LLM layer

`LLMClient` wraps a backend with a response cache (sha256 of the request), a budget guard
(max calls and max USD, checked before every call) and a concurrency limit. Backends:
`claude-cli` (headless Claude Code, isolated: custom system prompt, no tools, no settings, no
MCP) and `anthropic-api` (official SDK, structured outputs). Models are chosen by role:
`fast` for extraction and grouping, `smart` for later synthesis stages.

## Run directory

`runs/<seed>-<UTC timestamp>/` holds every intermediate file. `runs/.cache/` holds LLM
responses. Both are git-ignored.

## Roadmap

1. Spine: HN, GitHub, OpenAlex → lenses → verify → group → score → report. **Done.**
2. Breadth: YC startups (crowded vs open), research-area growth (OpenAlex yearly counts),
   cross-domain analogies (labelled hypotheses), Reddit/Product Hunt (credentials required).
3. Depth: register sources as GPT-Researcher retrievers (entry points) and produce cited
   deep-dive reports for top problems; a local OpenAI-compatible bridge for the CLI backend.
4. Commonplace book: one note per problem in any folder (`--notes-dir`), seed-free open-ended mode.
