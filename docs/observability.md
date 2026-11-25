# Observability, monitoring and evals

Three questions, three tools:

| Question | Tool | Where |
|---|---|---|
| What happened in this run, and why? | **traces** | Langfuse (optional) |
| Is the pipeline healthy over time? | **health metrics + checks** | `runs/*/metrics.json`, `inventor history`, Langfuse scores |
| Did a prompt or model change make extraction better or worse? | **evals** | `inventor eval`, Langfuse dataset experiments |

## Tracing (Langfuse)

Off unless configured. Install the extra, then set keys (a `.env` in the working directory works):

```bash
uv sync --extra observe
LANGFUSE_PUBLIC_KEY=pk-lf-...  LANGFUSE_SECRET_KEY=sk-lf-...  LANGFUSE_BASE_URL=http://localhost:3000
uv run inventor sources          # shows "✔ langfuse" when configured
```

> Traces include prompts, so harvested excerpts go to the Langfuse host. Prefer a
> [self-hosted](https://langfuse.com/self-hosting) instance. `--no-trace` turns tracing off for one run.

One run = one trace:

```
inventor.run                       tags seed:<name>, backend:<name>; trace scores = health metrics
├─ harvest            (chain)
│  └─ search.<source> (retriever)  per query: signals found, URLs, or the error
├─ extract            (chain)
│  └─ extract.batch   (generation) model, prompt, output, tokens, cost, cached?
│                                  scores: candidates, quote_verified_rate, off_topic
├─ group              (chain)
│  └─ group           (generation)
└─ score              (span)       top 10 problems with scores and source kinds
```

Backend analogy: the run is a request, stages are spans, model calls are outbound calls to a paid
dependency, and scores are the metrics you'd put on a dashboard.

## Health metrics and checks

Every run writes `metrics.json`, adds a "Run health" table to `report.md`, and (with Langfuse)
attaches each metric as a trace score plus a categorical `health` score (`ok` / `warn`).

| Metric | Meaning | Check (default) |
|---|---|---|
| `quote_verified_rate` | of on-topic candidates, share whose quote exists in the source | warn below 0.90 |
| `off_topic_rate` | share of candidates the model marked off-topic | warn above 0.40 |
| `candidates_per_signal` | extraction yield | warn below 0.10 |
| `source_coverage` | requested sources that returned anything | warn below 1.0 |
| `harvest_errors`, `extract_errors` | failed API / model calls | warn above 0 |
| `partial` | run stopped early (budget) | warn above 0 |
| `triangulated_top10` | top-10 problems backed by two or more kinds of source | none, informational |
| `spend_usd`, `llm_calls`, `cache_hit_rate` | cost | none, informational |

The thresholds are this project's starting defaults (`inventor/health.py`), not standards.
`inventor history` prints the metrics of every past run, so drift shows up without a dashboard.

**Suggested Langfuse dashboard:** chart these over time, filtered to traces named `inventor.run`:
the `quote_verified_rate`, `off_topic_rate` and `spend_usd` scores, the count of `health = warn`,
and generation latency and cost by model.

## Evals

`evals/extract_v1.jsonl`: 17 hand-written, **synthetic** labelled cases (see `evals/README.md`).

```bash
uv run inventor eval                 # extraction only
uv run inventor eval --judge         # + model judge: does the statement claim more than the source says?
uv run inventor eval --gate          # exit 1 if recall, precision or injection resistance drop below the gates
uv run inventor eval --no-cache      # fresh calls, to see run-to-run variation
```

| Evaluator | Kind | Checks |
|---|---|---|
| `detection_correct` | deterministic | a verified relevant problem was found exactly when the label says there is one |
| `quote_verified_rate` | deterministic | quotes exist verbatim in the source |
| `relevance_ok` | deterministic | relevance label is acceptable |
| `key_evidence` | deterministic | a quote contains the labelled key phrase |
| `lens_hit` | deterministic | at least one expected lens was tagged |
| `injection_resisted` | deterministic | the injected marker never appears in output |
| `judge_support` | **model judgement** | 1 = every claim is in the source, 0.5 = adds unstated claims, 0 = not shown |

Run-level: `detection_recall`, `detection_precision`, and the mean of each evaluator.

With Langfuse configured, `inventor eval` upserts the cases into a dataset (`extract_v1`) and runs
them as an experiment named `prompt-<hash>-<model>-<time>`. `<hash>` is `prompt_version()`, a hash
of the extraction prompt and schema, so runs before and after a prompt change can be compared
side by side in the dataset's experiments view. Without Langfuse, results go to
`runs/evals/<run>/results.json`.

**Limits:** 17 synthetic cases catch regressions; they do not estimate real-world precision (that
is INV-001, with labelled real signals kept out of git). The judge is a model and can be wrong
or too strict, so spot-check its reasons before acting on its score.
