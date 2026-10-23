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

**A read says the page is behind a login.** That is a fail-loud, not a broken install. To use an existing profile, run `searchts login keep URL --cookies-from-browser zen --yes` or use `vivaldi` in place of `zen`. Zen is read from its Firefox profile; Vivaldi is opened with a loopback debugger port and a throwaway profile copy. Only that site's cookies are saved, and a later plain `searchts read URL` uses the saved login. For a one-read copy, use `searchts read URL --cookies-from-browser zen --yes` or `vivaldi`. A saved login that has expired: `searchts login kill URL`, then keep it again. `searchts login list` shows which sites are kept without showing cookie values.

**`externally-managed-environment` (PEP 668):** do not `pip install` onto Homebrew / system Python. Keep = `pipx install "searchts[mcp]"`. Try = `uvx --from "searchts[mcp]" searchts …`.

**Windows: file lock on `searchts.exe`.** `searchts update` renames the running executable aside and writes the new one. It does not kill anything. If another `searchts.exe` still has the file and the rename fails, quit the PIDs it prints, then run the command it prints. Do not add a machine-wide mutex (**F11**).

**uvx:** there is no persistent install. `searchts update` clears the uv cache for searchts. The next `uvx` run is the latest PyPI release.

## Doctor warnings

Optional CLIs on PATH (`gh`, `twitter-cli`, …) are probes. They are not how `read` works. Doctor does not install skills. Skill: `searchts skill install`.

## MCP / Claude

Host cannot see PATH:

```bash
claude mcp add searchts -- uvx --from "searchts[mcp]" searchts mcp serve
```

`mcp serve` is quiet on stdout on purpose (protocol). Banner is stderr.

## Update

See [docs/update.md](update.md). `searchts update` (same as `searchts upgrade`) updates the copy that is running.

Install: [docs/install.md](install.md)
