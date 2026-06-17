# Search tools

Exa AI search engine.

## Exa AI search

A high-quality AI search engine, strong at technical and code search.

```bash
mcporter call 'exa.web_search_exa(query: "query", numResults: 5)'
mcporter call 'exa.get_code_context_exa(query: "code question", tokensNum: 3000)'
```

### Use cases

| Use case | Parameters |
|-----|------|
| Web search | `web_search_exa(query: "...", numResults: 5)` |
| Code search | `get_code_context_exa(query: "...", tokensNum: 3000)` |

### Strengths

- Strong at English content and technical documentation
- Supports code context search
- High result quality

## Comparison with other search tools

| Tool | Source | Use case |
|-----|------|---------|
| Exa | searchts | English / technical / code search |
| Zhipu search | my-mcp-tools | Chinese-language search |
| GitHub search | searchts (dev.md) | repo / code search |
