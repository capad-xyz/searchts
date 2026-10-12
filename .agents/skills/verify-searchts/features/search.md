# Search the web

`searchts search "<query>"` fans out to keyless providers (DuckDuckGo by
default; SearXNG, Exa, Brave and Tavily optional) and reciprocal-rank fuses
them. The product's claim is that it is keyless and free, so a drive that needs
a key is not proving the claim.

## Sub-features

- `search-basic` returns ranked hits from the default provider alone.
- `search-fusion` merges several providers and reconciles their ranking.
- `search-json` emits the same hits as JSON with `title`, `url`, `snippet`,
  `source`.
- `search-optional-providers` add a tier when configured, and are skipped
  silently when not.

## How to get to it (user POV)

- `searchts search "site:docs.python.org asyncio run"`
- `searchts search "<query>" --json`

## Driving it

Preconditions: `.venv` installed, `doctor --json` run. No API key is configured
for any provider on a clean machine, so a drive that passes is evidence the
keyless path works.

- **Basic search.** `.venv/bin/python -m searchts search "site:docs.python.org asyncio run" --json > artifacts/search/python-asyncio.json 2> artifacts/search/python-asyncio.err`. Exit `0`.
- **Proof.** `artifacts/search/python-asyncio.json` is a JSON **array** (empty array is a legitimate answer, but for this query it is not) whose first element has all four keys `title`, `url`, `snippet`, `source`, and a `url` that starts with `https://`.
- **Source is named.** `source` says which provider the hit came from. Every hit
  saying `duckduckgo` on a machine with no other provider configured is the
  expected result, not a failure to fuse.
- **Empty is honest.** Search for a nonsense string. Exit `0` and `[]` is a pass;
  exit non-zero would be a regression, because "nothing matched" is an answer.

## The keyless path is the whole product, and it is flaky

Driven 2026-10-12, the **same query, five times, about four seconds apart**:

| Runs | Exit | Bytes on stdout | Reason |
|---|---|---|---|
| 3 of 5 | `0` | 2,700 | — |
| 2 of 5 | `1` | 0 | `duckduckgo: DDGSException: No results found.` |

When it fails it fails correctly: non-zero, empty stdout, the provider named.
That is the fail-loud rule doing its job. The problem is availability, not
honesty: with no optional provider configured, DuckDuckGo *is* the product, and
it rate-limits a keyless caller.

**For any drive:** retry up to five times and record which attempt succeeded. A
single attempt that fails is not a proof that search is broken, and a single
attempt that passes is not a proof that it is reliable. Report the ratio, not the
best run. A durable fix is a second configured provider, which is a config
change, not a code one.

## Gotchas

- Result order is provider-dependent and not stable across runs. Assert on the
  shape of the first hit, never on a specific rank.
- Snippets are provider text, trimmed. Do not assert on exact snippet wording.
- Optional providers that are unconfigured cost nothing and produce nothing. An
  empty `source` field would be a bug; a missing optional provider is not.
- Search hits the real network. Do not stub it; it is the system under test.
- A drive that retries must keep each attempt's stderr; "it worked on the third
  try" is only readable if the first two failures were kept.