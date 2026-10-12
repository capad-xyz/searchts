# Check the environment

`searchts doctor` reports, per platform, which CLIs and keys are available and
which backend would serve it. It is the first thing a user runs when something
does not work, and the first thing an agent runs before driving anything.

## Sub-features

- `doctor-channels` reports one entry per platform (github, twitter, youtube,
  tiktok, instagram, and the rest).
- `doctor-status` grades each channel `ok`, `warn` or `error`, with a `message`
  saying what to do about it.
- `doctor-backend` names the `active_backend` that would actually serve the
  channel, `null` when nothing can.
- `doctor-tier` ranks channels by how hard they are to reach (tier 0, 1, …).
- `doctor-json` emits the whole report as JSON.

## How to get to it (user POV)

- `searchts doctor`
- `searchts doctor --json`

## Driving it

Preconditions: none. This is the check that decides whether the other four
features are driveable, so it runs first and runs alone.

- **Report.** `.venv/bin/python -m searchts doctor --json > artifacts/doctor/report.json 2> artifacts/doctor/report.err`. Exit `0`.
- **Proof.** `artifacts/doctor/report.json` is a JSON object keyed by platform
  name. `github`, `youtube`, `tiktok`, `instagram` and `rss` each have
  `"status": "ok"` with a non-null `active_backend`, and every `ok` entry has a
  `message` a user could act on.
- **`web` is the one to read.** `web` reports `"status": "warn"` whenever any
  tier of the read ladder is missing, and it names which:
  `Jina Reader not available (http-403); stealth-browser not installed`. It still
  carries `active_backend: curl_cffi`, so `read` works, but only on the first
  tier. On a machine in that state a bot-walled page fails. Treat `web: warn` as
  a readiness fact, not a broken install, and say so in any verdict.
- **Warnings are the normal state.** `twitter` is `"status": "warn"` with
  `active_backend: null` on any machine without `twitter-cli` installed. That is
  the documented expected state, not a broken environment, and not something to
  install during a proof. `exa_search` is `"status": "off"` for the same reason.
- **Errors are the alarm.** A `"status": "error"` on `github` means `gh` is
  present but failing, which changes what can be proven in this run. Stop and
  report it rather than driving around it.

## Gotchas

- Exit code `0` does not mean every channel is green. Judge each channel's
  `status`, not the exit code.
- Optional platform CLIs (`twitter-cli`, `OpenCLI`, `gh`, `mcporter`) are PATH
  probes. They are not how `read` works, and their absence never blocks a fetch.
- `doctor` performs a real network probe on some channels, so it is the one drive
  that can fail on a flaky network. Re-run once before calling it a regression.
## Proven here

Driven 2026-10-12 against `searchts v0.14.0`: exit `0`, 12 channels.
`github` ok via `gh CLI`; `youtube`, `tiktok`, `instagram` and `reddit-video` ok
via `yt-dlp`; `rss` ok via `feedparser`; `twitter` warn; `exa_search` off; and
`web` **warn**: `Jina Reader not available (http-403); stealth-browser not
installed`, with `active_backend: curl_cffi` still serving. On that machine a
bot-walled page cannot be read at all.
