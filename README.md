# Inventor

**Find real problems worth solving, with evidence.**

Most idea tools generate ideas. Inventor goes the other way: it reads what people actually
write (forum threads, GitHub issues, research abstracts) and looks for problems the way
inventors observe the world. It looks for friction, workarounds, things that don't work,
stated research limitations, design failures and defaults worth questioning. It keeps only
problems backed by a **verbatim quote it can find in the source**.

```
harvest ──► extract (LLM) ──► verify (code) ──► group (LLM, checked) ──► score (code) ──► report
HN · GitHub · OpenAlex   inventor lenses    quote must exist        nothing lost/invented     explainable
```

> **What it is not:** a market validator. Output is a ranked list of *candidate* problems with
> links to the evidence. Read the evidence, then talk to the people who have the problem.

## Quick start

```bash
git clone <this repo> && cd inventor
uv sync
uv run inventor sources                      # which sources are usable on this machine
uv run inventor run --seed cea --budget-usd 2
# -> runs/cea-<timestamp>/report.md (+ signals.jsonl, candidates.jsonl, problems.json)
```

**LLM backends:**

| Backend | Needs | Flag |
|---|---|---|
| Claude Code CLI (default) | `claude` installed and logged in | `--backend claude-cli` |
| Anthropic API | `pip install 'inventor[api]'`, `ANTHROPIC_API_KEY` | `--backend anthropic-api` |

**Cost:** each run has a hard cap (`--budget-usd`, `--max-calls`). Responses are cached in
`runs/.cache`, so re-running the same seed is free. Our first runs of the `cea` seed (160–170
signals, 21–24 calls on the fast model) cost US$0.05–0.07 as reported by the CLI.

## Sources

| Source | Kind | Credentials | Notes |
|---|---|---|---|
| `hackernews` | community | none | Algolia API, stories + comments, last 3 years |
| `github_issues` | code | optional `GITHUB_TOKEN` (or `gh auth token`) | open issues by reactions |
| `openalex` | paper | optional `OPENALEX_API_KEY` | abstracts from the last 5 years |

Planned: YC startups (yc-oss dataset), research-area growth, Reddit and Product Hunt (off
unless you provide credentials). See [docs/sources.md](docs/sources.md) for terms and limits.

## Observability and evals

```bash
uv run inventor eval --judge        # 17 labelled synthetic cases; recall, precision, injection, overclaim
uv run inventor history             # health metrics of every past run
uv sync --extra observe             # + LANGFUSE_* keys: every run becomes a Langfuse trace
```

Each run checks its own health (quote integrity, off-topic rate, yield, source coverage, errors)
and writes `metrics.json`. With [Langfuse](https://langfuse.com) configured, runs are traced stage
by stage, model calls are recorded with tokens and cost, and evals run as dataset experiments
labelled with the prompt version. See [docs/observability.md](docs/observability.md).

## Seeds

A seed is a domain plus search queries per source: [`inventor/seeds/cea.toml`](inventor/seeds/cea.toml)
(controlled-environment agriculture). Write your own and pass its path: `--seed my-domain.toml`.

## How it stays honest

* **Quotes are verified by code.** A problem without a quote that appears in its source is dropped.
* **Relevance is labelled, not hidden.** The model marks each problem core, adjacent or off-topic
  for the seed's domain. Off-topic ones are rejected and counted in the report.
* **Numbers come from code.** Scores are computed from signal counts, source diversity,
  engagement and recency, and every component is shown.
* **Signal text is treated as data.** Prompts fence it off and tell the model to ignore
  instructions inside it.
* **No personal data.** Author names and handles are never stored. Harvested data stays in
  `runs/`, which is git-ignored.

## Docs

* [Architecture](docs/architecture.md) · [Lenses](docs/lenses.md) · [Sources](docs/sources.md) ·
  [Observability and evals](docs/observability.md)
* Decisions: [0001 dependency, not fork](docs/decisions/0001-gpt-researcher-as-dependency.md) ·
  [0002 LLM backends](docs/decisions/0002-llm-backends.md)
* [Contributing](CONTRIBUTING.md): add a source or a lens

## Licence

MIT. Inventor calls third-party APIs; follow each source's terms of use.
