# searchts plan

This file is the work that is not done. A checked box, a PR number, and a post do not belong here.

Shipped checklist: [`docs/plan-shipped.md`](docs/plan-shipped.md). What landed on which day: [`docs/freeze-log.md`](docs/freeze-log.md). Posts: [`docs/comms.md`](docs/comms.md). Hare: [`docs/hare-next.md`](docs/hare-next.md). How to change the repo: [`AGENTS.md`](AGENTS.md).

searchts reads a page for an agent and says when it did not. The install on the user's machine stays something they can run without an account. A hosted fetch, the URL a remote connector points at, is **F18**. It is not a tunnel shipped inside pip.

## Still binding

| # | Choice |
|---|---|
| Q1 | Channels are doctor probes. They do not route reads. |
| Q2 | Install writes a short memory rule. Ask before overwrite. |
| Q3 | The public scorecard shows real pass rates, including the walls it missed. |
| Q4 | Jina stays on unless the user turns it off. The relay sees the URL. |
| Q5 | Env beats YAML. Doctor does not install anything. |

Do not build:

- **N1** A paid residential proxy as the default of `pip install`. An exit we operate is **F18**. This line is not "never finish a device-check" and not "never use a VPN the user already has."
- **N2** A public URL for the free CLI. The hosted read is **F18**.
- **N3** A keyed commercial unlocker as a default backend.
- **N4** A plugin system. A known host is one fail-open file, same shape as the share extractors.
- **N5** Sending GitHub or Twitter through some other CLI inside `read`.
- **N6** MCP resources and prompts before the tools are trusted.
- **N7** A release that says Reddit or LinkedIn now read.

## The reader

What a read still does not do.

- [ ] **F5f** Reddit, the rest. **Next.** Same known-host ring, still fail-open, still **N7**. Next-page cursor on top of **F23c**. Deeper comments on top of **F23d**. Private, NSFW, quarantined, and removed pages each fail with their own note. Profiles and search are cards or a loud failure. Tests use saved pages. The browser stays required. **Next:** built and driven live on this box, every read on a warm browser profile: Reddit's own cursor (`faceplate-partial[slot=load-after]` → `/svc/shreddit/community-more-posts/…`) followed to 52 posts in 3 pages (`r/MachineLearning/hot --items 40`) and a profile feed to 101 cards in 4 (`/user/spez --items 80`); a 195-comment thread from 25 comments to 127 with `--expand`; and one wall per state failing loud on empty stdout with its own reason (private, banned, quarantined, community gone, post gone, archived post, humanity check). Every row cap on those paths now reads `SEARCHTS_MAX_ITEMS`, plain or expanded, so `--items 250` no longer comes back with 30 rows. **Not driven, and not claimed:** the over-18 search gate (two later drives of that URL on a warm profile both came back with 7 result cards and the gate never fired, so the state rests on the saved fixture and one earlier run, not on a repeatable live wall); a cold-profile read (the one cold-profile drive ended in `reddit-challenge` on every tier, so a fresh profile is measured as refused and nothing else); the cursor hop's one browser retry after Reddit judges the request (proven by unit tests and a faked rung, never on a cold live page); the `.json` ring's row caps (both `.json` endpoints answer 403 from this address, so those are proven by fixtures and unit tests only); and no page saying "removed by the subreddit moderators" was obtained from this box, so removal rests on the two shapes Reddit really served (the forbidden page for a post with nothing public left, the archived post whose text is gone and whose comments still read). **N7** stays open: a listing, a thread, a profile and a search read, and that is not "Reddit works".
- [ ] **F23c** Scroll, the part that is not done. Curl already follows a next-batch URL for list rows (`--items`, `max_items`, ceiling `SEARCHTS_MAX_ITEMS`). What is left is a list that only grows by scrolling: probe first, copy rows each step so unmounted rows still count, click a stalled "Load more", stop at N or after two empty steps or on a wall, and say why. No browser: say `searchts install --browser`. **Next:** the loop and its row copy are built and driven live on two Discourse feeds, ending on the "reached the rows asked for" stop (`meta.discourse.org/latest --items 70`: 90 rows in 2 steps; `discuss.python.org/latest --items 60`: 60 rows in 1 step). Left, and resting on fakes and saved shapes rather than a live page: a stalled "Load more" press, a virtualized feed that unmounts its rows as you scroll (the store that keeps them is proven only by a fake page; reddit.com challenges every rung from this box, so it cannot be reached to measure), and the other stop reasons (empty steps, the clock, a wall, a page that navigates away). No Reddit read is claimed here: **N7** stays open. `item_count` also counts markdown list lines only, so a table-shaped feed reads as zero rows to `--items` and always looks short.
- [ ] **F23d** `--expand` / MCP `expand`. **Next.** Off on unknown sites. Opt-in opens `<details>` and buttons labelled read, show, or see more. Never links, forms, or sign-in. A news "continue reading" is a paywall: name it, do not work around it. Known hosts keep their own selectors. **Next:** built and driven live: ten closed `<details>` opened on the MDN `<details>` reference, and a Washington Post opinion page behind its paywall **named and not opened** (3,687 bytes with `--expand` against 3,563 without, the difference being the note and nothing else). Left: a button press is only seen when the control has hydrated by the time the pass runs (`kickstarter.com/discover/advanced` was seen once pressing two "Show more" buttons during development, but that run's output was not kept, and every saved drive found none; from this box its browser rung now meets a Cloudflare Turnstile, so a button press has no stored live proof at all, only the unit tests and a local page driven in a real Chromium), and an opened `<details>` does not always add text to the extract, because the extractor already reads MDN's folded tables closed.
- [ ] **F23e** The knobs for that. **Next.** Flags and MCP take intent only: pages, items, expand. The user sets the ceilings. The agent can ask up to the ceiling and cannot raise it. A clamped request says so. Same names everywhere. **Next:** built, and the clamp note is driven live (`SEARCHTS_MAX_ITEMS=20` with `--items 90` ends `[items: asked for 90, the ceiling is 20]` on page one; the ceiling stops the walk and the scroll asking for more, it does not trim a page that already held 30 rows). Left: no live drive of `SEARCHTS_MAX_EXPAND_CLICKS` actually capping presses on a page with more eligible controls than the ceiling, and no drive of the same note arriving through the MCP envelope rather than the CLI.
- [ ] **F24** The same fidelity on a site we do not special-case. **0.15 or later.** Signals in the page, not a new host router (**N4**).
  - [ ] **F24a** Images, video, and embeds in the main content, with URLs, or "media present, not resolved."
  - [ ] **F24b** JSON-LD and app state already in the page (`articleBody`, FAQ, discussion, `__NEXT_DATA__`), before the extractor. No second request.
  - [ ] **F24c** One context line: site, section, author, date, from metadata.
  - [ ] **F24d** A space that the extractor drops next to inline code or bold. Never inside code.
- [ ] **F21b** Put a dropped side panel back, once a saved page exists (a hackathon page or a job application, not a screenshot). Keep question text in a form. Never field values or hidden inputs. **F21a**, **F21c**, and **F21d** already shipped.
- [ ] **F19b** Two installs. `pip install -U` can update one Python while `searchts` on PATH is another, so `--version` stays old. Doctor names every `searchts` on PATH and says which one this process is not.
- [ ] **P3.7d** Three walled rows (`linkedin-feed`, `g2-cloudflare`, `datadome-co`) have no phrase from the real page, because no read has reached it, so they cannot pass. Add each phrase from a real read, then rerun to refresh `docs/scorecard.md`, which still has no where-it-ran line.
- [ ] **F27** Logged-in `read`, the remote half. The local half shipped in 0.15.0 ([`docs/freeze-log.md`](docs/freeze-log.md)). What is left is the same order on a remote browser. Sign-in is the next step when there is nothing to copy, not a replacement for a login that already exists. Do not impersonate `chrome.exe`, and do not decrypt a locked cookie file. A debug port is only on a browser searchts started after a yes, and only for the site in the command. No vendor and no price in this file.
  - **Sign-in.** The user signs in once in the remote window. That sign-in is the approval. Nothing is copied off the PC.
  - **Keep.** After the read works, if the site is not already kept, ask once: keep this site's login for next time? A yes leaves it on the remote profile and does not also write a cookie file on the PC. A no keeps nothing, and the next logged-in read starts again.
  - **Kill.** Deletes the remote profile's copy of that site, and searchts's local copy if one exists. It does not touch the cookies in the user's normal browser unless they said to delete those too.
  - **Driver.** No vendor is chosen. A cloud browser with a saved profile is the shape. A compute-sandbox credit is not that product. `read` still tries the local ladder first. The remote call happens only when the user asked for a logged-in or walled page and an account for that driver exists. If it is ever sold, it is **F18**.

## When something forces it

Not scheduled. The line is the trigger. No trigger, no build.

- [ ] **P3.8** / **U2** Compare the old Chrome 126 UA with the current one on a fixed set. Keep the extra only if the difference is real. Skip if **P3.4** is enough.
- [ ] **P3.9** / **U3** Count domain-memory hits that then fail. After a month of real reads, or never if the TTL is cheap enough.
- [ ] **U4** Jina becomes opt-in only if a privacy or rate-limit case shows up.
- [ ] **U5** Widen the SSRF guard past MCP only if the server is no longer local-only.
- [ ] **U6** After a thin read, check whether the model actually retries. Measure, then decide.
- [ ] **U7** Let install and directory numbers pick the P4 order. Not a feeling.
- [ ] **P4.2** Claude plugin (`plugin.json` + skill + MCP). When marketplace traffic says so (**U7**).
- [ ] **P4.3** A CI job with the browser extra. When stealth tests flake because Chromium is missing.
- [ ] **P4.4** A `browser` Docker tag beside `slim`. When someone runs the image.
- [ ] **P4.5** Split `cli.py` one verb at a time, and only while editing that verb.
- [ ] **F2** Read a PDF URL. When a real PDF URL is the support pain.
- [ ] **F3** A cache for a URL fetched in a loop. When that loop hurts.
- [ ] **F4** A bounded sitemap crawl. On demand. Not a crawler product.
- [ ] **F5** Write down the share-extractor file as the way to add a host. When the next share host is added. Not a plugin system (**N4**).
- [ ] **F6** Plugin polish past **P4.2**. With **P4.2**.
- [ ] **F10** WebMCP, site-exposed tools. After the local reader is the thing people reach for. It does not replace it.
- [ ] **F20** `--html`: a cleaned file, scripts and hidden nodes stripped, size capped. When someone asks, or when Markdown is the wrong handoff. Default `read` stays Markdown.
- [ ] **F14** Solari only when local patchright is missing, and only with `SOLARI_API_KEY`. Never the default (**N3**). Revisit if that is something a person would pay for, not because a wall turned green.

## Hosted

- [ ] **F18** The paid product is a hosted `read`: a URL we run and a key. That is what a Cloudflare or Hermes-style connector points at. The local CLI does not grow an account to keep working. Bought proxy pools stay **N1**. Price is not set in this file.

Not this product:

- [ ] **F15** Hare, for other repos. [`docs/hare-next.md`](docs/hare-next.md).
- [ ] **F16** A disposable remote workspace. After **F15** is a real question, not a side path on this one.
