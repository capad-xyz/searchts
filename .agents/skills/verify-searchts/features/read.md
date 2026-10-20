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
- `read-paginated` names the next page of a paginated list, and says which knob
  asks for the rest (`--pages`, `--items`), and stays silent on a page that is
  not paginated.
- `read-items` follows list pages until `--items` rows are kept, and scrolls a
  list that only grows that way.
- `read-expand` opens closed `<details>` and read/show/see-more buttons with
  `--expand`, and names a paywall instead of opening it.
- `read-reddit` reads a Reddit listing, thread, profile or search page as cards,
  follows Reddit's own next-post cursor for `--items`, opens its "more replies"
  controls for `--expand`, and names each wall it finds (private, banned,
  quarantined, over-18, gone, archived) instead of returning the nav bar.
- `read-ceilings` clamps `--pages`, `--items` and the expand presses to the
  user's own ceiling and says so on the text the caller reads.
- `read-scrub` redacts prompt-injection spans on request.
- `read-backend` forces one tier with `--backend`.
- `read-human` opens a headful browser for a page no tier could clear.
- `read-fail-loud` exits non-zero with empty stdout when no tier produced content.
- `read-page-data` reads words the page only ships as data (`<script
  type="application/ld+json">`, an app-state script named `__SOMETHING__`) out of
  the bytes already downloaded, and says `[source: ...]` when the data supplied
  them.
- `read-plain-text` treats a body the server sent as text (`text/plain`,
  `application/json`, markdown) as the page, not as markup to extract.
- `read-challenge` names a bot check that stands in front of the page, and never
  returns one as the article.

## How to get to it (user POV)

- Run `searchts read <url>` for markdown on stdout.
- Run `searchts read <url> --json` for a parseable object.
- Run `searchts read <url> --pages 3` for a multi-page article.
- Run `searchts read <url> --items 50` to walk list pages until 50 rows, then
  scroll the page in the browser when that is the only way it grows more.
- Run `searchts read <url> --expand` to open the text the page is holding back.
- Run `searchts read <url> --scrub` before passing the text to another model.
- Run `searchts read https://www.reddit.com/r/<sub>/hot/ --items 40` for more
  posts than the first window, and `searchts read <reddit thread url> --expand`
  for deeper comments.

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
- **A paginated list says so.** Run `.venv/bin/python -m searchts read "https://news.ycombinator.com/news?p=2" --json > artifacts/read/paginated.json 2> artifacts/read/paginated.err`. Exit code `0`, `more` carries a `next-page` entry with `next_url` set to the page after this one and a `paginated` entry naming `--pages` / `--items`; `text` contains that paginated note. Other notes such as media may follow it. On a page with no pagination at all, `more` must carry neither entry: the note may not appear where there is no next page.
- **Proof.** Open `artifacts/read/example.json` and `artifacts/read/missing.err` side by side. Together they show one fetch that returned content and named its tier, and one that returned nothing on stdout and named all three tiers.
- **Report an unreachable tier.** If `doctor`'s `web` entry shows a tier missing, do not drive a bot-walled URL and call the failure a bug. Record the missing tier and the command attempted.

### A body the server already sent as text

Driven on 2026-10-20 from this box, with the browser tier installed. A body
whose Content-Type is text (not markup) is the page, and the extractor must
not eat it.

- **A README is the file.** Run `.venv/bin/python -m searchts read https://raw.githubusercontent.com/capad-xyz/searchts/main/README.md --json > artifacts/read/raw-readme.json 2> artifacts/read/raw-readme.err`. Exit code `0`, `chars` is the size of the served file (25,397 on that day, against a 25,267-byte body), and `text` holds the file's first line and its last line. Before 2026-10-20 this drive returned 8,852 characters of 24,112 and said "16,274 characters are in blocks this read did not return": the article extractor read the markdown as markup and dropped the centred image blocks and the prose around them.
- **Proof.** Compare `chars` with the size of the file the server serves. A read that is a fixed fraction of it is a read that lost something.
- **Markup mislabelled as text is still extracted.** A server that sends a whole page under `text/plain` is still a page; the extractor reads it. Assert on the prose being present, not on the raw bytes.

### A bot check in front of the page

Driven on 2026-10-20 from this box, against pypi.org's F5/Shape client
challenge. A challenge is a wall: it is named, and it is never the article.

- **The shell is not the page.** Run `.venv/bin/python -m searchts read https://pypi.org/project/requests/ --json > artifacts/read/pypi.json 2> artifacts/read/pypi.err`. Two answers are correct and both were seen on that day: exit `0` with the project page (`chars` in the thousands, `text` holding the project's own summary), or exit non-zero with empty stdout and `artifacts/read/pypi.err` naming `challenge` on every tier. What is never correct is exit `0` with the challenge shell as `text`.
- **The shell's markers.** The F5/Shape shell carries `/_fs-ch-` in its asset paths and prints "Please enable JavaScript to proceed". A relay strips the scripts, so the copy is the second signal. Measured on 11 real pages (Wikipedia, GitHub, docs.python.org, MDN, Hacker News, arXiv, npm, crates.io, Stack Overflow, BBC, a personal blog): none of them carries either.
- **A puzzle that needs a person is named.** The image CAPTCHA on that site is a puzzle, so the browser rung stops and says so: `stealth-browser: challenge (needs a person: enter the characters seen in the image)`. A puzzle needing a person is never solved by guessing.

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

### Reddit (a known host)

Preconditions:

- `searchts install --browser` has been run. Every one of these drives needs the
  browser tier; Reddit's first window, its "more replies" controls and its feed
  cursor all live behind that rung.
- The run uses the **user's real** `HOME`. The persistent `~/.searchts/browser-profile`
  is what Reddit judges, and a scratch `HOME` (or `SEARCHTS_NO_BROWSER_PROFILE=1`)
  answers "Prove your humanity" on every page. That pairing is itself a drive; see
  the last bullet.

- **Listing and its cursor.** Run `.venv/bin/python -m searchts read https://www.reddit.com/r/MachineLearning/hot/ --items 40 --json > artifacts/reddit/listing-items.json 2> artifacts/reddit/listing-items.err`. Exit code `0`. The object has a `pages` array with more than one entry, the later entries' `url` starting `https://www.reddit.com/svc/shreddit/`, and each entry's `text` holding `- **post title**` rows. One entry is the first window; two or more is Reddit's own cursor being followed. `text` also carries the `[more: after these N cards, Reddit's own cursor for the next batch of this feed is <url>]` note naming the cursor an agent can act on. N is the count of the page just read, never the batch behind the cursor: the drive saved on 2026-10-17 read 3 cards on page one and 24 on the batch its cursor served, so a note claiming the next batch holds N is a number searchts does not have.
- **Payload, not just pages.** Count `- **` across all the entries in `pages`. One window is roughly 3 posts for a Reddit feed, so a walk that ends with the first window's worth of rows read nothing extra no matter how many entries there are.
- **Deeper comments.** Run the same verb on a Reddit thread URL with and without `--expand` and compare. The plain read reports `[partial: Reddit reports N comments; M were in the page]`; the `--expand` read reports the same sentence with a larger M. M is a count of `**/u/name** (N pts)` lines in `text`, and M must grow. A drive saved on 2026-10-17 went 25 → 127 on a 195-comment thread.
- **The ceiling still caps a thread.** Run `SEARCHTS_MAX_ITEMS=12 ... read <thread url> --expand --json`. `text` holds 12 comment lines and the line `[truncated: N more comments in the page were cut at the 12-comment cap]`. Comments are rows; `SEARCHTS_MAX_ITEMS` is the only cap on them, and the note has to name the number it used.
- **Profile and search.** Drive `https://www.reddit.com/user/spez/ --items 80 --json` and `https://www.reddit.com/search/?q=searchts --json`. The profile's `pages` array grows past its first entry and `text` starts `# /u/spez` with a `## Posts (` and a `## Comments (` section; the search's `text` starts `## Results` with one card per hit. A profile or search with no cards must exit non-zero with empty stdout, never the nav bar.
- **Each wall names itself.** Drive `https://www.reddit.com/r/gryffindor/` (private), `https://www.reddit.com/r/Random/` (banned), `https://www.reddit.com/r/incest/` (quarantined), `https://www.reddit.com/r/nsfw/` (no such community) and a comment URL for a post that is not there. Each exits non-zero, stdout is empty, and stderr names a different reason per URL. Two of these hand off to a person with `searchts read <same url> --human`; the private one must not, because there is no public page for a person to accept. The over-18 gate has its own bullet below because it does not fire on demand.
- **One rung, one line.** Drive the quarantined community again with `--human`. stderr carries `human-browser: reddit-quarantined` **once**: a wall the rung can name is not also answered with `human-browser: empty-extract` under it. Two lines for one rung read as two failures, and the second is a lie about the page, which was refused rather than empty. Count the `human-browser:` lines in stderr, not the presence of the wall's name. `read` itself passes `progress=False`, so the ladder's per-rung ticks are not in this drive; the error summary still shows one entry per rung, and that is the assertion to make on the CLI.
- **The over-18 gate is not a wall you can summon.** Drive `https://www.reddit.com/search/?q=gore`. On a warm profile this has answered with 7 result cards and exit `0` twice in a row, and with the gate notice once. Both are real. Record which one you saw; the gate is proven by the saved fixture and the one drive that hit it, and a drive that returns cards is not a failure of searchts.
- **An archived post still reads its comments.** Drive a post whose author deleted it. Exit `0`, `text` carries `**Post:** archived by Reddit. Its text is not available.` and a `[removed: ...]` note, and the comments are there. Removal that leaves nothing public is a failure; removal that leaves a comment tree is content.
- **A post that *quotes* the archived notice is not archived.** Drive `https://www.reddit.com/r/NoStupidQuestions/comments/1x4uke7/` (its OP body quotes "Archived post. New comments cannot be posted" because its author was reading one elsewhere). Exit `0`, `text` carries the OP body and its comments, and it carries **no** `archived by Reddit` line and no `[removed:` note. The archived line is only ever true when Reddit puts `archived` on the post element; Reddit serves threads about all four notices, so a read that keys off the words loses a page that was there.
- **Warm profile vs cold, paired.** Run the listing twice: once as above, once with `SEARCHTS_NO_BROWSER_PROFILE=1`. The warm run exits `0` with posts; the cold run exits non-zero with `reddit-challenge` on every tier and a hint that says the same URL may read on a warm profile. Both artifacts side by side are the proof for the warm-profile caveat in the README. If only the cold answer appears, the profile is not warm and the rest of the Reddit drives prove nothing yet.

### The page's own data

Driven on 2026-10-18 from this box with the JSON-LD and app-state reader (curl +
Jina, no browser installed). Proved: a real Next.js page whose app state holds
words the markup never showed, a real JSON-LD page the markup beat, and the
fail-loud case. Not proved on a live page: a shell whose body is *only* data, so
the replacement path is fixture-proved (`tests/test_f24b_page_data.py`).

- **Data the markup did not show.** Run `.venv/bin/python -m searchts read https://www.veed.io/tools/video-editor --json > artifacts/read/veed.json 2> artifacts/read/veed.err`. Exit code `0`, `backend` is `curl_cffi`, and `text` contains `[source: __NEXT_DATA__, the page's own data; N characters the markup did not show]`. The customer quotes in that section are in `__NEXT_DATA__` and in no `<p>` on the page, which is the proof the read took them from the data. Other notes such as media may follow the source note.
- **A page whose data repeats its markup says nothing.** Run the same verb on `https://react.dev/learn --json`. Exit code `0` and **no** `[source:` line: that page's `__NEXT_DATA__` says what the markup already said, so the read is the extract and the note is absent. A `[source:` line on every Next.js page would mean the reader cannot trust it.
- **JSON-LD consulted, not obeyed.** Run the same verb on `https://www.healthline.com/nutrition/intermittent-fasting-guide --json`. Exit code `0`, no `[source:` line, and `chars` matches `origin/main` for the same page: the page's JSON-LD describes a *related* article and the publisher's about text, so adding it would be noise. The rule is that the data supplies, and only what the markup did not say.
- **A blob of config is not a read.** `__NEXT_DATA__` on a page that ships no text (a shell) still exits non-zero when the blob is a build id, a nav list and a stylesheet. That is the fixture, not a live URL: no public shell page with a config-only blob was found in ninety probes. Do not read a `[source:` line as "this page was thin": it names words, not a rescue.
- **One request.** Every one of these drives is one curl request; the data is read out of the bytes that request returned. There is no second fetch, and the URL count is not observable from the CLI, so it is asserted in `tests/test_f24b_page_data.py::test_the_read_cost_one_request_and_no_other`.

### The ceilings

- **Clamp.** Run `SEARCHTS_MAX_ITEMS=20 .venv/bin/python -m searchts read https://meta.discourse.org/latest --items 90 --json > artifacts/read/clamp.json 2> artifacts/read/clamp.err`. The object carries a `text` containing `[items: asked for 90, the ceiling is 20]`, and the `[scroll:` line says it stopped at the 20 rows asked for. The ceiling stops further walking and scrolling; it does not trim rows page one already held (the saved drive had 30).
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
- A `--items` read that carries `--proxy` or cookies never scrolls: the scroll's own Chromium would carry neither. The text ends `[scroll: not run. ...]`.
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
- A Reddit read on a **fresh** profile is challenged on every page, and that is
  a fact about the profile, not a bug to report. Re-drive with the user's real
  `HOME` before concluding anything about the Reddit path. It also means the
  Reddit numbers in a scorecard are a warm-profile number (**N7** still stands:
  a listing, a thread, a profile and a search reading is not "Reddit works").
- A Reddit wall is worth one look at the *right* tier. `curl_cffi` gets the
  "Prove your humanity" interstitial for pages the browser rung reads fine, so a
  stderr line naming `reddit-challenge` for the first tier is not the page's
  state. The named content wall (`reddit-private`, `reddit-banned`, ...) is the
  one to report.
- A `[source: ...]` line in the notes means the page's own data supplied those
  words. It is not a media line and not a "thin page rescued" line: the read
  still fails loud when the data holds only build config, navigation or a
  stylesheet, and a page whose data repeats its markup carries no such line.
- The app-state reader is keyed on the shape `__SOMETHING__` in a script `id`.
  A bare `window.__STATE__ = {...}` with no `id` attribute (the Remix,
  SvelteKit and YouTube shape) is **not** read, because that shape is also how
  tracking blobs (`dataLayer`, `webpackJsonp`) are written. Do not expect a
  `ytInitialData` page to read from its data yet.
