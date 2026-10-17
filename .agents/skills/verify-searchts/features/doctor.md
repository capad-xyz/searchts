# Check the environment

Check the environment reports, per platform, which CLIs and keys are available
and which backend would serve it. It is the first thing a user runs when
something does not work, and the first thing a verification run does before
driving anything else.

## Sub-features

- `doctor-channels` reports one entry per platform.
- `doctor-status` grades each channel ok, warn, error or off with a message
  saying what to do about it.
- `doctor-backend` names the backend that would actually serve the channel, and
  `null` when nothing can.
- `doctor-tier` ranks channels by how hard they are to reach.
- `doctor-json` emits the whole report as an object.

## How to get to it (user POV)

- Run `searchts doctor` for a readable report.
- Run `searchts doctor --json` for a parseable object.

## Driving it with searchts

Preconditions: none. This is the check that decides whether the other features are
driveable, so it runs first and on its own.

- **Report.** Run `.venv/bin/python -m searchts doctor --json > artifacts/doctor/report.json 2> artifacts/doctor/report.err`. Exit code `0`.
- **Shape.** `artifacts/doctor/report.json` is an object keyed by platform name, and every entry carries `status`, `message`, `tier`, `backends` and `active_backend`.
- **Core channels.** `github`, `youtube`, `tiktok`, `instagram`, `reddit-video` and `rss` each report `ok` with a non-null `active_backend`.
- **Optional channels.** `twitter` reports `warn` with a `null` backend on any machine without the optional CLI installed, and an unconfigured search MCP reports `off`. Both are the documented expected state and neither is a broken environment.
- **Reddit's `off` is not a login requirement.** The `reddit` entry is a *channel* probe (OpenCLI, rdt-cli) and reports `off` when neither is installed. Read its message: it must say the login is the channel's and point at `searchts read <url>` for reading public pages, with the browser tier named. A message that says Reddit needs a login to be read is the report being wrong about the product.
- **Read tiers.** The `web` entry reports `warn` whenever any tier of the read ladder is missing and its message names them. Read it every run, because it is the ceiling on what any fetch-driven feature can be proved against on this machine.
- **Proof.** Open `artifacts/doctor/report.json` and read the `message` of every entry that is not `ok`. A report where each warning names the install that would clear it is the proof; the status field alone would pass on a report that told the user nothing.
- **Re-run after surprise.** If a drive failed in a way the report does not explain, run this again before concluding anything about the feature.

## Gotchas

- Exit code `0` does not mean every channel is green. Judge each channel's
  `status`, not the exit code.
- The optional platform CLIs are availability probes. They are not how reading
  works, and their absence never blocks a fetch.
- Some entries perform a live network probe, so this is the one drive that can
  fail on a flaky network. Re-run once before calling it a regression.
- `warn` on `web` is the entry that quietly invalidates a "read a bot-walled
  page" claim. Reporting `ok` on the whole document while skipping that message
  is how an unprovable run looks proved.