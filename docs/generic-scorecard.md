# Generic read scorecard (F24)

What `searchts read` does on pages it has no special code for. Measured
2026-10-17 from this box with `searchts read <url>` against the real network.
No host in this table is in `searchts/known_hosts` or `searchts/share_extractors`.

## Method

- One fresh process per page: `SEARCHTS_NO_MEMORY=1 searchts read <url>`.
  The ceiling knobs were left at their defaults.
- "raw DOM text" is the visible text of the same URL fetched with
  `curl_cffi` impersonating Chrome, with `script/style/noscript/template/svg`
  removed and whitespace collapsed. It is a size reference, not the answer:
  it includes navigation and footers the extractor is meant to drop.
- "Kept" is the character count the CLI returned.
- A page is **silent** when the read exits `0` with no `[more:]`/`[folded:]`/
  `[left out:]`/`[thin:]`-style note even though the live page has content the
  read did not return. It is **loud** when the CLI exits non-zero with a named
  reason.
- The stealth browser is not installed on this box
  (`searchts install --browser`), so the browser rung was never in play. Every
  row below therefore measures curl + Jina only.

## Scorecard

| # | Kind | URL | Kept | Raw DOM | Backend | Result | What a reader sees that the read lacks |
|---|---|---|---|---|---|---|---|
| 1 | news article | https://www.bbc.com/news/articles/cxr5yvzv7rp0o | 7,098 | 10,571 | curl_cffi | loud about two side panels (`[left out: …]`) | Two "most read" side panels, named in the notes and not added back. Images and captions are not listed. |
| 2 | news article | https://apnews.com/article/oregon-school-shooting-silver-rail-elementary-989180ae6e9aa2ed6a4239c8e3423085 | 6,626 | 48,583 | curl_cffi | loud about folds (`[folded: 7 controls like "Read More"]`) | 25 images, one video and one iframe are not listed. The DOM gap is mostly nav, live-update cards and related-story chrome. |
| 3 | personal blog | https://danluu.com/ | 17,570 | 9,150 | curl_cffi | clean | None found; the extract is longer than the DOM text because link targets count. |
| 4 | personal blog | https://simonwillison.net/2024/Dec/31/llms-in-2024/ | 47,242 | 42,448 | curl_cffi | clean | None found. |
| 5 | docs page | https://docs.python.org/3/library/json.html | 33,496 | 27,105 | curl_cffi | clean | None found; the signature tables and inline code survive. |
| 6 | forum thread | https://meta.discourse.org/t/about-the-news-and-events-category/396990 | 621 | 703 | curl_cffi | clean | None found; this topic really is one short post. |
| 7 | Q&A | https://stackoverflow.com/questions/11227809/why-is-processing-a-sorted-array-faster-than-processing-an-unsorted-array | 0 | 16 | none | loud (`curl_cffi: http-403`, `Jina Reader: 403`, browser skipped) | The answer page is refused by the address, not by the parser. The reason is specific. |
| 8 | product page | https://www.ikea.com/us/en/p/markus-office-chair-vissle-dark-gray-90289172/ | 18,289 | 17,797 | curl_cffi | loud about one fold (`[folded: 1 control like "Show more"]`) | 53 images and 3 videos are not listed; a "Show more" product-information panel is named but not opened. |
| 9 | wiki article | https://en.wikipedia.org/wiki/Web_scraping | 43,869 | 31,030 | curl_cffi | clean | None found. |
| 10 | GitHub-like README | https://github.com/psf/requests | 0 | 6,009 | none | **loud, but the reason is wrong** (`login-wall` on every rung) | Public README is not returned. The extract is GitHub's navigation chrome, which repeats "Sign in"; the generic auth-wall classifier reads that as a login page. This is a false wall, not a private page. |
| 11 | paginated listing | https://news.ycombinator.com/news?p=2 | 6,067 | 3,933 | curl_cffi | loud about the list and next page (`[list: 30 items rebuilt]`, `[more: next page is …p=3]`) | None: the 30 rows and the next-page URL are both present. |
| 12 | FAQ / accordions | https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/details | 10,998 | 13,194 | curl_cffi | loud about a side panel (`[left out: … "In this article"]`) | The 11 `<details>` and their closed answers are in the extract (the extractor already reads them); the right-hand contents panel is named and not added. |
| 13 | comment-heavy thread | https://news.ycombinator.com/item?id=50126253 | 2,046 | 1,049 | curl_cffi | clean | None found; this item has a short discussion. |
| 14 | embedded video | https://www.youtube.com/watch?v=dQw4w9WgXcQ | 0 | 225 | none | loud (`curl_cffi: thin-146b`, `Jina Reader: 403`, browser missing) | The watch page is a JS app: 1.4 MB of HTML, 225 characters of DOM text, no `<video>` URL in the served markup. The read refuses rather than passing 146 characters of shell. |
| 15 | JS SPA | https://svelte.dev/ | 1,033 | 2,188 | curl_cffi | clean | None found; SvelteKit server-renders this page and the read ends at the footer. |
| 16 | JSON-LD | https://www.allrecipes.com/recipe/223042/chicken-parmesan/ | 7,844 | 15,121 | curl_cffi | clean | The prose, `## Ingredients` and `## Directions` are all present. 90 images are not listed; the JSON-LD `Recipe` object is not consulted. The DOM gap is ads, nutrition chrome and related recipes. |
| 17 | `__NEXT_DATA__` | https://www.notion.so/ | 2,855 | 2,710 | curl_cffi | clean | None found; the marketing page is server-rendered. `__NEXT_DATA__` is present but the extract is already the whole visible page. |
| 18 | long article / "read more" | https://www.wired.com/story/kernel-panic-encryption-is-getting-squeezed-from-all-sides/ | 8,346 | 8,972 | curl_cffi | clean | None found; the article body is complete. The page's "read more" text is related-story chrome. |
| 19 | RSS/Atom feed | https://hnrss.org/frontpage | 8,648 | 8,401 | curl_cffi | clean | None found. |
| 20 | news front page | https://www.theguardian.com/international | 3,198 | 19,785 | curl_cffi | loud about a rebuilt list (`[list: 8 items rebuilt from the page]`) | 19,736 characters of visible text against 3,198 kept. The list note names 8 rebuilt items but not the size of the gap: most of the front page's headlines are gone. This is the clearest "content far smaller than the DOM text" case in the set. |

## What this set says

- **17 of 20 reads returned content** (rows 1, 2, 3, 4, 5, 6, 8, 9, 11, 12,
  13, 15, 16, 17, 18, 19, 20; rows 7, 10 and 14 refused).
- **Three refused for a real wall or a real shell** (7, 14) or for a false wall
  the classifier can name but not read through (10).
- **No row silently passed a thin page** in the sense of an empty or
  mid-sentence read. The silent failures in this set are *partial*, not empty:
  row 20 keeps 16% of the page's visible text and says only that 8 items were
  rebuilt, and row 2 keeps 14% while naming the "Read More" folds but not the
  size of the gap.
- The generic path is good at prose and docs, and weak at three things the
  page can signal without a host name:
  1. a control that holds text behind `aria-expanded`/hidden siblings but whose
     label is not exactly "Read more" or "Load more";
  2. an extract that is a small share of the main region's visible text, with
     no note saying so;
  3. media: images, video and embeds are dropped; F24a is the fix.
- These are the signals F24 adds. They are structural, so they apply to hosts
  this file has never seen.

## Not run

- The stealth-browser rung: `patchright` is not installed here. Every JS-wall
  row (14) and the browser-only half of `--expand` were not measured.
- The over-18 / private states and any host-specific failure: out of scope for
  this scorecard, which only covers pages with no host code.

## Re-measured at the branch tip (2026-10-18)

Same 20 URLs, same method (`SEARCHTS_NO_MEMORY=1 searchts read <url>`, curl +
Jina only, no browser installed), run from the branch tip with every F24 commit.
"Chars" is the length of what the CLI printed on stdout, notes included. Live
pages change between runs, so a row's size can move for reasons that are not the
code (rows 11 and 13 changed most).

| # | Host / path | Chars | Exit | What the read said |
|---|---|---|---|---|
| 1 | www.bbc.com/news/articles/cxr5yvzv7rp0o | 7,504 | 0 | context line, media, two `[left out:]` panels |
| 2 | apnews.com/article/oregon-school-shooting-… | 7,381 | 0 | context line, `[folded: 7 …]`, `[kept 5,869 of 27,006 … (22%)]`, media |
| 3 | danluu.com/ | 17,571 | 0 | no notes |
| 4 | simonwillison.net/2024/Dec/31/llms-in-2024/ | 47,632 | 0 | context line, media |
| 5 | docs.python.org/3/library/json.html | 33,497 | 0 | no notes |
| 6 | meta.discourse.org/t/about-the-news-and-events-category/396990 | 677 | 0 | context line |
| 7 | stackoverflow.com/questions/11227809/… | 0 | 1 | refused: `curl_cffi: http-403`, `Jina Reader: 403` |
| 8 | www.ikea.com/us/en/p/markus-office-chair-… | 18,736 | 0 | `[folded: 5 controls like "Show more"]`, media |
| 9 | en.wikipedia.org/wiki/Web_scraping | 44,530 | 0 | context line, media |
| 10 | github.com/psf/requests | 0 | 1 | refused: `login-wall` on curl and Jina; the hint now says the browser tier is sent no cookies. Still a **false wall** (see gaps). |
| 11 | news.ycombinator.com/news?p=2 | 3,952 | 0 | `[more: next page …]`, media. No `[list:]` note this run, and the text is one token per line (same on `origin/main`: 3,877 chars). |
| 12 | developer.mozilla.org/…/Elements/details | 11,165 | 0 | `[folded: 1 …]`, `[media: 4 embeds …; media present, not resolved]`, `[left out: "In this article"]` |
| 13 | news.ycombinator.com/item?id=50126253 | 10,287 | 0 | `[list: 35 items rebuilt …]`, media (the thread grew since the first run) |
| 14 | www.youtube.com/watch?v=dQw4w9WgXcQ | 0 | 1 | refused: `curl_cffi: thin-146b`; hint: "this page is a JS app … that tier is sent no cookies" |
| 15 | svelte.dev/ | 1,392 | 0 | media (18 images, 1 video) |
| 16 | www.allrecipes.com/recipe/223042/chicken-parmesan/ | 0 | 1 | refused: `curl_cffi: http-403`, `Jina Reader: 451`. The first run fetched this page; **NOT RE-MEASURED** for its JSON-LD. |
| 17 | www.notion.so/ | 3,382 | 0 | media (53 images, 1 video) |
| 18 | www.wired.com/story/kernel-panic-… | 8,635 | 0 | context line, media |
| 19 | hnrss.org/frontpage | 8,456 | 0 | no notes |
| 20 | www.theguardian.com/international | 4,496 | 0 | `[list: 9 items …]`, `[kept 2,607 of 16,600 … (16%); … the last line also stops mid-sentence]`, media (105 images, 4 videos) |

What changed against the first table: rows 2 and 20, the two "kept a small
share, said nothing about the size" cases, now say the share and both numbers;
row 20 also says the last line stops mid-sentence. Every read that has media in
its main content lists it, with at most four URLs, or says "media present, not
resolved". Row 14 gets the JS-app hint and row 10 the no-cookies hint.

### JSON-LD (F24b) on real pages

`more.structured_text` and the extractor, run on the same downloaded bytes
(visible characters, 2026-10-18; `curl_cffi` impersonating Chrome):

| Page | Has JSON-LD | Structured body | Extract | Used |
|---|---|---|---|---|
| www.bonappetit.com/recipe/bas-best-chocolate-chip-cookies | yes | 2,811 | 5,198 | extract |
| www.healthline.com/nutrition/intermittent-fasting-guide | yes | 1,436 | 11,613 | extract |
| www.theverge.com | yes | 0 | 20,751 | extract |
| www.nngroup.com/articles/usability-101-… | yes | 0 | 7,047 | extract |

On all four the page's own markup already beat the data, so the read is
unchanged, which is the intended rule (the data is used only when it beats the
extract by 10%). **No real page was found where the data wins**; that path is
proved by hand-written fixtures only (`tests/test_f24_generic.py`). Four other
candidate recipe/Q&A pages returned 403 and were not measured.

## Open gaps

- Row 10: a public README read as `login-wall`, because the page's chrome repeats
  "Sign in". The loud failure is right in kind and wrong in reason.
- Row 11: a list page the extractor flattens to one token per line, with no note
  that the list was not rebuilt. Same on `origin/main`.
- F24b `__NEXT_DATA__` is not read (no real page found where it beats the
  extract). F24b's JSON-LD path is proved on fixtures only.
- The browser rung was never run here, so no JS-app page was read, only named.
