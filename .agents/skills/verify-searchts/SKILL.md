---
name: verify-searchts
description: "Drive searchts the way a user does and prove what it returns: read, search, transcribe, grab/get, doctor. Use before claiming a change works, when a fetch or search behaves oddly, or to answer 'is searchts ready for a real user'. CLI surface, fresh process per drive, evidence under artifacts/."
---

# Verify searchts

searchts is a CLI a user runs in a terminal. There is no server to start and no
browser to attach to: **every drive is a fresh process that exits on its own.**
The proof is the process's own output, its exit code, and what it wrote to disk.

Read `features/README.md` for the map. One file per feature, each with the
end state that proves it. Do not prove one command and call the app verified
while the map lists five.

## Launch

There is no long-lived process. Launch means: make sure the interpreter exists,
then each drive is one command.

```bash
uv venv .venv && uv pip install -c constraints.txt -e ".[dev]"
.venv/bin/python -m searchts --version      # ready when this prints searchts vX.Y.Z
```

Use `.venv/bin/python -m searchts`, not the `searchts` script on `PATH`: the
`PATH` copy may be an older global install, and a proof against the wrong build
is worse than no proof. Teardown is `rm -rf .venv` only if you created it.

## Doctor

Run this before driving anything, and again after any drive that misbehaved.

```bash
.venv/bin/python -m searchts doctor --json
```

Exit code `0` means the command ran. It does **not** mean every channel is green:
optional platform CLIs report `"status": "warn"` and that is the expected state on
a machine without them. Worth driving is: `github`, `youtube`, `tiktok`,
`instagram` all `"status": "ok"` with a non-null `active_backend`, and the whole
document is JSON on stdout.

If `github` is `warn`, `gh` is missing or unauthenticated; that is not fatal for
`read`/`search` but it means GitHub-specific paths are untested here.

## Drive

Every drive is one subprocess. Three rules keep the evidence honest:

- **Capture to a file, never pipe.** `searchts grab … | head` makes Python print
  `BrokenPipeError: [Errno 32] Broken pipe` to stderr and the proof is a truncated
  pipe rather than the tool's output. Redirect to a file.
- **`--json` for anything you assert on.** Human output is `rich`-formatted and
  moves with terminal width. `read`, `search`, `grab` and `doctor` all take
  `--json`; `transcribe` does not, so assert on the text it writes to `-o`.
- **Separate the streams.** stdout is the answer, stderr is progress. The CLI
  keeps ticks off stdout (P4.6), so a proof that greps stdout alone is a proof of
  the payload.

```bash
.venv/bin/python -m searchts read https://example.com --json \
  > artifacts/read/example.json 2> artifacts/read/example.err
echo $? > artifacts/read/example.exit
```

## Evidence

Proof lives in `artifacts/<feature>/` inside this skill directory and **survives
cleanup**. Capture, per drive: the exact command, the exit code, the full stdout,
the full stderr, and any file the drive wrote.

A proof is good enough when a reader can tell three things without running
anything: what was asked, what came back, and why that counts as working. Store
the raw JSON, not a summary of it.

Do not fake a boundary that production does not isolate. searchts hits the real
network for `read`, `search` and `transcribe`; that is the system under test, so
do not stub it. Stub only what the repo itself already stubs.

## Cleanup

- `grab` writes `./searchts-grab-<host>/` **into the current directory** unless
  `--out` says otherwise. Pass `--out` under `artifacts/`, or `rm -rf` it after.
- Nothing else leaves state behind: `read`, `search`, `get`, `doctor` write only
  where you redirect them, and `transcribe` writes only where `-o` says.
- Config lives in `~/.searchts/`. To drive without touching the user's config,
  export `HOME` to a scratch directory for that drive only:
  `HOME=$(mktemp -d) .venv/bin/python -m searchts …`.
- **Never** `pkill searchts`: a drive is a process that already exited, and that
  would kill a user's own running session.
- Cleanup removes scratch state. It never removes `artifacts/`. After cleaning,
  confirm the evidence is still there before calling the run proven.

## Helpers

No helper scripts ship with this skill yet. The three commands above are the
whole harness, which is the right size for a CLI of this shape. If a drive keeps
needing the same five lines of shell, that is the moment to add
`drive.sh` here and document its invocation below.