# Read a page

Read a page turns a URL a browser would be refused into clean markdown, through
an escalating ladder of fetch backends, and says which backend answered. It
prints nothing and fails loudly when no tier produced real content.

## Sub-features

- `read-basic` turns a reachable page into markdown.
- `read-escalate` climbs to a later tier when the first returns thin or challenge
  content, and names the one that answered.
- `read-json` emits the same result as a parseable object.
- `read-pages` follows the next page on the same site up to `--pages`.
- `read-items` follows list pages until `--items` rows are kept.
- `read-scrub` redacts prompt-injection spans on request.
- `read-backend` forces one tier with `--backend`.
- `read-human` opens a headful browser for a page no tier could clear.
- `read-fail-loud` exits non-zero with empty stdout when no tier produced content.

## How to get to it (user POV)

- Run `searchts read <url>` for markdown on stdout.
- Run `searchts read <url> --json` for a parseable object.
- Run `searchts read <url> --pages 3` for a multi-page article.
- Run `searchts read <url> --items 50` to walk list pages until 50 rows.
- Run `searchts read <url> --scrub` before passing the text to another model.

## Driving it with searchts

Preconditions:

- `.venv` is installed as `SKILL.md` describes.
- `doctor --json` has been run and its `web` message has been read. A missing
  tier is why a bot-walled URL cannot be proved here, and it must be recorded as
  an unmet precondition rather than a failure.

- **Basic read.** Run `.venv/bin/python -m searchts read https://example.com --json > artifacts/read/example.json 2> artifacts/read/example.err`. Exit code `0`.
- **Payload.** Read `artifacts/read/example.json`. It is a JSON object with `status`, `chars`, `text` and `backend`. `status` is `200`, `chars` is greater than `0`, and `text` contains a phrase from the page.
- **Which tier answered.** Read the `backend` field. A `backend` of `curl_cffi` on a site that needs a browser is the ladder having answered early, which is a pass. An empty or `null` `backend` beside a long `text` is not.
- **Fail loud.** Read a URL that does not exist. Run `.venv/bin/python -m searchts read https://raw.githubusercontent.com/pstack-dev/pstack/main/README.md > artifacts/read/missing.out 2> artifacts/read/missing.err`. Exit code is non-zero, `artifacts/read/missing.out` is empty, and `artifacts/read/missing.err` names every tier that was tried and why each gave up.
- **Pagination.** Run `.venv/bin/python -m searchts read https://example.com --pages 2 --json > artifacts/read/pages.json 2> artifacts/read/pages.err`. Exit code `0` and the object carries a `pages` array with one entry per page actually followed, which on a single-page site is one entry and not the two that were asked for. Assert on the array's presence, not on its length matching the flag.
- **Proof.** Open `artifacts/read/example.json` and `artifacts/read/missing.err` side by side. Together they show one fetch that returned content and named its tier, and one that returned nothing on stdout and named all three tiers.
- **Report an unreachable tier.** If `doctor`'s `web` entry shows a tier missing, do not drive a bot-walled URL and call the failure a bug. Record the missing tier and the command attempted.

## Gotchas

- Never pipe a read into `head`. The broken pipe makes the CLI print a
  `BrokenPipeError` to stderr and the artifact becomes the pipe.
- `--json` and raw markdown are different outputs. Pick one per drive.
- `--pages` follows only within one site and only through the first tier. A
  cross-site `next_url` is not followed.
- `--items` returns at most 300 rows and does not error when asked for more.
- A 404 page is still HTML. The verb decides thin content is thin; do not add a
  "does this look like an error page" check on top of it, because that check
  would have hidden the fail-loud behaviour above.
- `example.com` is a reserved documentation domain and is deliberately empty.
  It proves the ladder and the JSON shape. It proves nothing about extraction.