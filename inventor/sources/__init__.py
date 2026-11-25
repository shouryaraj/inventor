"""Source plugins. Importing this package registers the built-in sources."""

from inventor.sources import github_issues, hackernews, openalex  # noqa: F401
from inventor.sources.base import SOURCES, Source, http_client, register_source

__all__ = ["SOURCES", "Source", "http_client", "register_source"]
