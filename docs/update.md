# searchts — Update Guide

Copy for an agent:

```
Update searchts using https://raw.githubusercontent.com/capad-xyz/searchts/main/docs/update.md
```

---

## For AI agents

**Do not** `pip install` onto system Python. **Do not** unzip `main.zip` as the default. **Do not** uninstall the user's tools.

### 1. How they installed

```bash
searchts --version
command -v searchts || true
```

### 2. Update the package

**Keep (pipx):**

```bash
pipx upgrade searchts
```

**venv / packaging:**

```bash
pip install -U "searchts[mcp]"
```

**Try (uvx):** already the latest PyPI each run. Nothing to upgrade.

If `searchts.exe` / `mcp serve` is running (Windows), stop it first or pipx will hit a file lock (**F11**).

### Windows: one install

`where.exe searchts` can list more than one binary. The first PATH hit is what a host launches as MCP.

Do not keep pipx (`~/.local/bin`) and an editable Desktop checkout on PATH together. Pick one:

- **pipx** after a PyPI release: `pipx upgrade searchts`
- **repo / main:** from the checkout, `python -m searchts …`. Point the host MCP `cwd` at that folder.

Quit every host that spawned `mcp serve` before replacing `searchts.exe`. `searchts doctor` lists the PIDs. There is no `searchts mcp stop`.

### 3. Skill (optional)

Doctor does **not** install skills.

```bash
searchts skill install
```

### 4. Verify

```bash
searchts --version
searchts doctor
```

First read after update: Wikipedia, not `example.com`.

```bash
searchts -v read https://en.wikipedia.org/wiki/Ada_Lovelace
```

### 5. Tell the user

1. Version (`searchts --version`)
2. How they install (pipx / venv / uvx)
3. Doctor warnings only — optional CLIs on PATH, not “searchts reads Twitter”
4. `check-update` notes if any
5. Optional: a one-line stderr nudge on interactive commands when a newer
   GitHub release exists (F13). Hidden by `SEARCHTS_NO_UPDATE_CHECK=1`.
   Never on `mcp serve` or pipes.
