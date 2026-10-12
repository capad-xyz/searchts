# Download one asset

Download one asset saves exactly one file from a URL to a path you name, through
the same escalating fetch as reading a page. It is the single-asset form of
grabbing a page's design.

## Sub-features

- `get-one` writes one asset to the path given by `-o`.
- `get-derived-name` derives a filename from the URL when `-o` is omitted.
- `get-escalate` climbs the same ladder as a read, so an asset behind a wall
  needs the same tiers installed.

## How to get to it (user POV)

- Run `searchts get <url> -o ./file` to choose where it lands.
- Run `searchts get <url>` to accept the derived name.

## Driving it with searchts

Preconditions:

- `.venv` is installed as `SKILL.md` describes.
- `doctor --json` has been run and its `web` message read.
- The URL is an asset that exists. Pointing this at a page URL or at a host that
  serves no such file proves nothing about the verb.

- **Download.** Run `.venv/bin/python -m searchts get https://docs.python.org/3/_static/pygments.css -o artifacts/get/pygments.css > artifacts/get/pygments.out 2> artifacts/get/pygments.err`. Exit code `0`.
- **Payload.** Open `artifacts/get/pygments.css`. It is non-empty and its first bytes are a real stylesheet rule, not an HTML document tag.
- **Side effect.** The file exists at the exact path `-o` named. This is the one feature whose proof is a file on disk, so a passing exit code with nothing at that path has proved nothing.
- **Absent asset.** Run `.venv/bin/python -m searchts get https://example.com/favicon.ico -o artifacts/get/favicon.ico > artifacts/get/favicon.out 2> artifacts/get/favicon.err`. Exit code is non-zero, nothing is written at the path, and the stderr names the tiers that were tried.
- **Proof.** Open `artifacts/get/pygments.css` and `artifacts/get/favicon.err`. One shows real bytes at a named path and one shows a missing asset producing no file and a named reason.
- **Clean the working directory.** Confirm no derived-name file was left in the working directory by a drive that omitted `-o`.

## Gotchas

- `https://example.com/favicon.ico` does not exist. example.com serves no
  favicon, so that drive fails at the fetch and proves nothing about the verb.
  Pick an asset you have confirmed is served.
- Without `-o` the filename is derived from the URL path and lands in the
  current working directory. Always pass `-o`.
- A login wall that answers with an HTML page and a success status will save HTML
  under the asset's name. If the first bytes are a document tag, the fetch was
  fooled rather than the save.
- The read-tier limits apply unchanged: with only the first tier installed, an
  asset behind a wall cannot be reached.