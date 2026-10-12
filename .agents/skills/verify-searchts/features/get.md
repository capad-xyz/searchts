# Download one asset

`searchts get <url>` downloads exactly one file through the same escalating
unlocker `read` uses, to a path you name. It is the single-asset half of
[`grab`](grab.md) and shares its ladder.

## Sub-features

- `get-one` writes one asset to `-o <path>`.
- `get-escalate` climbs the same ladder, so an asset behind a bot-wall needs the
  same tiers installed as a page.
- `get-default-name` derives a filename from the URL when `-o` is omitted.

## How to get to it (user POV)

- `searchts get https://docs.python.org/3/_static/pygments.css -o ./pygments.css`
- `searchts get <url>`  (writes a derived name into the current directory)

## Driving it

Preconditions: `.venv` installed. The URL must be an **asset**, not a page: a
page fetched with `get` returns the page's bytes under a misleading name, and
that is the caller's mistake rather than a proof either way.

- **Download.** `.venv/bin/python -m searchts get https://docs.python.org/3/_static/pygments.css -o artifacts/get/pygments.css > artifacts/get/pygments.out 2> artifacts/get/pygments.err`. Exit `0`.
- **Proof.** `artifacts/get/pygments.css` exists and is **not empty**. Exit `0`
  with a zero-byte file is a failure: the exit code and the payload are separate
  claims.
- **Bytes are the asset, not the name.** The file starts with a real CSS rule
  (`pre { … }`), not `<!DOCTYPE`. Assert on the first bytes, not the extension
  the tool chose.
- **Side effect, not just output.** This is the one verb whose proof is a file on
  disk. A drive that passes but leaves nothing at `-o` has proven nothing.

## Gotchas

- **Do not use `https://example.com/favicon.ico` as the example URL.** example.com
  serves no favicon, so the drive fails at `http-404` and proves nothing about
  `get`. Pick an asset you have confirmed exists.
- Without `-o` the filename is derived from the URL path and lands in the current
  directory. Always pass `-o`, for the same reason `grab` always passes `--out`.
- An asset served with `Content-Type: text/html` behind a 200 (a login wall) will
  download as HTML under a `.png` name. If the first bytes are `<!DOCTYPE`, the
  ladder was fooled, not the downloader.
- The same tier warnings as `read` apply: with only `curl_cffi` installed, an
  asset behind a bot-wall cannot be reached. The 404 stderr above names
  `curl_cffi` and `stealth-browser` for exactly this reason.

## Proven here

Driven 2026-10-12 against `searchts v0.14.0`:
`get https://docs.python.org/3/_static/pygments.css -o …` → exit `0`, 4,848 bytes
of real CSS, stderr naming the fetch and the save.
