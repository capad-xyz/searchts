# Keep and use a site login

The login commands copy cookies for one requested host from a browser the user
names, store them in searchts when asked, and let a later read use that saved
login.

## Sub-features

- `login-copy` reads only the requested site's cookies from Zen or Vivaldi.
- `login-consent` requires `--yes` before copying browser cookies.
- `login-keep` saves the selected site's cookies in the searchts store.
- `login-reuse` uses the saved cookies on a later plain read.
- `login-list` lists kept hosts and cookie counts without values.

## How to get to it (user POV)

- Run `searchts login keep <url> --cookies-from-browser zen --yes` to save a
  login from Zen.
- Run the same command with `vivaldi` to save a login from Vivaldi.
- Run `searchts read <url>` to use a saved login.
- Run `searchts login list` to see saved hosts, or `searchts login kill <url>`
  to remove one saved login.

## Driving it with searchts

Preconditions: the chosen browser is signed in to the requested host. Vivaldi
also needs the browser extra installed with `searchts install --browser`.

- **Keep from Zen.** Run `searchts login keep <url> --cookies-from-browser zen --yes`. Exit code `0`; the receipt names the host and cookie count, and prints no values.
- **Keep from Vivaldi.** Run `searchts login keep <url> --cookies-from-browser vivaldi --yes`. Exit code `0`; stderr explains the local debugger window, the receipt names the host and cookie count, and no cookie values are printed.
- **Reuse.** Run `searchts read <same-url> --json`. Stderr says `cookies: owned store`; assert the JSON says `authenticated: true` and its `text` contains a signed-in-only marker for that site. A live drive succeeded through both `curl_cffi` and `stealth-browser`. The response body was not retained because the verified page was personal account settings.
- **Browser rung.** Run `searchts read <same-url> --json --backend stealth-browser`. Assert `authenticated: true` and the site's signed-in-only marker. The temporary local context receives only host-scoped cookies; the Jina relay never receives them.
- **No approval.** Run `searchts login keep https://example.org --cookies-from-browser zen` without `--yes`. It exits `3`, prints the approval requirement, produces empty stdout, and stores nothing.
- **Forget.** Run `searchts login kill <url>`. The next bare read no longer uses the stored login.

## Gotchas

- `login keep` stores cookies, but cannot decide whether the browser was truly signed in. Prove reuse by reading a signed-in-only page and checking its payload.
- `--cookies-from-browser` is scoped to the requested URL's host. A cookie for another site is never sent with the read.
- If the browser rung is needed, searchts adds those same scoped cookies to a temporary Playwright context. It does not copy them into the persistent stealth profile, and it does not send them to Jina.
- Vivaldi's cookies are not decrypted from disk. The debugger window and disposable copy are part of its explicit copy path; the original profile is left alone.
- A saved login can expire. `login list` shows that a host is stored, not that the site's session is still valid.
- A successful cookie copy proves only that cookies were found. A signed-in-only page marker proves that the site accepted them.
