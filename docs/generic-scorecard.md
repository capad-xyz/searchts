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
