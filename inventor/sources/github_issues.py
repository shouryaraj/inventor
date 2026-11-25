"""GitHub issues via the REST search API.

Open issues sorted by reactions: requests many people want and nobody has built.
Token: GITHUB_TOKEN, else `gh auth token` if the GitHub CLI is logged in, else
anonymous (lower rate limit). API: https://docs.github.com/en/rest/search
"""

from __future__ import annotations

import os
import shutil
import subprocess
from functools import cache

from inventor.models import Signal
from inventor.sources.base import Source, clean_text, now_utc, parse_time, register_source

API = "https://api.github.com/search/issues"


@cache
def github_token() -> str | None:
    if token := os.environ.get("GITHUB_TOKEN"):
        return token
    if shutil.which("gh"):
        try:
            out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return out.stdout.strip() or None
    return None


@register_source
class GitHubIssues(Source):
    name = "github_issues"
    kind = "code"
    min_interval_s = 2.5  # search API: 30 requests/min authenticated

    @classmethod
    def available(cls) -> tuple[bool, str]:
        return True, "token found" if github_token() else "anonymous (10 searches/min)"

    async def search(self, query: str, limit: int) -> list[Signal]:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token := github_token():
            headers["Authorization"] = f"Bearer {token}"
        data = await self.get_json(API, headers=headers, params={
            "q": f"{query} is:issue is:open", "sort": "reactions", "order": "desc", "per_page": min(limit, 100),
        })
        retrieved = now_utc()
        signals = []
        for item in data.get("items", []):
            repo = item.get("repository_url", "").removeprefix("https://api.github.com/repos/")
            title = clean_text(item.get("title"), 300)
            body = clean_text(item.get("body"))
            signals.append(Signal(
                id=f"github_issues:{item['id']}",
                source=self.name,
                kind=self.kind,
                url=item["html_url"],
                title=f"{repo}: {title}" if repo else title,
                text=f"{title}. {body}".strip(),
                query=query,
                created_utc=parse_time(item.get("created_at")),
                retrieved_utc=retrieved,
                engagement={"reactions": int((item.get("reactions") or {}).get("total_count", 0)),
                            "comments": int(item.get("comments", 0))},
            ))
        return signals
