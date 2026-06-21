# Design inspiration / assets (`grab`, `get`)

Use these when the user wants a website's **design**, its **assets** (images,
icons, logos, fonts, CSS), or its **design tokens** (color palette, fonts in
use) — e.g. "grab the assets from this site", "what colors/fonts does X use",
"pull design inspiration from this page", "download that logo/image".

**Not this if they only want the page's words.** To summarize a page or answer a
question from its text -- even on a design site like Dribbble -- use `searchts
read` instead; it is cheaper and downloads nothing. Reach for grab/get only when
the deliverable is the asset files themselves or the palette/fonts.

Both commands fetch through the SAME escalating unlock ladder as `read`
(curl_cffi browser fingerprint -> lazy patchright stealth browser), so they
get through fingerprint-gated CDNs and many bot-walls, not just open sites.

## `searchts grab <url>` — a whole page's assets + design tokens

```bash
searchts grab https://example.com --out ./inspo
searchts grab https://example.com --kinds images,icons,svg   # only these kinds
searchts grab https://example.com --read                     # also save page.md (the copy)
searchts grab https://example.com --max 100                  # raise the asset cap (default 60)
searchts grab https://example.com --json                     # print the manifest to stdout
```

It writes to the output dir (default `./searchts-grab-<host>`):
- `images/`, `icons/`, `css/`, `fonts/`, `svg/` — the downloaded assets, by kind.
- `manifest.json` — the design summary. Key fields:
  - `title`, `theme_color`
  - `palette`: top colors as `{ "hex": "#3776ab", "count": N }`, frequency-ranked
    (hex / rgb / hsl in the HTML + CSS are all normalized to hex)
  - `fonts`: the font families in use (CSS `font-family`, `@font-face`, Google Fonts)
  - `found`: how many of each kind were discovered on the page
  - `assets`: per-file records (`source_url`, `local_path`, `bytes`, `content_type`,
    `backend`, and `ok`/`error` — a failed asset is recorded, never fatal)
  - `page_md`: `"page.md"` when `--read` was passed

To answer "what's the palette / what fonts", read `manifest.json` and report
`palette` + `fonts`. To reuse assets, point at the files under the kind folders.

## `searchts get <url>` — one asset

```bash
searchts get https://example.com/logo.svg -o logo.svg
searchts get https://cdn.example.com/file.pdf            # filename inferred from the URL
```

Downloads the raw bytes of a single image / PDF / font / file (anything) and
saves it. Prints the saved path to stdout. Use this when the user points at a
specific asset rather than a whole page.

## From an agent over MCP

- `grab_site(url, out_dir?, read?)` — returns the manifest JSON (palette, fonts,
  asset list with local paths) for design inspiration.
- `fetch_asset(url, out_dir?)` — downloads one asset, returns `{path, content_type, bytes}`.

## Notes / limits

- Best-effort and bounded: capped at `--max` assets and ~50 MB total per grab;
  one bad asset is logged in the manifest and skipped.
- Same ceiling as `read`: an interactive CAPTCHA can still block a walled asset.
- Personal-grade: runs from your own IP at personal volume. Respect each site's
  terms of service and copyright — this is for reference/inspiration, not bulk
  re-publishing.
- Write outputs to `/tmp/` (or a user-named dir), not the agent workspace.
