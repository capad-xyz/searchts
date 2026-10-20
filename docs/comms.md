# Posts

What we say in public. Not the product plan.

Open work: [`PLAN.md`](../PLAN.md). What shipped: [`plan-shipped.md`](plan-shipped.md). The day-by-day log: [`freeze-log.md`](freeze-log.md).

### Communications

- [x] **X1** After P0.7: smoke vs walled; thin is not a pass (posted 2026-08-20)
- [x] **X2** After P1 demo: 403 → agent calls `read_url` (issue #22). *Posted 2026-08-27 (`@aadarsh_io`).*
- [x] **X3** After P3.1+P3.2: one wall before/after. *Posted (`@aadarsh_io`). Honesty framing — do not claim permanent bypass.*
- [x] **X4** After P2.3: mcp 2.x no longer kills `mcp serve`. *Posted 2026-08-26 (`@aadarsh_io`). Host stdio smoke done.*
- [x] **X5** 0.8.0 on PyPI. *Posted 2026-08-30 (`@aadarsh_io`). Used `example.com` in the uvx line — that URL is thin (`_MIN_CHARS`); a copypaste looks like a broken install. Do not unpost. Next demo URL = Wikipedia. F8b/F13 later.*
- [x] **X6** 0.9.0 on PyPI. *Posted 2026-09-21 (`@aadarsh_io`). Wikipedia demo URL. HTTP MCP + transcribe.*
- [x] **X7** 0.12.0 Reddit listing cards + 0.11 MCP catch-up. *Posted 2026-09-30 (`@aadarsh_io`). Video: listing → Markdown cards. Honesty: listing parser, not "Reddit complete".*
- [x] **LI1** First LinkedIn post for searchts (same 0.12 story). *Posted 2026-09-30.* First LI beat; keep share-link / fail-loud as the long-form homepage pitch later.
- [ ] **LI2** (2026-10-03: version-free story, not "Latest 0.13"; Reddit hook, Bing inside; a motion video built only on real output and real numbers, captions burned in, 4:5, 20 to 25 s; links in the first comment; a weekday.) Earlier text: After 0.13 is on PyPI: fill "Latest" (0.13) and "Next up" (**F23**: pages that scroll, paginate or fold, on any site). 4:5 clip from real 0.13 output. Links and install in the first comment.
- [ ] **X8** Thread, version-free (drafted 2026-10-03). 1/ Reddit hook (blocked links; some agents fake a summary) with a real r/LocalLLaMA listing clip, browser step shown, waits sped up and labeled. 2/ Bing before/after screenshots: `trafilatura -u` vs `searchts read`, 0 of 10 titles vs 10 of 10 with real links. 3/ also new (has-more notes, Reddit fields, `install --browser`). 4/ MCP safety, 12/12 open, walled failures named. 5/ anthropics/claude-code#45070 as proof, install and repo. Say "free, no API key", not "runs on your machine": the Jina relay is a hosted tier.
- [ ] Cadence ≤2 *story* posts/week; no chore tweets (pins, dead keys, YAML). Quiet patch tags do not need a post. One user-facing release story every 1–2 weeks beats six internal tags in ten days.
- [x] **X1** posted 2026-08-20 (`@aadarsh_io`). Article live: https://x.com/i/article/2090756751675342848 (also linked 2026-09-06).
- [x] **CI** PRs: lint + typecheck + version-sync + ubuntu 3.12 tests. Full matrix + wheel-gate on `main` only.

- [x] Article: [X Article](https://x.com/i/article/2090756751675342848). PLAN had lagged (“drafted”). Demo URL = Wikipedia.
- [x] **PyPI 0.8.0** [#78](https://github.com/capad-xyz/searchts/pull/78) merged 2026-08-29; [pypi.org/project/searchts/0.8.0](https://pypi.org/project/searchts/0.8.0/).

- [x] **Install story** (docs, not a feature): **keep** = `pipx install "searchts[mcp]"`; **try / MCP** = `uvx --from "searchts[mcp]" searchts …`. `pip` is for venvs only.

---

## 5. Comms rules

| Beat | Trigger | Content |
|---|---|---|
| X1 | P0.7 merged | Scorecard was smoke; thin ≠ pass; smoke vs walled |
| X2 | P1 acceptance green | Demo: wall → `read_url` without being told (#22) |
| X3 | P3.1 + P3.2 | One before/after on a real wall; name the signal, not "we beat Vendor forever" |
| X4 | P2.3 + host smoke | One line: mcp 2.x no longer kills the server |

Article after P0 (better with one P1/P3 win). Draft free; publish when the repo matches the story.

**Reach rules (2026-10-03).** Posts were under 50 impressions on X and LinkedIn. Stories, not versions: one or two posts a week, each true for several releases; release notes stay in the changelog. Hook = a problem in one line, then real proof (a clip or a before/after), then the difference, then the install line; links in the first reply or comment. Real output only: styled screenshots of real runs are fine, generated terminal footage is not. Fifteen minutes a day of real replies on bigger accounts' posts about agents and MCP (a reply on a 1.1M account already got a DM). Post from `@aadarsh_io`; reserve a searchts handle, switch when there is an audience. Show HN when **F25** ships (0.13.1), on a weekday morning US time; P3.7c is done (#227).

Organic X / LinkedIn: draft here; publish from `@aadarsh_io` (and LI). **Distribution order (2026-09-30):** product is ahead of reach (few stars vs many releases). Next gains = first-run + proof + focus, not feature count. Loud campaigns lead with **fail-loud honesty** and **AI-chat share links** (proven, keyless). Reddit listing/parser is **proof of progress**, not the permanent homepage hook, and never "Reddit unlocked" (**N7**). **Show HN**: the gate is in the Reach rules above (2026-10-03). **F15** and **F16** are not searchts posts. **F18** is the hosted read in [`PLAN.md`](../PLAN.md); do not announce it until there is a price.

---

## 6. Launch kit (draft, 2026-10-20)

Ready-to-post copy for Show HN, X, Reddit and a 60-second Reel. Every claim here is true of the current tree (0.15.0). The Show HN gates in section 5 are clear: **F25** shipped in 0.13.1 and **P3.7c** is #227. Post on a weekday morning US time from `@aadarsh_io`.

### 6.1 Show HN

**Title options:**

1. `Show HN: searchts – a keyless web reader for agents that fails loudly on walls`
2. `Show HN: searchts ("search this shit") – a keyless web reader for MCP agents`
3. `Show HN: searchts – escalating web reader for coding agents (curl_cffi, Jina, patchright)`

**URL:** https://github.com/capad-xyz/searchts

**First comment by the author:**

Hi HN, I'm Aadarsh. I built searchts (off the record: "search this shit") because Claude kept failing at two opposite extremes whenever I asked it to read a URL.

The trigger was a Devpost hackathon page and its terms. The page wasn't even behind a hard paywall, and Claude's built-in fetch still couldn't read it. When I wired up a quick fallback scraper, it failed the other way: when a site served a 200 OK loading spinner, a login gate, or a Cloudflare interstitial, the tool handed that HTML back to the model, and the agent confidently summarized the loading screen as if it were the article.

searchts is built around one rule: return the real page, or fail loudly and say which tier stopped and why.

**What it does under the hood**

1. **An escalating keyless unlocker.** Tier 1 is `curl_cffi`, impersonating a real Chrome TLS/JA3 and HTTP/2 fingerprint locally. Tier 2 is Jina Reader (`r.jina.ai`) for pages that only fill in after JavaScript; it is on by default and `SEARCHTS_NO_JINA=1` keeps the URL local. Tier 3 is `patchright`, an undetected headless Chromium started lazily only when the cheaper tiers fail. `--human` opens a real browser when the page genuinely needs a person. Per-domain memory remembers which rung worked.

2. **Native AI-chat share-link decoders (8 providers).** Generic fetches get an empty shell, and renderers can cut a long chat off mid-thread. `searchts read` decodes the provider's own channel: ChatGPT turbo-stream (both `/share/<uuid>` and the newer `/s/` short links), Claude's keyless snapshot API, Gemini's batchexecute RPC, Grok's share-links API and Poe's `__NEXT_DATA__`, all without a browser. DeepSeek, Perplexity and Copilot use a stealth render that scrolls past list virtualization.

3. **A two-suite benchmark that reports the walls it misses.** Open-web Smoke and real bot-walled targets are reported separately. The last committed run is 12/12 on Smoke and 2/7 on Walled. The five walled failures are named in `docs/scorecard.md`; a wall is not counted as a pass just because its HTML is long enough.

4. **A CLI, an MCP server and a Python library.** Nine MCP tools, and `read_url` is the one. `web_search` finds URLs to read; a snippet is not the page. A player page's captions come back from `read_url`, and `transcribe` is the audio when that read finds none. `fetch_asset` fetches one file a read named. Search is keyless DuckDuckGo by default, with reciprocal rank fusion across optional SearXNG, Exa, Brave or Tavily. `--scrub` strips invisible/bidi characters and flags prompt injection.

A login you hand over is opt-in and host-fenced in 0.15.0: `--cookies-from-browser <browser> --yes`, `--cookies <path>`, or `--cdp-port <port>`. Reusing a login on a remote browser is not built yet (F27). Nothing is guessed silently.

Try it in one line with Claude Code or Cursor:

```bash
claude mcp add searchts -- uvx --from "searchts[mcp]" searchts mcp serve
```

MIT, Python 3.10+, v0.15.0 on PyPI. It started as an extension of Agent-Reach's channel and doctor scaffolding; the unlocker, share-link extractors, benchmark harness and MCP surface are the additions. I would love feedback on targets that break the unlocker, and on false positives in wall detection.

### 6.2 X thread (6 posts)

**1/ Hook**

Every week a repo goes viral claiming it "gives your AI agent eyes to see the entire internet for $0."

Then you run it:

- it is mostly an installer for third-party CLIs
- it summarizes a 200 OK login wall as an article
- a plain fetch returns an empty shell on ChatGPT or Claude share links

So I built searchts ("search this shit"), a keyless web reader and MCP server for agents. 🧵

https://github.com/capad-xyz/searchts

**2/ The rule**

Most agent fetchers fail in the same direction: a Cloudflare challenge, a JS shell, or a LinkedIn login wall served as HTTP 200 gets handed to the model, and the model summarizes the loading screen.

searchts has one rule: return the real page, or fail loudly and say which tier stopped and why. Empty stdout, non-zero exit, named reason.

**3/ The ladder**

Instead of calling `curl` once, `searchts read <url>` walks an open-source ladder and remembers which rung worked per domain:

1. `curl_cffi`: Chrome TLS/JA3 and HTTP/2 fingerprint
2. Jina Reader: JS render relay (`SEARCHTS_NO_JINA=1` keeps it local)
3. `patchright`: lazy stealth Chromium
4. `--human`: real-browser handoff for a CAPTCHA or a login only a person can clear

**4/ The share links**

Feed your agent a `chatgpt.com/share/...`, `claude.ai/share/...` or `gemini.google.com/share/...` link and a plain fetch returns an empty JS shell, while a renderer can truncate a long chat.

`searchts read` decodes the native payload for 8 providers: ChatGPT, Claude, Gemini, Grok and Poe without a browser; DeepSeek, Perplexity and Copilot with an auto-scrolling stealth render.

**5/ The rest of the CLI**

- `searchts transcribe <url>`: subtitles first, then `yt-dlp` + Whisper for YouTube, Instagram Reels, TikTok and Reddit (`--cookies-from-browser chrome` is opt-in)
- `searchts grab <url>`: fingerprint-gated images, SVGs, fonts and color palettes
- `--scrub`: strips invisible/bidi prompt-injection characters
- Honest two-suite scorecard: Smoke 12/12, Walled 2/7 at the last committed run

**6/ CTA**

MIT, free, keyless by default, no paid residential proxy. Nine MCP tools, one install line:

`claude mcp add searchts -- uvx --from "searchts[mcp]" searchts mcp serve`

Repo and scorecard: https://github.com/capad-xyz/searchts

### 6.3 Reddit

**r/ClaudeAI**

Title: I got tired of Claude Code failing on 403 walls and AI share links, so I built searchts ("search this shit"), a keyless escalating web reader + MCP server

Body:

If you use Claude Code daily, you have probably hit two annoying web-fetching bugs:

1. You paste a doc URL or a shared ChatGPT/Claude/Gemini conversation link, and the built-in fetch comes back with a 403 or an empty JavaScript shell.
2. You try a naive scraper, it hits a soft login wall or a loading screen served as HTTP 200, and Claude summarizes the login page as if it read the article.

I started by looking at viral tools like Agent-Reach. Most of what they do is install and route upstream CLIs (`OpenCLI`, `yt-dlp`, Jina) rather than read the page themselves. So I built searchts (MIT, Python, v0.15.0 on PyPI).

What makes it different:

- Escalating unlocker: every read tries `curl_cffi` (Chrome TLS/JA3) → Jina Reader (opt out with `SEARCHTS_NO_JINA=1`) → `patchright` stealth Chromium → `--human` handoff.
- Fails loudly: phrase-based wall detection plus a minimum-content threshold. If the page is a login gate or a puzzle, you get a non-zero exit and the tier that stopped, not half-HTML.
- Reads full AI share links (8 providers): native decoders for ChatGPT, Claude, Gemini, Grok and Poe; auto-scrolling stealth renders for DeepSeek, Perplexity and Copilot.
- Logged-in reads are opt-in and host-fenced: `--cookies-from-browser`, `--cookies`, or `--cdp-port`. Nothing is reused silently, and remote sign-in is not built yet.
- `transcribe` is subtitles-first, then `yt-dlp` + Whisper, with `--cookies-from-browser chrome` for login-gated Reels.
- Honest scorecard: Smoke and Walled are reported separately. The last committed run is 12/12 and 2/7; the failures are named in `docs/scorecard.md`.

One-command setup for Claude Code:

```bash
claude mcp add searchts -- uvx --from "searchts[mcp]" searchts mcp serve
```

Or install the `/searchts` slash command after `pipx install "searchts[mcp]"`:

```bash
searchts skill install
```

Repo: https://github.com/capad-xyz/searchts. Feedback and PRs welcome.

**r/LocalLLaMA**

Title: searchts: a keyless web unlocker for agents (curl_cffi → Jina → patchright) with an honest Smoke vs Walled scorecard

Body: same as the r/ClaudeAI post, with the first two paragraphs replaced by:

Most agent "web access" tools are wrappers around someone else's renderer, and when the renderer fails they hand the failure to the model. searchts is an open-source local ladder: `curl_cffi` with Chrome TLS/JA3 impersonation first, a Jina JS relay second (opt-out), and a lazily launched `patchright` Chromium third. Every read either returns real content or exits non-zero with the tier and reason.

It also decodes AI-chat share links natively (8 providers), transcribes video subtitles-first, grabs fingerprint-gated assets, and ships a reproducible two-suite benchmark instead of a marketing pass rate. MIT, Python 3.10+, keyless, no paid proxy pool.

### 6.4 60-second Reel script

- **0:00–0:05. Hook.** On-screen: "Can Agent-Reach actually watch Instagram Reels and beat 403 walls?"
  "Everyone is sharing Agent-Reach and saying it gives AI agents eyes on the whole internet. Here is what happens when you test it side by side with searchts, short for search this shit."
- **0:05–0:18. Split screen, share links.** "Drop a shared ChatGPT, Claude or Gemini link into a plain fetch and you get an app shell, not the conversation. `searchts read` decodes the provider's own payload for 8 providers, with no browser for the first five."
- **0:18–0:35. Split screen, 403 wall.** "Hit a TLS-fingerprinted page. Python's default fetch gets a 403. searchts escalates from Chrome TLS impersonation to a JS relay to a stealth browser, and scrubs invisible prompt-injection characters before the text hits your LLM. If it hits a real login wall, it fails loudly and names the tier instead of summarizing the login screen."
- **0:35–0:50. Split screen, Reels and video.** "For Instagram Reels, YouTube or TikTok, stop hand-wiring `yt-dlp` flags. `searchts transcribe <url>` takes subtitles first and falls back to Whisper, with opt-in browser cookies for a gated Reel."
- **0:50–1:00. CTA.** "MIT, free, keyless by default, and it ships an honest Smoke versus Walled scorecard. Add it to Claude Code in one line with uvx. Repo: github.com/capad-xyz/searchts."
