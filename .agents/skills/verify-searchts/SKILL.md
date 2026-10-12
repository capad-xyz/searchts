---
name: verify-searchts
description: "Drive the searchts CLI the way a user does and prove what it returns: read, search, transcribe, grab, get, doctor. Use before claiming a fetch, search, transcription or download works, when a command behaves oddly, or to answer whether searchts is ready for a real user. One fresh process per drive, evidence captured under artifacts/."
---

# Verify searchts

searchts is a CLI a user runs in a terminal. **Every drive is a fresh process
that exits on its own**: there is no server to start, no browser to attach to and
no PTY to hold open, because none of the user-facing verbs is interactive. The
proof is the process's own output, its exit code, and the file it wrote.

Read [`features/README.md`](features/README.md) first. It holds the baseline
preconditions, the driving conventions, the proof standard and the contract every
feature file follows.

## Launch

There is no long-lived process to launch. Launch means make the interpreter
exist once, then each drive is a single command.

```bash
uv venv .venv && uv pip install -c constraints.txt -e ".[dev]"
.venv/bin/python -m searchts --version
```

Ready when that prints `searchts vX.Y.Z`. Use `.venv/bin/python -m searchts`, not
the `searchts` script on `PATH`: the `PATH` copy may be an older global install,
and a proof against the wrong build is worse than no proof. The documented
install is the one in [`CLAUDE.md`](../../../CLAUDE.md); `uv` and `pip` both work.

Teardown is `rm -rf .venv` and nothing else, and only if this run created it.

## Doctor

Run this before driving anything, and again after any drive that misbehaved.

```bash
.venv/bin/python -m searchts doctor --json
```

Exit `0` means the command ran. It does not mean every channel is green: optional
platform CLIs report `"status": "warn"` and that is the expected state on a
machine without them. Worth driving is: `github`, `youtube`, `tiktok`,
`instagram`, `reddit-video` and `rss` all `"status": "ok"` with a non-null
`active_backend`.

`web` is the one that changes what a run can prove. Read its `message`: it names
every tier of the read ladder that is missing, and a missing tier is why a
bot-walled page cannot be fetched on this machine.

## Drive

Three rules keep the evidence honest.

- **Capture to a file, never pipe.** `searchts grab … | head` makes Python write
  `BrokenPipeError: [Errno 32] Broken pipe` to stderr, and the artifact becomes
  the pipe rather than the tool. Redirect stdout and stderr separately.
- **Use `--json` wherever the verb has it.** `read`, `search`, `grab` and
  `doctor` do; `transcribe` and `get` do not and write files instead. Human
  output is `rich`-formatted and moves with terminal width, so it is not a
  stable thing to assert on.
- **Keep the streams apart.** stdout is the answer, stderr is progress. Ticks do
  not go to stdout, so a drive that asserts on stdout alone is asserting on the
  payload.

```bash
.venv/bin/python -m searchts read https://example.com --json \
  > artifacts/read/example.json 2> artifacts/read/example.err
echo $? > artifacts/read/example.exit
```

## Evidence

Proof lives in `artifacts/<feature>/` inside this skill directory and **survives
cleanup**. Capture per drive: the exact command, the exit code, the full stdout,
the full stderr, and any file the drive wrote.

A proof is good enough when a reader can tell three things without running
anything: what was asked, what came back, and why that counts as working. Store
the raw JSON, not a summary of it.

Drive the real network. searchts fetches live pages and live search results, so
that is the system under test and stubbing it proves a proxy. Mock only what the
repo itself already mocks.

## Cleanup

- Every drive's process is already gone when the drive returns. There is nothing
  to kill, and nothing may be killed by name: `pkill searchts` would take out a
  user's own session.
- `grab` writes `./searchts-grab-<host>/` into the current working directory
  unless `--out` says otherwise. Pass `--out` under `artifacts/`, or remove the
  directory afterwards.
- `get` and `transcribe` write where `-o` says. Without `-o`, `get` derives a
  name into the current directory.
- Config lives in `~/.searchts`. To drive without touching the user's config,
  export `HOME` to a scratch directory for that drive only:
  `HOME=$(mktemp -d) .venv/bin/python -m searchts …`.
- Cleanup removes scratch state. It never removes `artifacts/`. After cleaning,
  confirm the evidence is still readable at its named location before calling
  the run proven. A cleanup that eats the proof fails the run.

## Helpers

No helper scripts ship. The three commands above are the whole harness, which is
the right size for a CLI whose every verb is one short-lived process. If a drive
keeps needing the same shell, add `drive.sh` here, make it executable, and show
its invocation in this section: a helper the reader has to reverse-engineer is
not a helper.

## Keeping this honest

The map rots the moment the app changes. After changing what a command does, or
the ladder it climbs, or the channels `doctor` reports, drive that feature again
and update its file. `/maintain-verification-skill` runs that pass on a schedule.