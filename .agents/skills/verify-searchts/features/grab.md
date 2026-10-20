# Grab a page's design

Grab a page's design downloads a page's images, icons, stylesheets, fonts and
vector art into a directory, and reports the colour palette and the fonts the
page uses. It is the on-demand asset grabber, reached through the same escalating
fetch as reading a page.

## Sub-features

- `grab-assets` downloads images, icons, css, fonts, svg and inline svg into a directory.
- `grab-kinds` narrows which kinds are downloaded.
- `grab-scripts` widens the set to script sources.
- `grab-palette` returns hex colours with occurrence counts, ordered by weight (frequency plus semantic use).
- `grab-fonts` returns the font family names found in the page.
- `grab-json` emits the manifest as an object.
- `grab-omit` names every asset a cap left out, on stderr and in the manifest.
- `grab-rungs` records the fetch tiers tried and how many assets each found.
- `grab-tokens` reports CSS variables, gradients and design tokens.
- `grab-read` also saves the page text alongside the assets.
- `grab-max` caps how many assets are downloaded.

## How to get to it (user POV)

- Run `searchts grab <url>` to download into a directory beside you.
- Run `searchts grab <url> --out ./out` to choose the directory.
- Run `searchts grab <url> --json` to print the manifest.
- Run `searchts grab <url> --read` to keep the page text too.

## Driving it with searchts

Preconditions:

- `.venv` is installed as `SKILL.md` describes.
- `doctor --json` has been run. Grab climbs the same ladder as reading, so a
  missing tier bounds it the same way.

- **Grab.** Run `.venv/bin/python -m searchts grab https://tailwindcss.com --out artifacts/grab/tailwind --json > artifacts/grab/tailwind.json 2> artifacts/grab/tailwind.err`. Exit code `0`.
- **Palette.** Read `artifacts/grab/tailwind.json`. Its `palette` is a non-empty array and each entry has `hex`, `count`, `semantic` and `weight`. The counts sum to more than the array's length, and the first entry has the highest `weight`.
- **Fonts.** The `fonts` array is non-empty.
- **Downloaded files.** `downloaded` in the manifest is greater than zero, and `artifacts/grab/tailwind/` holds that many files plus `manifest.json` (`page.md` too when `--read` is passed).
- **Types and rules.** The manifest has at least one saved `css` asset and at least one saved `fonts` asset, and `css_variables` is non-empty.
- **Narrow the set.** Run `.venv/bin/python -m searchts grab https://tailwindcss.com --out artifacts/grab/icons --kinds icons --json > artifacts/grab/icons.json 2> artifacts/grab/icons.err`. Exit code `0` and the manifest's icon count is lower than the unfiltered run's.
- **Name the omissions.** Run `.venv/bin/python -m searchts grab https://aweiro.studio --max 12 --out artifacts/grab/cap --json > artifacts/grab/cap.json 2> artifacts/grab/cap.err`. Exit code `0`, `omitted_count` is greater than zero, every `omitted` entry has `reason`, `kind`, `count` and `urls`, and `cap.err` contains `omitted:`. The JSON on stdout still parses.
- **Proof.** Open `artifacts/grab/tailwind.json` and count the files in `artifacts/grab/tailwind/`. The manifest's `downloaded` number and the directory's file count agreeing is what shows the assets really landed, rather than the manifest describing a download that did not happen.
- **Clean the working directory.** Confirm `searchts-grab-<host>/` does not exist in the working directory. Any drive that omitted `--out` leaves one, and it must be removed.

## Gotchas

- Without `--out` the assets land in a `searchts-grab-<host>` directory in the
  current working directory. Always pass `--out`.
- `download` reaching its ceiling is normal, not truncation: the default ceiling
  is 120 assets, CSS and fonts are saved before images, and a larger page reports
  exactly what was left out in `omitted` and on stderr. That note is printed with
  `--json` too, on stderr, so stdout stays parseable.
- `theme_color` is `null` on many sites. That is not a failure.
- `page_backend` names the fetch tier that retrieved the page, and it carries
  the same meaning as the `backend` field of a read. `page_rungs` lists each tier
  tried and the asset count it found.
- Palette entries carry `hex`, raw `count`, a `semantic` score and a `weight`.
  The semantic score adds to frequency for colors used on body, headings, links,
  buttons and semantic variables, so a reset stylesheet's black and white does
  not hide the brand.
- Fonts declared only as synthetic local fallbacks (`... Fallback`) are not
  listed; the real families are.
- Images a stylesheet paints (`background-image`, masks) are collected from the
  saved CSS, not just from HTML attributes.
- `--read` failing to save `page.md` is named in `page_md_error` and on stderr;
  it is not reported as success.
- Inline `<svg>` art is saved as its own file and counted under `inline_svg`.
  Its manifest `source_url` is a stable `inline:<hash>` label rather than the
  whole data URI, and `inline` is `true`. A page with more inline art than the
  cap allows names the rest in `omitted`.
