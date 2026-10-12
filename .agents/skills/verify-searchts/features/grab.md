# Grab a page's design

Grab a page's design downloads a page's images, icons, stylesheets, fonts and
vector art into a directory, and reports the colour palette and the fonts the
page uses. It is the on-demand asset grabber, reached through the same escalating
fetch as reading a page.

## Sub-features

- `grab-assets` downloads images, icons, css, fonts and svg into a directory.
- `grab-kinds` narrows which kinds are downloaded.
- `grab-scripts` widens the set to script sources.
- `grab-palette` returns hex colours with occurrence counts, most used first.
- `grab-fonts` returns the font family names found in the page.
- `grab-json` emits the manifest as an object.
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
- **Palette.** Read `artifacts/grab/tailwind.json`. Its `palette` is a non-empty array and each entry has `hex` and `count`. The counts sum to more than the array's length and the first entry is the most frequent colour on the page.
- **Fonts.** The `fonts` array is non-empty.
- **Downloaded files.** `downloaded` in the manifest is greater than zero, and `artifacts/grab/tailwind/` holds that many files.
- **Narrow the set.** Run `.venv/bin/python -m searchts grab https://tailwindcss.com --out artifacts/grab/icons --kinds icons --json > artifacts/grab/icons.json 2> artifacts/grab/icons.err`. Exit code `0` and the manifest's icon count is lower than the unfiltered run's.
- **Proof.** Open `artifacts/grab/tailwind.json` and count the files in `artifacts/grab/tailwind/`. The manifest's `downloaded` number and the directory's file count agreeing is what shows the assets really landed, rather than the manifest describing a download that did not happen.
- **Clean the working directory.** Confirm `searchts-grab-<host>/` does not exist in the working directory. Any drive that omitted `--out` leaves one, and it must be removed.

## Gotchas

- Without `--out` the assets land in a `searchts-grab-<host>` directory in the
  current working directory. Always pass `--out`.
- `download` reaching its ceiling is normal, not truncation: the default ceiling
  is 60 assets and a larger page reports exactly that.
- `theme_color` is `null` on many sites. That is not a failure.
- `page_backend` names the fetch tier that retrieved the page, and it carries
  the same meaning as the `backend` field of a read.
- Palette entries are evidence of frequency, not of taste. A site redesign
  changes the hex values, so assert on structure and ordering and never on a
  specific colour.
- Font names scraped from stylesheets can include placeholders such as `Fallback`
  and property values. That is normal and is not a failure.