# Troubleshooting

Copy for an agent:

```
Searchts is acting up: https://raw.githubusercontent.com/capad-xyz/searchts/main/docs/troubleshooting.md
```

One read path: `unlocker.fetch`. Fail loud on thin pages, challenges, and login walls. **Do not** install twitter-cli, rdt-cli, or cookies so `read` can "see Twitter." There is no `searchts search-twitter`. Doctor is read-only.

## Looks like a broken install

**`example.com` is one short paragraph.** That is the whole page, not a broken install (older versions called it thin and started a browser). For a fuller first read, use Wikipedia:

```bash
searchts -v read https://en.wikipedia.org/wiki/Ada_Lovelace
```

**Reddit / LinkedIn / X often fail loud.** That is honesty, not a broken pip. Do not claim 0.8.1 unlocked them (**N7**).

**A read says the page is behind a login.** That is a fail-loud, not a broken install. The error names two ways past it: `searchts login signin URL` (sign in once in a browser searchts opens), or `searchts read URL --cookies-from-browser firefox --yes` (copy that one site's cookies from a Firefox-family browser, this session only). A saved login that has expired: `searchts login kill HOST`, then sign in again. `searchts login list` shows what is kept.

**`externally-managed-environment` (PEP 668):** do not `pip install` onto Homebrew / system Python. Keep = `pipx install "searchts[mcp]"`. Try = `uvx --from "searchts[mcp]" searchts …`.

**Windows: file lock on `searchts.exe`.** MCP `serve` is holding the shim. Stop those PIDs, then reinstall (`pipx install --force`, or `pip install --force-reinstall -e .`). Do not add a machine-wide mutex (**F11**).

**uvx "won't upgrade":** each run is latest PyPI. Nothing to upgrade.

## Doctor warnings

Optional CLIs on PATH (`gh`, `twitter-cli`, …) are probes. They are not how `read` works. Doctor does not install skills. Skill: `searchts skill install`.

## MCP / Claude

Host cannot see PATH:

```bash
claude mcp add searchts -- uvx --from "searchts[mcp]" searchts mcp serve
```

`mcp serve` is quiet on stdout on purpose (protocol). Banner is stderr.

## Update

See [docs/update.md](update.md). Keep: `pipx upgrade searchts`. venv: `pip install -U "searchts[mcp]"`.

Install: [docs/install.md](install.md)
