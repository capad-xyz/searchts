# searchts — Install

Copy for an agent:

```
Install searchts using https://raw.githubusercontent.com/capad-xyz/searchts/main/docs/install.md
```

---

## For AI agents

**Do not** `pip install` onto system / Homebrew / PEP 668 Python. **Do not** run `searchts install --env=auto` as the product. **Do not** install twitter-cli / rdt-cli / cookies so `read` can "see Twitter." One read path: `unlocker.fetch`. Fail loud on walls.

### Keep (pipx)

```bash
pipx install "searchts[mcp]"
searchts --version
```

### Try / Claude MCP (no PATH)

```bash
uvx --from "searchts[mcp]" searchts -v read https://en.wikipedia.org/wiki/Ada_Lovelace
claude mcp add searchts -- uvx --from "searchts[mcp]" searchts mcp serve
```

uvx is already latest PyPI each run.

### venv only

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install "searchts[mcp]"
```

Windows Store `python3` alias: use `py -3` instead.

If `searchts.exe` / `mcp serve` is running (Windows), stop it before reinstall (**F11**).

### Browser / stealth (keep-path)

Recommended after a keep install (`pipx` or a real venv). One command installs the `[browser]` extra and Chromium into **the same environment** as the running `searchts` CLI:

```bash
searchts install --browser
searchts doctor
```

It prints which env it is mutating (pipx / uv tool / venv / editable).

- **pipx / venv / editable**: installs browser deps into that env, then downloads Chromium (progress on stderr). Chromium itself lives in the per-user ms-playwright cache.
- **uv tool**: does not inject into the tool env (upgrade wipes it). Prints `uv tool install "searchts[mcp,browser]" --force` (quit `searchts.exe` first on Windows, F11), then still runs the Chromium step if patchright is already importable.
- **ephemeral uvx**: if patchright is already on the uvx env, only installs Chromium into the user cache. If patchright is missing:

```bash
uvx --from "searchts[browser]@latest" searchts install --browser
```

Manual equivalent (venv only): `pip install "searchts[browser]"` then `patchright install chromium`.

### After install

```bash
searchts doctor
searchts -v read https://en.wikipedia.org/wiki/Ada_Lovelace
```

Doctor is **read-only**. It probes optional CLIs on PATH (`gh`, …). Those are not how `read` works. Reddit/LinkedIn often **fail loud**. That is honesty, not a broken install.

`example.com` is thinner than `_MIN_CHARS` and looks like a failed install. Use Wikipedia.

Skill (optional, not doctor): `searchts skill install`

Full README: https://github.com/capad-xyz/searchts/blob/main/README.md
Upgrade: https://github.com/capad-xyz/searchts/blob/main/docs/update.md
