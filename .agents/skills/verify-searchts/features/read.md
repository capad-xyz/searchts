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
- `read-items` follows list pages until `--items` rows are kept, and scrolls a
  list that only grows that way.
- `read-expand` opens closed `<details>` and read/show/see-more buttons with
  `--expand`, and names a paywall instead of opening it.
- `read-ceilings` clamps `--pages`, `--items` and the expand presses to the
  user's own ceiling and says so on the text the caller reads.
- `read-scrub` redacts prompt-injection spans on request.
- `read-backend` forces one tier with `--backend`.
- `read-human` opens a headful browser for a page no tier could clear.
- `read-fail-loud` exits non-zero with empty stdout when no tier produced content.

## How to get to it (user POV)

- Run `searchts read <url>` for markdown on stdout.
- Run `searchts read <url> --json` for a parseable object.
- Run `searchts read <url> --pages 3` for a multi-page article.
- Run `searchts read <url> --items 50` to walk list pages until 50 rows, then
  scroll the page in the browser when that is the only way it grows more.
- Run `searchts read <url> --expand` to open the text the page is holding back.
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

### Scrolling a list (`--items`)

Preconditions:

- `searchts install --browser` has been run in this run. Without it the read
  cannot scroll, and it says so instead.

- **Scroll.** Run `.venv/bin/python -m searchts read https://meta.discourse.org/latest --items 70 > artifacts/read/items-scroll.out 2> artifacts/read/items-scroll.err`. Exit code `0` and `items-scroll.out` ends with a `[scroll: ...]` line naming how many rows were collected, how many steps it took and why it stopped, for example `[scroll: 90 list row(s) after 2 scroll step(s); reached the 70 rows asked for]`.
- **Payload.** Count the distinct topic links in `items-scroll.out`. More than the number of rows on one screen of the page is the scroll having worked, and the `[scroll:` line's row count agrees with it.
- **A second feed.** Drive `https://discuss.python.org/latest --items 60` the same way. A feed that scrolls must not be a one-page accident.
- **A wall.** Drive `https://www.reddit.com/r/python/ --items 70`. On a box where every tier is challenged, exit code is non-zero, stdout is empty and stderr names the wall per tier. That is `read-fail-loud` reached through `--items`, and it is not a scroll bug.
- **No browser.** On a box with no browser installed, drive a list URL with
  `--items`. The text ends with `[scroll: this list only grows in the browser.
  Run: searchts install --browser]` and the exit code is still `0`, because the
  page itself was read. The note is the proof.

### Opening the folds (`--expand`)

Preconditions:

- `searchts install --browser` has been run in this run when the fold is a
  button. A closed `<details>` needs no browser.

- **A folded page.** Run `.venv/bin/python -m searchts read https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/details --expand > artifacts/read/expand.out 2> artifacts/read/expand.err`. Exit code `0` and the text ends with `[expand: N <details> section(s) opened]`.
- **Off by default.** Drive the same URL without `--expand` and the line is
  absent. A plain read must not press anything.
- **A paywall is named, not opened.** Run `.venv/bin/python -m searchts read https://www.washingtonpost.com/opinions/2026/10/14/donald-trump-chaos-sows-gop-midterm-troubles/ --expand > artifacts/read/expand-paywall.out 2> artifacts/read/expand-paywall.err`. The text ends with `[expand: the rest of this article is behind a paywall ("continue reading"). searchts names it and does not work around it]`. Drive the same URL without `--expand` and compare the byte counts: the difference is the note, not article text. That comparison is the proof that nothing was bypassed.
- **A button.** Drive a page whose "Show more" is built in JavaScript with
  `--expand`. The note reads `[expand: N button(s) pressed ("Show more", ...)]`
  **or** `[expand: nothing on the rendered page answered to a read/show/see-more
  button]`. Both are honest answers and which one you get depends on hydration
  having finished, so record the one you saw rather than asserting one.

### The ceilings

- **Clamp.** Run `SEARCHTS_MAX_ITEMS=20 .venv/bin/python -m searchts read https://meta.discourse.org/latest --items 90 --json > artifacts/read/clamp.json 2> artifacts/read/clamp.err`. The object carries a `text` containing `[items: asked for 90, the ceiling is 20]`, and the row count in the text is at most 20.
- **The note lands on page one.** Assert the note is inside `text`, not only in
  `warnings`. The CLI prints the text of the first page and the MCP envelope
  carries it in `text`, so a note on the last page is a note nobody reads.
- **The agent cannot raise it.** The same drive with `SEARCHTS_MAX_ITEMS=900
  --items 90` returns 90 rows and says nothing about a ceiling: the flag is the
  request and the env var is the policy.

## Gotchas

- Never pipe a read into `head`. The broken pipe makes the CLI print a
  `BrokenPipeError` to stderr and the artifact becomes the pipe.
- `--json` and raw markdown are different outputs. Pick one per drive.
- `--pages` follows only within one site and only through the first tier. A
  cross-site `next_url` is not followed.
- `--items` returns at most 300 rows and does not error when asked for more.
- `--items` counts markdown list lines as rows. A feed laid out as a table
  counts as zero rows, so the walk always looks short and the scroll always
  runs. Read the `[scroll:` line, not `item_count`, to know how many rows came
  back.
- `--items` and `--pages` together use `--items` and warn on stderr.
- `--expand` needs a browser for a button, and the button may not be there yet.
  "nothing on the rendered page answered" after a press succeeded earlier on the
  same URL is hydration, not a regression. Re-drive before believing it.
- `--expand` drops the Jina relay from the ladder, because a relay returns
  markdown and cannot be told to press a button. A `--expand` read therefore
  never hands its URL to the relay, and an unexpanded read still may.
- `--expand` never presses a link, a form control or a sign-in, and names a
  "continue reading" paywall instead of opening it. A named paywall with a short
  body is the correct outcome, not a failure.
- A 404 page is still HTML. The verb decides thin content is thin; do not add a
  "does this look like an error page" check on top of it, because that check
  would have hidden the fail-loud behaviour above.
- `example.com` is a reserved documentation domain and is deliberately empty.
  It proves the ladder and the JSON shape. It proves nothing about extraction.