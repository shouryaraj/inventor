# Eval sets

`extract_v1.jsonl`: 17 **synthetic** cases for the extraction step, written by hand for this
project. They are not harvested data and describe no real person or product. Each case has:

| Field | Meaning |
|---|---|
| `input.domain`, `input.signal` | what the extractor sees |
| `expected.has_problem` | is there a real, relevant problem in the text? |
| `expected.relevance` | acceptable relevance labels for the problem |
| `expected.key_phrase` | a verified quote should contain this phrase, or one of a list (case-insensitive) |
| `expected.lenses_any` | at least one of these lenses should be tagged |
| `expected.forbidden` | must not appear in any output (prompt-injection check) |

Categories: workarounds, things that don't work, Norman design failures, research limitations,
unmet needs, a buried problem, an adjacent-domain problem, a second domain (observability),
negatives (launch post, praise, neutral abstract, off-topic bugs) and one prompt injection.

Seventeen cases catch regressions; they do not measure real-world precision. That takes labelled
real signals (INV-001), which stay out of git.
