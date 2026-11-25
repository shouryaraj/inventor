---
name: inventor
description: Look at a domain, a text, a product or an everyday situation the way inventors do. Find friction, workarounds, things that don't work, design failures, defaults worth questioning, and cross-domain associations, backed by evidence. Use when the user says "inventor lens", "find problems in…", "what's broken about…", "observe this", or wants to run or interpret the inventor problem-finding pipeline.
---

# Inventor lens

Observation is a skill: describe what is there before interpreting it. Problems come first;
solutions come later and are labelled as hypotheses.

## When the user gives you text, a product, a workflow or a domain

1. **Observe, don't interpret.** List what is literally there or literally said. Quote the
   source; never paraphrase evidence into something stronger.
2. **Apply the lenses** (ids match `inventor/lenses.py`):
   - friction, workaround, doesnt_work, unmet_need, limitation_future_work
   - Norman's design checks: affordance, signifier, constraint, mapping, feedback, conceptual model
     (and the gulfs of execution and evaluation: "how do I do it?" and "what just happened?")
   - questioned_default ("why must it be this way?")
   - already_changing (a shift that has begun and is creating new problems)
3. **Question.** For each problem ask "why does this happen?", "why is this the pattern?" and
   "who has found a better way in a different environment?"
4. **Associate.** Name one or two fields where a similar problem was solved (exaptation,
   biomimicry, the adjacent possible). Label each as **hypothesis** with a way to check it.
5. **Write it as a commonplace-book entry:** problem statement (who struggles with what), evidence
   quote and link, lenses, current workaround, open questions, and a "hunch" line left for the user.

## Rules

- No quote, no problem. If evidence is missing, say what you would need to observe.
- Do not invent numbers, market sizes or users. Mark guesses as guesses.
- Prefer problems people already work around: a workaround is proof of pain.
- Outsider eyes are an asset. Ask the naive question an expert would skip.
- End with one small experiment or conversation that would test the most promising problem.

## Running the pipeline

`uv run inventor run --seed <name-or-path.toml> --budget-usd 2` writes `runs/<id>/report.md`.
When interpreting a report, separate what the evidence shows from your reading of it, and point
out any problem whose quotes are weak, old or off-topic.
