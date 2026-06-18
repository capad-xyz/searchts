# Search

Keyless multi-provider web search.

## Web search (`searchts search`)

```bash
# Keyless multi-provider web search; prints ranked title + url + snippet
searchts search "open source vector db" -n 10

# Structured output
searchts search "open source vector db" --json

# Force a single provider
searchts search "query" --provider duckduckgo
```

**Use case**: the primary way to search the web. `searchts search` queries
multiple providers and merges them with reciprocal-rank fusion, de-duplicating
results. DuckDuckGo is the keyless default; SearXNG, Exa, Brave, and Tavily
merge in automatically when configured. Once you have URLs, read them with
`searchts read <url>`.

## Optional providers

More and better results come from configuring extra providers (all optional):

- A self-hosted `SEARXNG_URL`.
- Exa, Brave, or Tavily API keys.

Set them with `searchts configure` or a `.env`, then run `searchts doctor` to
confirm which providers are active. No keys are required to search.
