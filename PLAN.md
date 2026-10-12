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

- [ ] **F5f** Reddit, the rest. **0.15.** Same known-host ring, still fail-open, still **N7**. Next-page cursor on top of **F23c**. Deeper comments on top of **F23d**. Private, NSFW, quarantined, and removed pages each fail with their own note. Profiles and search are cards or a loud failure. Tests use saved pages. The browser stays required.
- [ ] **F23c** Scroll, the part that is not done. Curl already follows a next-batch URL for list rows (`--items`, `max_items`, ceiling `SEARCHTS_MAX_ITEMS`). What is left is a list that only grows by scrolling: probe first, copy rows each step so unmounted rows still count, click a stalled "Load more", stop at N or after two empty steps or on a wall, and say why. No browser: say `searchts install --browser`. **0.15.**
- [ ] **F23d** `--expand` / MCP `expand`. **0.15.** Off on unknown sites. Opt-in opens `<details>` and buttons labelled read, show, or see more. Never links, forms, or sign-in. A news "continue reading" is a paywall: name it, do not work around it. Known hosts keep their own selectors.
- [ ] **F23e** The knobs for that. **0.15.** Flags and MCP take intent only: pages, items, expand. The user sets the ceilings. The agent can ask up to the ceiling and cannot raise it. A clamped request says so. Same names everywhere.
- [ ] **F24** The same fidelity on a site we do not special-case. **0.15 or later.** Signals in the page, not a new host router (**N4**).
  - [ ] **F24a** Images, video, and embeds in the main content, with URLs, or "media present, not resolved."
  - [ ] **F24b** JSON-LD and app state already in the page (`articleBody`, FAQ, discussion, `__NEXT_DATA__`), before the extractor. No second request.
  - [ ] **F24c** One context line: site, section, author, date, from metadata.
  - [ ] **F24d** A space that the extractor drops next to inline code or bold. Never inside code.
- [ ] **F21b** Put a dropped side panel back, once a saved page exists (a hackathon page or a job application, not a screenshot). Keep question text in a form. Never field values or hidden inputs. **F21a**, **F21c**, and **F21d** already shipped.
- [ ] **F22c** A link pasted inside `[...]` or `<...>` is read as the link, or the error says it is not a URL. Today `read "[https://…]"` dies with "scheme '://' is not allowed".
- [ ] Bing result redirects decode only on `bing.com` and its subdomains. A lookalike host stays as written.
- [ ] **F19b** Two installs. `pip install -U` can update one Python while `searchts` on PATH is another, so `--version` stays old. Doctor names every `searchts` on PATH and says which one this process is not.
- [ ] **P3.7d** A walled scorecard row passes only if the text contains a phrase from the real page. 500 characters is not enough. The scorecard says where it was run.
- [ ] **F27** Logged-in `read`. Not built. Same order locally and on a remote browser. Sign-in is the next step when there is nothing to copy, not a replacement for a login that already exists. A user who refuses the copy can still sign in fresh. Do not impersonate `chrome.exe`, and do not decrypt a locked cookie file. A debug port is only on a browser searchts started after a yes, and only for the site in the command. No vendor and no price in this file.
  - **Already kept.** The next `read` of that site uses what was kept. The user's Chrome does not open.
  - **Not kept, and a browser on the machine has the login.** One yes per session covers copying the sites that session actually reads. After that yes, the agent does not ask per URL. It does not get every cookie on the machine, and it does not get a site that session never opens. Firefox, Zen, and LibreWolf are a cookie-file read. Chrome is a second window beside the one already open, because the cookie file is locked and a second launch does not attach to the running window. The scratch folder is deleted when the read finishes, even if the copy failed. Say so when the copy fails. Do not pretend it connected.
  - **Not kept, and there is nothing to copy.** Local: the user signs in once in searchts's own browser. Remote: the user signs in once in the remote window. That sign-in is the approval. Nothing is copied off the PC.
  - **Keep.** After the read works, if the site is not already kept, ask once: keep this site's login for next time? A yes on local writes only that site into searchts's store. A yes on remote leaves it on the remote profile and does not also write a cookie file on the PC. A no keeps nothing, and the next logged-in read starts again.
  - **Kill.** Deletes searchts's copy, if one exists, and the remote profile's copy of that site. It does not touch the cookies in the user's normal browser unless they said to delete those too. The scratch folder is deleted every time, kept or not.
  - **Remote** is the same order. No vendor is chosen. A cloud browser with a saved profile is the shape. A compute-sandbox credit is not that product. `read` still tries the local ladder first. The remote call happens only when the user asked for a logged-in or walled page and an account for that driver exists. If it is ever sold, it is **F18**.

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

## Housekeeping

- [ ] **P1.4** The old box is still open. The text says the 0.10 fail-loud slice shipped and **U1** was answered. Tick it, or write the one thing that is actually left. Do not rebuild it.
