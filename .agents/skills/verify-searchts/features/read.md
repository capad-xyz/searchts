# Read a page

`searchts read <url>` is the core promise: hand it a URL that a browser would be
blocked by, get back clean markdown. One path, `unlocker.fetch`, escalating
curl_cffi → Jina Reader → stealth browser.

## Sub-features

- `read-basic` turns a reachable page into markdown with no boilerplate.
- `read-escalate` climbs to the next backend when the first returns thin or
  challenge content, and says which one answered.
- `read-json` emits the same result as a parseable object.
- `read-pages` follows `next_url` on the same site up to `--pages`.
- `read-scrub` redacts prompt-injection spans (`--scrub`).
- `read-items` follows list pages until `--items` rows, ceiling 300.
- `read-human` opens a headful browser for a page no tier could clear.
- `read-fail-loud` exits non-zero when no tier produced real content, rather
  than printing half a page and calling it a pass.

## How to get to it (user POV)

- `searchts read https://example.com`
- `searchts read <url> --json` when a script wants to read the result.
- `searchts read <url> --pages 3` for a multi-page article.
- `searchts read <url> --scrub` before feeding the text to another model.

## Driving it

Preconditions: `.venv` installed (see `../SKILL.md`), `doctor --json` reports
`github` and `youtube` `ok`.

- **Basic read.** `.venv/bin/python -m searchts read https://example.com --json > artifacts/read/example.json 2> artifacts/read/example.err`. Exit `0`.
- **Proof.** `artifacts/read/example.json` is a JSON object with `status: 200`,
  `chars` greater than 0, a `text` containing a phrase from the page, and a
  `backend` naming which tier answered.
- **Escalation is reported, not assumed.** Read the `backend` field. A `backend`
  of `curl_cffi` on a site that needs a browser is the ladder having answered
  early, which is fine; a `backend` of `null` with a long `text` is not.
- **Fail loud.** Read a URL that 404s: `.venv/bin/python -m searchts read https://raw.githubusercontent.com/pstack-dev/pstack/main/README.md`. Exit is non-zero and stderr names every tier that was tried. Exit `0` with an empty `text` would be a regression in the thing that matters most here.

## Gotchas

- **How many tiers are installed decides what you can prove.** `curl_cffi` needs
  nothing; `stealth-browser` needs `searchts install --browser`. On a machine
  without it, a `read` of a bot-walled page can only fail, and that is the
  environment, not the code. Check `doctor --json` for `web` before promising a
  hard read, and report the tier count with any verdict.
- Never pipe `read` into `head`. The broken pipe makes the CLI print a
  `BrokenPipeError` to stderr and the proof becomes the pipe, not the tool.
- `--json` and raw text are mutually exclusive outputs; pick one per drive.
- `--pages` follows only within one site and only via curl. A cross-site
  `next_url` is not followed.
- `--items` caps at 300 rows (`SEARCHTS_MAX_ITEMS`). Asking for more returns 300,
  not an error.
- A 404 page still has HTML. The CLI decides thin content is thin; do not add a
  "does it look like an error page" check on top of it.

## Proven here

Driven 2026-10-12 against `searchts v0.14.0`:

- `read https://example.com --json` → exit `0`, `status: 200`, `chars: 156`,
  `backend: curl_cffi`, text carries the page's own sentence.
- `read https://raw.githubusercontent.com/pstack-dev/pstack/main/README.md` →
  exit `1`, **0 bytes on stdout**, stderr naming all three tiers and why each
  gave up. Fail loud, with nothing half-printed for a caller to mistake for a
  page.