# searchts verification map

This directory is the maintained source for verifying the user-facing behavior of
searchts. Read this index before driving anything, then use the matching feature
file as the recipe.

## Baseline preconditions

- The repo is checked out and `.venv` exists with `[dev]` installed, as
  [`SKILL.md`](../SKILL.md) describes.
- `searchts install --browser` works in that `.venv`. A venv made by `uv venv`
  has no `pip` module, so an installer that only knows `python -m pip` fails
  there with "No module named pip" on the documented install path.
- `python -m searchts doctor --json` has been run in this run, and its `github`,
  `youtube`, `tiktok`, `instagram`, `reddit-video` and `rss` entries are `ok`.
- The `web` entry has been read, not just its status. Its message names any read
  tier that is not installed, which bounds what a hard `read` can prove here.
- No drive has been run against a different interpreter than
  `.venv/bin/python -m searchts`.
- Never drive a process this run did not start. Nothing here is long-lived, so
  there is no shared instance to corrupt.

## Driving conventions

- Treat every command as literal. Keep quoted URLs and flags unchanged.
- Start every recipe from the baseline unless its preconditions say otherwise.
- Capture stdout and stderr to separate files. Never pipe a searchts verb into
  `head` or `grep`.
- Use `--json` for any assertion on structured output. Human output moves with
  terminal width.
- Assert on the payload, not on the exit code alone. A verb that exits `0` having
  produced nothing has failed.
- Set `HOME` to a scratch directory when a drive must not read the user's
  `~/.searchts` config.
- Pass `--out` or `-o` to every verb that writes, so no drive leaves files in the
  working directory.
- Do not remove proof artifacts during cleanup.

## Proof and skip reporting

- CLI proof includes the command, stdout, stderr and exit code.
- A verb whose proof is a file on disk is proved by that file's bytes, not by its
  name.
- Record the feature and the command used with every artifact.
- Report an unreachable path with the attempted command and the unmet
  precondition. A missing read tier, a missing optional provider and an absent
  `patchright` are preconditions, not failures.
- Do not report one entry point as verified through a different path. `read` and
  `get` climb the same ladder and neither proves the other.

## Feature entry contract

Each feature file starts with an H1 title and one paragraph describing the
user-visible behavior. It then uses exactly four H2 sections in this order.

1. `Sub-features` lists short IDs with one line for each behavior.
2. `How to get to it (user POV)` lists every user entry point.
3. `Driving it with searchts` starts with `Preconditions:` and uses labeled
   bullets that pair each user action with an exact command and observable
   result.
4. `Gotchas` lists traps that can waste or invalidate a verification run.

Keep implementation details out of the map. Name only user paths, commands,
required state and observable proof.

## Features

- [Read a page](./read.md) covers the escalating fetch, JSON output, pagination,
  injection scrubbing, and the non-zero exit when no tier produced content.
- [Search the web](./search.md) covers keyless multi-provider search, the JSON
  result shape, and an empty result set as a valid answer.
- [Transcribe a video](./transcribe.md) covers caption-first transcription, the
  output file, and local audio input.
- [Grab a page's design](./grab.md) covers asset download, the colour palette,
  font extraction and the manifest.
- [Download one asset](./get.md) covers the single-asset download and the file it
  writes.
- [Check the environment](./doctor.md) covers per-channel status, the active
  backend, and the read-tier report that bounds every other feature.
- [Keep a site login](./login.md) covers copying one site's cookies from Zen or
  Vivaldi, saving them, and proving a later read uses the saved login.

Not covered, and named so no run claims it: `searchts mcp serve` is a second
surface over the same functions and no feature file here drives it. The
install, setup and uninstall verbs change the user's machine and are proved by
their own tests, not by driving them. Every tier of the read ladder above the
first needs an extra install and is bounded per run by the `doctor` entry.

Two verbs are driven here only as far as a non-interactive run can go, and
both must fail cleanly rather than crash: `searchts setup` with stdin closed
finishes the steps that need no answer (its prompts say "press Enter to skip",
so a closed stdin is the same answer) and prints no traceback; `searchts
login list` into a scratch `HOME` prints that no site logins are kept.
