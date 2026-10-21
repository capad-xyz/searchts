# Search the web

Search the web finds pages from a query using keyless providers, merged by rank,
and prints them as a list or as JSON. Its claim is that it is keyless and free,
so a drive that needs a key is not proving the claim.

## Sub-features

- `search-basic` returns ranked hits from the default provider.
- `search-fusion` merges several providers and reconciles their ranking.
- `search-json` emits the hits with `title`, `url`, `snippet` and `source`.
- `search-optional-providers` add a tier when configured and are skipped when
  not.
- `search-empty` returns an empty list rather than an error when nothing matches.

## How to get to it (user POV)

- Run `searchts search "<query>"` for a human-readable list. The first line is `Snippets are not the page. Read each URL.`
- Run `searchts search "<query>" --json` for a parseable array. The same line is on stderr, so stdout stays the array.

## Driving it with searchts

Preconditions:

- `.venv` is installed as `SKILL.md` describes.
- No search API key is configured. A machine with one configured is not proving
  the keyless path and must be reported as such.
- The network reaches the default provider. Rate limiting is possible and is not
  a code failure; see Gotchas.

- **Basic search.** Run `.venv/bin/python -m searchts search "site:docs.python.org asyncio run" --json > artifacts/search/python-asyncio.json 2> artifacts/search/python-asyncio.err`. Exit code `0`.
- **Payload.** Read `artifacts/search/python-asyncio.json`. It is a JSON array, and its first element has all four keys `title`, `url`, `snippet` and `source`, with a `url` that begins `https://`.
- **Provider.** Read the `source` field. On a machine with no optional provider configured every hit names the same keyless provider, and that is the expected result rather than a failure to fuse.
- **Empty result.** Run `.venv/bin/python -m searchts search "zxqvw nonexistent phrase 9384" --json > artifacts/search/empty.json 2> artifacts/search/empty.err`. Exit code `0` and the array is empty. An error here would be a regression, because nothing matching is an answer.
- **Proof.** Open `artifacts/search/python-asyncio.json`. The first hit's `url` resolves to the documentation page the query named, which shows the ranking is returning the page rather than an array that merely parses.
- **Retry rather than conclude.** If a drive exits non-zero with an empty stdout, read the stderr, then run the same command up to five times and keep every attempt's stderr. Report the ratio of passes to attempts, never the best single run.

## Gotchas

- **A single failed run is not proof that search is broken, and a single pass is
  not proof that it is reliable.** The default provider rate-limits keyless
  callers. Measured on 2026-10-12: the same query, five times about four seconds
  apart, returned ten hits three times and exited non-zero with an empty stdout
  and a `No results found` error twice.
- Result order is provider-dependent and does not hold across runs. Assert on the
  shape of the first hit, never on a specific rank.
- Snippets are provider text and are trimmed. Do not assert on exact wording.
- An unconfigured optional provider costs nothing and produces nothing. A hit
  with an empty `source` would be a bug.
- Search hits the real network and that is the system under test. Do not stub it.