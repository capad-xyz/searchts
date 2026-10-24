# searchts — Update Guide

Copy for an agent:

```
Update searchts: run `searchts update`
```

---

## Update checks and the agent note

searchts checks for a newer release **at most once per 24 hours**. The check is
one `GET https://api.github.com/repos/capad-xyz/searchts/releases/latest` with a
`searchts/<version>` User-Agent. Nothing about the user or the machine is sent.
The answer is cached in `~/.searchts/update-check.json`; a network or cache
failure is silent.

When the latest release is newer:

- `searchts read --json` and `searchts grab --json` include a top-level
  `update_available` object (`current`, `latest`, `command`) only on that run.
  `searchts search --json` and `searchts doctor --json` are top-level lists, so
  their shape does not change.
- MCP tool results include the same object. At most once per 24 hours they also
  include one line telling the agent a newer version exists; the stamp is in
  `~/.searchts/update-notice.json`.
- A terminal still gets the stderr nudge.

Nothing is installed automatically. The command is always `searchts update`, run
by the user or by you after they agree. `SEARCHTS_NO_UPDATE_CHECK=1` turns the
check, the agent note and the stderr nudge off.

---

## For AI agents

**Do not** `pip install` onto system Python. **Do not** unzip `main.zip` as the default. **Do not** uninstall the user's tools. **Do not** kill `searchts.exe`.

### 1. Update the copy that is running

```bash
searchts update
```

`searchts upgrade` is the same command.

That command:

- upgrades a **pipx** install, including packages injected into it (for example patchright)
- upgrades a **uv tool** install
- upgrades a **venv** or pip install in place, keeping the extras already installed (`mcp`, `browser`, `cookies`, `local-transcribe`)
- fast-forwards a clean **git checkout** and reinstalls that checkout
- clears the **uvx** cache so the next `uvx` run is the latest PyPI release

It does not downgrade a copy that is already ahead of PyPI. On Windows it renames a running `searchts.exe` aside so the new file can be written. If that rename fails, it prints the PIDs and the one command to run after you quit them, and changes nothing.

`searchts update --dry-run` prints the command and does not run it. `--force` reinstalls even when the version already matches.

### 2. If this version has no `searchts update` yet

**Keep (pipx):**

```bash
pipx upgrade searchts --include-injected
```

**uv tool:**

```bash
uv tool upgrade searchts
```

**venv / packaging:**

```bash
python -m pip install -U "searchts[mcp]"
```

Add the extras this environment already has.

**uvx:** `uv cache clean --force searchts`, then the next run. There is no persistent uvx install.

Quit every `searchts.exe` first on Windows, or the file stays locked (**F11**). `searchts doctor` lists the PIDs.

### 3. One install on PATH

`where.exe searchts` can list more than one binary. `searchts update` updates the copy that is running and names any other copy that is still older. Do not keep a pipx install and a Desktop checkout on PATH together.

### 4. Skill

Doctor does not install skills, and `searchts update` does not either.

```bash
searchts skill install
```

### 5. Verify

```bash
searchts --version
searchts doctor
```

First read after update: Wikipedia shows the most; `example.com` is one short paragraph.

```bash
searchts -v read https://en.wikipedia.org/wiki/Ada_Lovelace
```

### 6. Tell the user

1. Version (`searchts --version`)
2. How this copy is installed (pipx / uv tool / venv / uvx / checkout)
3. Doctor warnings only — optional CLIs on PATH, not "searchts reads Twitter"
4. Any other `searchts` still on PATH at an older version
