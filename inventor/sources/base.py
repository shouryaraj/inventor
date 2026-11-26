"""Source plugin contract and shared helpers.

A source turns a search query into `Signal`s. Rules every source follows:
* public data only, through the documented API, within its rate limits;
* keep an excerpt (not the whole document), the URL and engagement counts;
* never keep author names or handles;
* `available()` says whether credentials are present, so a source can ship
  disabled instead of failing.
"""

from __future__ import annotations

import asyncio
import html
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx

from inventor import __version__
from inventor.models import Signal, SourceKind

USER_AGENT = f"inventor/{__version__} (open-source problem finder)"
MAX_EXCERPT_CHARS = 2000

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_FENCE = re.compile(r"</?\s*signal\b", re.IGNORECASE)  # the prompt's own fence; never let data forge it


def clean_text(raw: str | None, limit: int = MAX_EXCERPT_CHARS) -> str:
    """Strip HTML, unescape entities, collapse whitespace, cut to `limit` characters."""
    if not raw:
        return ""
    text = html.unescape(_TAG.sub(" ", raw.replace("<p>", "\n")))
    text = _FENCE.sub(" ", text)  # entities decode after tags are stripped, so `&lt;/signal&gt;` would get through
    text = _SPACE.sub(" ", text).strip()
    return text[:limit]


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def now_utc() -> datetime:
    return datetime.now(UTC)


class Source:
    name: ClassVar[str]
    kind: ClassVar[SourceKind]
    min_interval_s: ClassVar[float] = 1.0  # politeness floor between requests

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self._lock = asyncio.Lock()
        self._last = 0.0

    @classmethod
    def available(cls) -> tuple[bool, str]:
        return True, "no credentials needed"

    async def search(self, query: str, limit: int) -> list[Signal]:
        raise NotImplementedError

    async def get_json(self, url: str, params: dict[str, Any] | None = None,
                       headers: dict[str, str] | None = None) -> Any:
        """GET with a per-source rate limit and one polite retry on HTTP 429."""
        for attempt in range(2):
            async with self._lock:
                wait = self.min_interval_s - (time.monotonic() - self._last)
                if wait > 0:
                    await asyncio.sleep(wait)
                self._last = time.monotonic()
                resp = await self.client.get(url, params=params, headers=headers)
            if resp.status_code == 429 and attempt == 0:
                await asyncio.sleep(min(float(resp.headers.get("retry-after", 10)), 60))
                continue
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()  # pragma: no cover - loop always returns or raises


SOURCES: dict[str, type[Source]] = {}


def register_source(cls: type[Source]) -> type[Source]:
    if cls.name in SOURCES:
        raise ValueError(f"source {cls.name!r} already registered")
    SOURCES[cls.name] = cls
    return cls


def http_client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=30.0,
                             follow_redirects=True, transport=transport)


Factory = Callable[[httpx.AsyncClient], Source]
