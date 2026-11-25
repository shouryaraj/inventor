# 0002: Two LLM backends behind one client

Status: accepted (2026-11-25)

## Context
The first user runs Inventor through a Claude Code subscription, while public users are more
likely to have an API key. Both need the same guarantees: structured output, a spend cap, and
repeatable runs.

## Decision
One `LLMClient` (cache + budget + concurrency) over two backends:
* `claude-cli`: `claude -p --output-format json --json-schema …` with a custom system prompt,
  `--tools ""`, `--strict-mcp-config`, `--setting-sources ""`, `--no-session-persistence`, run from
  an empty temp directory. Measured overhead is about 1.1k input tokens per call, against about 23k
  with the default agent prompt.
* `anthropic-api`: the official `anthropic` SDK with `output_config.format` (JSON schema); cost
  computed from usage with a documented price table, and unknown models charged at the top price.

## Consequences
* The CLI's `total_cost_usd` is an API-equivalent estimate on subscription plans; it is still
  used as the budget unit.
* The CLI starts a process per call (about 1 s each); concurrency hides most of it.
* Model choice is by role (`fast`, `smart`) per backend and stays configurable.
