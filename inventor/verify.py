"""Deterministic evidence check: the anti-hallucination rule.

A candidate survives only if its evidence quote really appears in the signal it
cites. Comparison ignores case, whitespace, quote styles and dashes. A quote
with an ellipsis is checked part by part, in order.
"""

from __future__ import annotations

import re
import unicodedata

MIN_QUOTE_CHARS = 15
MIN_PART_CHARS = 8

_TRANSLATE = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})
_SPACE = re.compile(r"\s+")
_ELLIPSIS = re.compile(r"\.\.\.|…|\[\.\.\.\]")


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_TRANSLATE).lower()
    return _SPACE.sub(" ", text).strip()


def strip_wrapping(quote: str) -> str:
    q = quote.strip()
    while len(q) >= 2 and q[0] == q[-1] and q[0] in "\"'`":
        q = q[1:-1].strip()
    return q.strip("\"'“”‘’ ")


def quote_in_text(quote: str, text: str) -> tuple[bool, str | None]:
    """Return (ok, reason). Reason is None when ok."""
    q = strip_wrapping(quote)
    if len(q) < MIN_QUOTE_CHARS:
        return False, "quote_too_short"
    haystack = normalise(text)
    parts = [normalise(p) for p in _ELLIPSIS.split(q) if normalise(p)]
    if any(len(p) < MIN_PART_CHARS for p in parts):
        return False, "quote_too_short"
    pos = 0
    for part in parts:
        found = haystack.find(part, pos)
        if found < 0:
            return False, "quote_not_found"
        pos = found + len(part)
    return True, None
