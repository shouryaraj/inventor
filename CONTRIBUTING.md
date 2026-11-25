# Contributing

Setup: `uv sync`, then `uv run pytest -q` and `uv run ruff check .` (both offline).

## Add a source

1. Create `inventor/sources/<name>.py` with a `Source` subclass decorated with `@register_source`:
   set `name`, `kind` (`community` | `code` | `paper` | `startup`) and `min_interval_s`, and
   implement `async search(query, limit) -> list[Signal]` using `self.get_json(...)`.
2. Use `clean_text` for any text; keep an excerpt, the URL and engagement counts; **never store
   author names**. Missing counts stay missing (omit the key), never 0.
3. If it needs credentials, override `available()` to return `(False, "set XYZ_TOKEN")` when absent.
4. Import it in `inventor/sources/__init__.py`, document terms and limits in `docs/sources.md`,
   and add an offline test with a synthetic response in `tests/test_sources.py`.

## Add or change a lens

Lenses live in `inventor/lenses.py` (`LENSES`). Explain where the lens comes from in
`docs/lenses.md`. Changing the extraction prompt changes results: note it in the PR and compare
a run of the same seed before and after.

## Pull requests

Keep the honesty rules in [AGENTS.md](AGENTS.md). PRs that weaken quote verification or let
model output supply numbers will not be merged.
