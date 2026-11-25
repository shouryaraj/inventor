# Sources: access, limits, terms

Inventor uses only documented public APIs, identifies itself with a User-Agent, spaces its
requests (`min_interval_s` per source), retries once on HTTP 429, keeps excerpts (≤ 2,000
characters) rather than full documents, and never stores author names.

| Source | Endpoint | Auth | Limits we respect | Terms |
|---|---|---|---|---|
| Hacker News | `hn.algolia.com/api/v1/search` | none | 0.5 s between requests | [HN API](https://hn.algolia.com/api) |
| GitHub issues | `api.github.com/search/issues` | `GITHUB_TOKEN` or `gh auth token`, optional | search API: 30 req/min with a token, 10 without; we wait 2.5 s | [GitHub REST search](https://docs.github.com/en/rest/search) |
| OpenAlex | `api.openalex.org/works` | `OPENALEX_API_KEY`, optional | budget-based daily limits; no key = small budget | [OpenAlex rate limits](https://docs.openalex.org/how-to-use-the-api/rate-limits-and-authentication) |

## Planned

| Source | Status | Why |
|---|---|---|
| YC companies (`yc-oss.github.io/api`) | slice 2 | community-maintained open dataset of YC companies; shows crowded areas vs gaps |
| Reddit | off unless `REDDIT_CLIENT_ID`/`SECRET` | unauthenticated requests return 403; the Data API needs a registered, approved app, and its free tier is for non-commercial use |
| Product Hunt | off unless `PRODUCTHUNT_TOKEN` | the GraphQL API requires a token |

Check each provider's current terms before heavy or commercial use. They change.
