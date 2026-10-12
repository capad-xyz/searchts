# searchts feature map

Five user-facing features, one file each. Each file answers, from a user's point
of view: what it is, how to reach it, how to drive it, and what end state proves
it worked.

**Proof standard.** The end state is the tool's own output: the JSON it printed,
the file it wrote, the exit code it returned. Not "it did not error". A command
that exits `0` having produced nothing is a failure, and so is one that exits
non-zero having produced the right thing.

**Before driving:** run `doctor --json` (see `../SKILL.md`). After a drive that
misbehaved, run it again before believing anything about the next one.

One command the user reaches for that is **not** on this map: the read ladder's
higher tiers. `stealth-browser` needs `searchts install --browser`, and until it
is installed a bot-walled page cannot be fetched at all. That is a readiness
fact about the machine, not a gap in the map, and it is recorded in
[`doctor.md`](doctor.md) and [`read.md`](read.md).

| Feature | File | End state that proves it |
|---|---|---|
| Read a page | [read.md](read.md) | JSON with `status: 200`, non-empty `text`, a named `backend` |
| Search the web | [search.md](search.md) | JSON array with `title`, `url`, `snippet`, `source` per hit |
| Transcribe a video | [transcribe.md](transcribe.md) | a text file on disk with real sentences, `exit 0` |
| Grab a page's design | [grab.md](grab.md) | manifest JSON with a non-empty `palette` and `downloaded > 0` |
| Download one asset | [get.md](get.md) | a non-empty file at the path `-o` named |
| Check the environment | [doctor.md](doctor.md) | JSON where the core channels are `ok` with an `active_backend` |

## What this map does not cover

- The MCP server (`searchts mcp serve`). It is a second surface over the same
  functions, and it needs its own entry here before anyone calls the MCP path
  verified.
- `setup`, `install`, `configure`, `uninstall`, `skill`. Interactive and
  destructive; they change the user's machine and are proven by their own
  install/uninstall tests, not by driving them.
- Any tier of the read ladder above `curl_cffi`. `stealth-browser` needs
  `searchts install --browser` and is proven in CI, not here.