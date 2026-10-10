# Cookie / authenticated-read security review

Independent adversarial review of the new authenticated-read ("cookie") capability.

Scope: `searchts/session_cookies.py`, the `cookies` parameter on
`unlocker.fetch()`, `searchts/cdp_profile.py`, and their CLI wiring in
`cli.py`. Threat model: an agent reads pages using the user's own browser
cookies. The single unacceptable outcome is a live login token reaching a
third party or a site the user did not intend.

Method: every claim below was checked against source and, where it mattered,
reproduced by running the code. No source was modified (no critical leak was
found).

Snapshot reviewed: branch `feat/ux-first-run`, HEAD `894a9f3`, plus the
uncommitted feature files. Note: this worktree was being edited concurrently
during the review (`session_cookies.py` mtime `20:24:01`, `cli.py` `19:48:40`,
`unlocker.py` `19:09:22`). Final numbers below were re-run after the last
write.

| # | Check | Verdict | Evidence |
|---|-------|---------|----------|
| 1 | Can a cookie reach a relay (r.jina.ai / asset rungs) or a third party? | PASS | The cookie header is read at exactly one call site, `unlocker.py:1492-1494`, inside the `curl_cffi` branch only. `_fetch_jina(url, timeout)` (`:945`) takes no parameter that can carry a cookie and its call site (`:1499`) is bare; `_fetch_stealth` (`:1501`) is bare; the share and known-host extractors are called before the ladder and receive no cookies. `assets.py` has no `cookies` parameter and uses fixed headers. MCP `read_url` (`mcp_server.py:346`) has no `cookies` parameter and calls `read_items`/`read_pages` without them. This is a call-site fence, not a filter. |
| 1b | Could the Cookie ride a redirect to another host? | PASS (verified empirically) | The request is built against the scoped host; on redirect the raw `Cookie` header is dropped by the HTTP transport. Reproduced on the pinned `curl_cffi 0.16.3` with two local servers: same-origin redirect **retained** the Cookie, origin change (same host, new port) **dropped** it, and hostname change (`target.example` -> `attacker.example`, pinned via `CurlOpt.RESOLVE`) **dropped** it (`Cookie: None` at the attacker). |
| 2 | Host-scoping: can a foreign cookie ride along? | PASS | `_domain_matches` (`session_cookies.py:146-160`) requires an exact host match or a `.`-prefixed suffix, so `.amazon.in` rides on `www.amazon.in` but `notamazon.in` does not (the leading dot defeats a bare `endswith`). A cookie domain with no dot is a host, not a suffix: `com` matches `example.com` not at all, so a stray single-label cookie in a jar cannot sweep itself onto every site under that label. `filter_for_host` is applied to the whole jar in `fetch()` (`unlocker.py:1404-1411`) before any `name=value` string exists, and `save_owned_site` refuses to persist a jar with no cookie matching the host. |
| 3 | Does any code print or log a cookie value? | PASS (verified live) | `build_header` (`session_cookies.py:168`) is the only place a `name=value` string is produced, and it feeds only the outgoing `Cookie` header. Provenance uses `CookieSource.describe()` (`:124`), which prints count and site only. Live run with a planted secret (`LEAKME-secret-value-98765`) in `--cookies <file>`: stderr showed `cookies: file -> 1 cookies for https://example.com/`, and the secret appeared nowhere in stdout or stderr. curl_cffi failures do not embed request headers: three forced failures (connection refused, DNS timeout, bad IP) returned only libcurl error text, no `Cookie`. |
| 4 | Owned store owner-only and out of git? | PASS | `owned_store_path()` = `$HOME/.searchts/cookies/owned.json`, written through a temp file + atomic `os.replace`, chmod `0600`, dir `0700`. It lives under `$HOME`, not the repo; the repo `.gitignore` also lists `.searchts/`. Read path opens SQLite with `?mode=ro` (`_open_ro`), so a read cannot checkpoint a live WAL into the browser profile. |
| 5 | CDP: scratch profile deleted on success AND failure? | PASS | `_scratch_profile` (`cdp_profile.py:284-312`) is a generator whose `except BaseException` purges then re-raises, so the copy is deleted on success, on read failure, and on any `BaseException`. On the success path a purge failure raises rather than returning cookies while a full profile copy sits on disk; on the failure path the original exception wins and the leftover is named on stderr. |
| 6 | CDP: localhost-only, consent-gated, no lingering port? | PASS (verified live) | `_check_endpoint` (`cdp_profile.py:617-637`) accepts only loopback names/literals and ports 1-65535, before any client is built. Reproduced: `169.254.169.254`, `evil.com`, `10.0.0.1`, `192.168.1.5` all rejected; `127.0.0.1`, `localhost`, `::1` accepted; port `70000` rejected. An IPv4-mapped literal (`::ffff:127.0.0.1`) is rejected too: `parse_endpoint` splits at the last colon, so it reads as host `::ffff` and is refused as a non-loopback name, which is the direction to fail in. Consent gates the launch and `confirm=None` aborts rather than defaulting open. |
| 7 | Can cookies ever become the default? | PASS (verified live) | `fetch(..., cookies=None)` defaults to None. `_read_command_cookies` (`cli.py:1725-1732`) returns `None` unless `--cookies`, `--cookies-from-browser`, or `--cdp-port` is present. Live run without a flag produced no `cookies:` provenance line; with the flag it did. MCP `read_url` cannot pass cookies at all. |

## Verdict

No CRITICAL or MAJOR finding. The relay fence is structural, host-scoping is
correct and tested, no value is printed (proven live with a planted secret),
the owned store is `0600` and outside the repo, the CDP scratch profile is
purged on every path, the debugger endpoint is loopback-only and
consent-gated, and cookies are never on by default.

## Verification run

- `pytest tests -q` -> **1367 passed, 11 skipped**
- `pytest` on the cookie/CDP/CLI-cookie test files -> **127 passed, 1 skipped**
- `ruff check searchts tests` -> clean
- `mypy searchts/session_cookies.py searchts/cdp_profile.py` -> 0 errors in
  these modules; the only output is the 4 pre-existing Playwright
  `BrowserContext` errors in `unlocker.py`, unchanged by this work.

## Notes (not blocking)

- **The redirect defense is one layer, and that layer is libcurl.** searchts
  scopes the Cookie to the requested host, but does not re-filter after a
  redirect: `private_hop` only drops private final URLs, so a redirect to a
  *public* third party would be followed. Nothing leaks today because
  curl_cffi/libcurl strips the raw `Cookie` header on a host change (verified
  above on the pinned 0.16.3), but that is the HTTP transport's behavior, not
  a searchts-owned guarantee. If a future curl_cffi/libcurl release changed
  header handling, searchts would have no second layer. Hardening option:
  deliver cookies through the curl cookie engine (`COOKIELIST`, which is
  domain-scoped by construction) instead of a raw header, so the scoping
  invariant holds even if redirect handling changes.
- `save_owned_site` currently has no production caller (tests only), so the
  owned store is never written by the CLI today; `for_site()` reads it.
- On Windows the `0600`/`0700` chmod calls are skipped (`os.name == "nt"`);
  the file instead inherits the user-profile ACL. Tests do not assert the
  Windows ACL, only the POSIX mode.
- Chromium-family cookies cannot be read from disk on this machine
  (App-Bound Encryption); that path is reachable only through a user-opened
  `--cdp-port`, which is the intended design rather than a gap.
