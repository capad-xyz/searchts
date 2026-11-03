# Browser settings, detection, and the login-wall offer

## Settings and precedence

The browser and profile settings are browser-neutral. The old LinkedIn-shaped
names remain aliases:

| Purpose | Preferred | Legacy alias |
|---|---|---|
| Browser, name or executable | `SEARCHTS_BROWSER` | `SEARCHTS_LINKEDIN_CHROME` |
| Profile / user-data directory | `SEARCHTS_BROWSER_PROFILE` | `SEARCHTS_LINKEDIN_PROFILE` |

Precedence is **per setting**:

1. If the preferred variable is set and non-blank, it wins.
2. Otherwise the legacy alias is used.
3. If neither is set, the Chromium attach path uses that browser's default
   user-data directory. The LinkedIn feed still needs an explicit profile; run
   `searchts doctor` to see the profiles detection found.

Because precedence is per setting, `SEARCHTS_BROWSER=vivaldi` with only
`SEARCHTS_LINKEDIN_PROFILE` set uses Vivaldi *and* that legacy profile. A
machine that already exports the legacy pair keeps working unchanged.

`SEARCHTS_BROWSER` accepts either an executable path or a supported browser
name (`chrome`, `edge`, `brave`, `vivaldi`, `opera`, `arc`, `chromium`,
`firefox`, `zen`, `librewolf`, `waterfox`, `floorp`, `mullvad`). A name is
resolved to an installed executable when one is found; otherwise it is passed
through unchanged so a failure names what was asked for.

## What detection covers

`searchts doctor` lists every supported browser it finds, on Windows, macOS
and Linux. Detection is paths only: it does not open a cookie database.

- **Chromium family:** Chrome, Edge, Brave, Vivaldi, Opera, Arc, Chromium.
- **Firefox family:** Firefox, Zen, LibreWolf, Waterfox, Floorp, Mullvad.

Each entry shows the executable when one is found, the user-data directory,
and every profile with a cookie database. A browser is marked `running` when
its profile lock names a live process. A Chromium is marked
`remote debugging on (port N)` only when its `DevToolsActivePort` parses *and*
something accepts a connection on that loopback port; a stale file left by a
browser that has exited does not count.

`searchts doctor --json` adds a `browsers` array with the same information.

## On a login wall

When `searchts read <url>` fails with a login wall on a site other than
LinkedIn, searchts asks each installed browser profile one yes/no question:

> does this profile hold a cookie for the site's registrable domain?

That is **presence only**. The scan:

- opens the cookie database read-only and selects the host column only;
- never selects a name, value or encrypted blob;
- never decrypts anything and never asks the OS keychain for a key;
- never prints or logs a cookie name or value;
- if the database is locked, copies it (and its `-wal`/`-shm` sidecars) to a
  temporary file, reads that, and deletes it immediately; if that also fails,
  it says the profile was skipped instead of guessing "no".

If one or more profiles answer yes:

- **On a terminal**, searchts lists the browsers and asks which one to copy
  from, then asks once more for an explicit `[y/N]`. Only a yes copies. The
  copy goes through the same `searchts login keep` path as the CLI: session
  grant, host-scoped copy, kept-login store.
- **Without a terminal, or with `--json`**, nothing is copied. The exact
  command is printed instead:

  ```bash
  searchts login keep example.com --cookies-from-browser chrome --yes
  ```

LinkedIn is excluded from the scan. A LinkedIn wall points at attach instead:
set `SEARCHTS_LINKEDIN_ATTACH=on`, open
`chrome://inspect/#remote-debugging` (or `vivaldi://`, `edge://`,
`brave://` on those browsers) and tick **Allow remote debugging for this
browser instance**. See [Firefox-family attach research](firefox-attach-research.md)
for why the Firefox family stays on cookie copy.
