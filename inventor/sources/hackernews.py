"""Hacker News via the public Algolia search API (no key).

Searches both stories (Ask HN, Show HN, links with text) and comments, because
friction and workarounds usually live in the comments.
API: https://hn.algolia.com/api
"""

from __future__ import annotations

from datetime import timedelta

from inventor.models import Signal
from inventor.sources.base import Source, clean_text, now_utc, parse_time, register_source

API = "https://hn.algolia.com/api/v1/search"


@register_source
class HackerNews(Source):
    name = "hackernews"
    kind = "community"
    min_interval_s = 0.5

    def __init__(self, client, years: int = 3) -> None:
        super().__init__(client)
        self.years = years  # relevance search favours old classics; keep the evidence current

    async def search(self, query: str, limit: int) -> list[Signal]:
        signals: list[Signal] = []
        retrieved = now_utc()
        since = int((retrieved - timedelta(days=365 * self.years)).timestamp())
        for tag in ("story", "comment"):
            data = await self.get_json(API, params={"query": query, "tags": tag, "hitsPerPage": limit,
                                                    "numericFilters": f"created_at_i>{since}"})
            for hit in data.get("hits", []):
                text = clean_text(hit.get("comment_text") or hit.get("story_text"))
                title = clean_text(hit.get("title") or hit.get("story_title"), 300)
                if not text and not title:
                    continue
                signals.append(Signal(
                    id=f"hackernews:{hit['objectID']}",
                    source=self.name,
                    kind=self.kind,
                    url=f"https://news.ycombinator.com/item?id={hit['objectID']}",
                    title=title,
                    text=text or title,
                    query=query,
                    created_utc=parse_time(hit.get("created_at")),
                    retrieved_utc=retrieved,
                    engagement={k: int(hit[src]) for k, src in (("points", "points"), ("comments", "num_comments"))
                                if hit.get(src) is not None},
                ))
        return signals
