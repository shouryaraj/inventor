# 0001: GPT-Researcher as a dependency, not a fork

Status: accepted (2026-11-25)

## Context
Deep-dive reports on a found problem need multi-source research with citations. GPT-Researcher
(Apache-2.0, actively maintained) does this well and already ships OpenAlex, arXiv and Semantic
Scholar retrievers. Its job is different from ours, though: it *answers* a question, whereas
Inventor *finds* the questions.

## Decision
Build Inventor as its own MIT-licensed project and use GPT-Researcher as an optional dependency
(`inventor[deep]`) only for deep-dives. Our sources plug into it through its retriever entry-point
group `gpt_researcher.retrievers`, so no fork is needed.

## Consequences
* Upstream upgrades are a version bump, not a rebase.
* GPT-Researcher has no plugin hook for LLM providers. With an API key, use its built-in
  `anthropic` provider. With the Claude Code CLI, Inventor will run a localhost OpenAI-compatible
  bridge and point GPT-Researcher's `openai` provider at it through `OPENAI_BASE_URL`.
* If the bridge proves fragile, propose an upstream provider entry point rather than forking.
