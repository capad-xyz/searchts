# Grab a page's design

`searchts grab <url>` downloads a page's images, icons, CSS, fonts and SVG, then
reports a colour palette and the fonts in use. `searchts get <url>` is the
single-asset version of the same machinery.

## Sub-features

- `grab-assets` downloads images, icons, css, fonts and svg into a directory.
- `grab-palette` returns hex colours with occurrence counts, most used first.
- `grab-fonts` returns the font family names found in the page's CSS.
- `grab-json` emits the manifest instead of a human summary.
- `grab-kinds` narrows what is downloaded (`--kinds`), `--scripts` widens it.
- `grab-read` also saves the page text as `page.md`.
- `get-one` downloads exactly one asset to `-o`.

## How to get to it (user POV)

- `searchts grab https://tailwindcss.com --out ./out`
- `searchts get https://example.com/favicon.ico -o ./favicon.ico`

## Driving it

Preconditions: `.venv` installed. **Always pass `--out`.** Without it the CLI
writes `./searchts-grab-<host>/` into whatever directory the drive ran in, which
is how a proof leaves sixty untracked files in the repo.

- **Grab.** `.venv/bin/python -m searchts grab https://tailwindcss.com --out artifacts/grab/tailwind --json > artifacts/grab/tailwind.json 2> artifacts/grab/tailwind.err`. Exit `0`.
- **Proof.** `artifacts/grab/tailwind.json` has a `palette` array that is not
  empty, each entry with `hex` and `count`; a `fonts` array that is not empty; a
  `downloaded` count greater than zero; and `artifacts/grab/tailwind/` on disk
  containing that many files.
- **Palette is evidence, not taste.** Counts sum to more than the palette length,
  and the top entry is the most frequent colour on the page. Assert on structure
  and ordering, never on a specific hex; a site redesign changes the hex.
- **Fonts can be junk.** `fonts` can contain `"<value>"` and `"Fallback"`
  entries scraped from CSS custom properties. A non-empty array with some odd
  members is normal and is not a failure.
- **Single asset.** `.venv/bin/python -m searchts get https://example.com/favicon.ico -o artifacts/grab/favicon.ico`. Exit `0` and the file exists and is non-empty.

## Gotchas

- `download: 60` is the default ceiling (`--max`). A page with more assets
  reports 60, which is not a truncation bug.
- `theme_color` is `null` on many sites. `null` here is normal and not a failure.
- `page_backend` names which read tier fetched the page, the same field `read`
  reports as `backend`.
- `grab` follows the same unlocker as `read`, so a site behind a bot-wall may
  need `--kinds` narrowed or will fail on the fetch, not the download.
## Proven here

Driven 2026-10-12 against `searchts v0.14.0`:
`grab https://tailwindcss.com --out artifacts/grab/tailwind --json` → exit `0`,
12 palette entries whose counts sum to 571 (top `#ffffff` at 227), 9 font names
including the usual `Fallback` junk, `downloaded: 60`, and 61 files on disk. 60
is the `--max` ceiling, so a site with more assets reports the same number.
