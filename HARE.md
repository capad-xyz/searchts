# HARE.md

Hare's own file on this repo. AGENTS.md is the contract every agent signs; this
is what Hare holds this repo to, and what it has learned. Hare reads both before
every note. How Hare works is in [docs/hare.md](docs/hare.md).

Two parts. Rules the owner wrote by hand, anywhere outside the marked block. And
the marked block, which `scripts/hare_ledger.py` rewrites on the weekly ledger
run from `/hare score 1..5 <why>` comments: a score of 2 or less with a reason
becomes a line. To retire one, delete the score comment it came from, or edit it
to a 3 or higher; the next run drops the line.

## Owner's rules

- **Tests run the real code.** Fake the network, the clock and the disk, never the function the test is named after. A test that stubs the unit it covers, or reads source text instead of running it, is a real finding, not a skip. (#269, #275)
- **Anything of unknown size has a bound.** A log, a response body, a file: stream it or cap it, or the PR says why not. An unbounded read is a real finding. (#269, #275)
- **A changed rule leaves no old copy behind.** When the diff changes how something works, check AGENTS.md, HARE.md and the docs for lines that still say the old thing. Agents read those files, so a contradiction is a real finding. (#269)
- **One read path.** Every read goes through `unlocker.fetch`; do not suggest routing reads by channel.
- **Doctor only reads.** Do not suggest wiring config keys that nothing uses.
- **Honest over clever.** searchts is a keyless reader: prefer saying plainly that a page could not be read over a feature that guesses.
- **CI scripts may log with `print`.** P4.6 (progress on stderr, never stdout) protects searchts's CLI and MCP output. Scripts under `scripts/` and `.github/` write to the Actions log, where stdout is only a log, and they do not import searchts. A `print` there is not a finding. (#233, #268)
- **What counts as real here.** On top of the general list in Hare's prompt: progress or ticks on stdout (P4.6: stdout is the CLI's and the MCP server's output), anything that breaks the MCP protocol, and a diff that misses the intent named for that item in [`PLAN.md`](PLAN.md) (searchts) or [`docs/hare-next.md`](docs/hare-next.md) (Hare).
- **Line length is the formatter's, not a finding.** The limit is `line-length = 100` in pyproject.toml, not 80, and ruff does not enforce it (E501 is off), so do not flag a long line. A line that is hard to read because of what it does is a finding about what it does.

<!-- hare-ledger:rules -->
**What the owner said Hare missed (from the ledger, PLAN R2c).** Each line is the reason behind a low score, filed by `scripts/hare_ledger.py` from `/hare score`. Hare reads these as rules for the next note. Each ledger run rewrites this block; to retire a line, delete its score comment or edit the score to 3 or higher.

- Held nothing, so it cost nothing, but it read an incremental diff as the whole PR again and returned prose where the prompt asks for JSON. The 2 is for the same reason as 321's: correct-by-accident is. (#324, scored 2/5 on 2026-10-07)
- Ship on the sidebar regex was already scored. This note holds the PR for the coverage carve-out and uninstall --browser. The carve-out arrived with main (#302). uninstall is #304. Neither is this diff. (#306, scored 2/5 on 2026-10-06)
- the double-fetch note was already scored. This note holds the PR for uninstall --browser and the Jina global. Neither file is in this diff. They are on main, from #304 and #305, because the branch mer. (#303, scored 2/5 on 2026-10-06)
- the same model asked to shorten this comment and then to lengthen it; the cause belongs in the comment, the flip does not. (#299, scored 2/5 on 2026-10-05)
- said Ship while a comment Hare itself posts would start a run in the command's own concurrency group and cancel it; check what every new side effect triggers. (#282, scored 2/5 on 2026-10-05)
- missed an unbounded read of a whole job log and AGENTS.md lines contradicting the diff; called a test that checks source text instead of behaviour a skip, when it is real. (#269, scored 2/5 on 2026-10-04)
<!-- /hare-ledger:rules -->
