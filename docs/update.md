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
