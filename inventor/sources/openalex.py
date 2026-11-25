"""Research papers via OpenAlex (open catalogue of scholarly works).

The abstract is where authors state limitations and open problems. OpenAlex
stores abstracts as an inverted index, rebuilt here into text. Works from the
last `years` years only, so the signal reflects active research.
Optional: OPENALEX_API_KEY (larger daily budget), OPENALEX_EMAIL (identifies you).
API: https://docs.openalex.org
"""

from __future__ import annotations

import os
from datetime import date

from inventor.models import Signal
from inventor.sources.base import Source, clean_text, now_utc, parse_time, register_source

API = "https://api.openalex.org/works"


def rebuild_abstract(inverted: dict[str, list[int]] | None) -> str:
    if not inverted:
        return ""
    positions = [(pos, word) for word, where in inverted.items() for pos in where]
    return " ".join(word for _, word in sorted(positions))


@register_source
class OpenAlex(Source):
    name = "openalex"
    kind = "paper"
    min_interval_s = 0.2

    def __init__(self, client, years: int = 5) -> None:
        super().__init__(client)
        self.years = years

    @classmethod
    def available(cls) -> tuple[bool, str]:
        return True, "API key set" if os.environ.get("OPENALEX_API_KEY") else "no key (small daily budget)"

    async def search(self, query: str, limit: int) -> list[Signal]:
        params = {
            "search": query,
            "per_page": min(limit, 50),
            "sort": "relevance_score:desc",
            "filter": f"from_publication_date:{date.today().year - self.years}-01-01,has_abstract:true",
        }
        if key := os.environ.get("OPENALEX_API_KEY"):
            params["api_key"] = key
        if email := os.environ.get("OPENALEX_EMAIL"):
            params["mailto"] = email
        data = await self.get_json(API, params=params)
        retrieved = now_utc()
        signals = []
        for work in data.get("results", []):
            abstract = clean_text(rebuild_abstract(work.get("abstract_inverted_index")))
            if not abstract:
                continue
            native = work["id"].rsplit("/", 1)[-1]
            signals.append(Signal(
                id=f"openalex:{native}",
                source=self.name,
                kind=self.kind,
                url=work.get("doi") or work["id"],
                title=clean_text(work.get("title"), 300),
                text=abstract,
                query=query,
                created_utc=parse_time(work.get("publication_date")),
                retrieved_utc=retrieved,
                engagement={"citations": int(work.get("cited_by_count") or 0)},
            ))
        return signals
