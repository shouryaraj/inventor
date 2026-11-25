import asyncio

from conftest import json_transport

from inventor.sources import SOURCES, http_client
from inventor.sources.openalex import rebuild_abstract

HN = {"hits": [
    {"objectID": "101", "comment_text": "<p>Every vendor app is <i>terrible</i> &amp; slow</p>",
     "story_title": "Ask HN: Greenhouse tools?", "author": "someone", "points": None,
     "created_at": "2026-10-01T10:00:00Z"},
    {"objectID": "102", "title": "", "story_text": None},  # empty: skipped
]}
GH = {"items": [
    {"id": 7, "html_url": "https://github.com/o/r/issues/1", "title": "Add alerting for stale sensors",
     "body": "Our pumps failed silently.", "user": {"login": "someone"}, "reactions": {"total_count": 42},
     "comments": 5, "created_at": "2025-01-01T00:00:00Z", "repository_url": "https://api.github.com/repos/o/r"},
]}
OA = {"results": [
    {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/x", "title": "Greenhouse control",
     "abstract_inverted_index": {"Limitations": [0], "remain": [1], "unsolved.": [2]},
     "publication_date": "2024-05-01", "cited_by_count": 12},
    {"id": "https://openalex.org/W2", "title": "No abstract", "abstract_inverted_index": None},
]}


def search(name, routes):
    async def go():
        async with http_client(json_transport(routes)) as client:
            src = SOURCES[name](client)
            src.min_interval_s = 0
            return await src.search("greenhouse", 5)
    return asyncio.run(go())


def test_hackernews_cleans_html_and_drops_authors():
    signals = search("hackernews", {"hn.algolia.com": HN})
    # story + comment searches both return the canned page; empty hits are skipped
    assert {s.id for s in signals} == {"hackernews:101"}
    s = signals[0]
    assert s.text == "Every vendor app is terrible & slow"
    assert s.url == "https://news.ycombinator.com/item?id=101"
    assert "someone" not in s.model_dump_json()
    assert s.engagement == {}  # missing points stay missing, not 0


def test_github_issues_keeps_reactions_and_repo():
    [s] = search("github_issues", {"api.github.com": GH})
    assert s.title == "o/r: Add alerting for stale sensors"
    assert s.engagement == {"reactions": 42, "comments": 5}
    assert s.kind == "code" and "someone" not in s.model_dump_json()


def test_openalex_rebuilds_abstract_and_skips_works_without_one():
    [s] = search("openalex", {"api.openalex.org": OA})
    assert s.text == "Limitations remain unsolved."
    assert s.url == "https://doi.org/10.1/x" and s.engagement == {"citations": 12}
    assert rebuild_abstract(None) == ""
