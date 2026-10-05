# HARE.md

Hare's own file on this repo. AGENTS.md is the contract every agent signs; this
is how Hare runs here and what it has learned. Hare reads both before every note.

Three parts. How Hare works, below. Rules the owner wrote by hand, anywhere
outside the marked block. And the marked block, which `scripts/hare_ledger.py`
rewrites on the weekly ledger run from `/hare score 1..5 <why>` comments: a score
of 2 or less with a reason becomes a line. To retire one, delete the score
comment it came from, or edit it to a 3 or higher; the next run drops the line.

## How Hare works here

1. A PR opens or gets a push, or someone with write access comments `/hare`.
   A command gets 🐇 at once, or 🐢 for `/hare think`; the note quotes the request
   and the sign is removed when it lands. Re-run on Hare's check also reviews
   again, and the note says who pressed it.
   The Action `hare / r1` runs `scripts/hare_r1.py` from main. A fixed list of
   free model hops (PLAN R1c) is tried in order; the first that answers writes
   the review. If none answers, Hare posts a needed comment instead.
2. Hare reads AGENTS.md, this file, and what the ledger knows about the files in
   the diff, then posts one review: summary, CI, intent, a verdict (Ship, Hold, or Wait
   while CI runs, from CI and the real findings, then the model's case), findings with bubbles
   on the lines (a one-click fix where the fix is small), a checks fold, and a
   fold on how to answer. A later push gets a Since section on each old finding.
3. The owner answers with PR comments: `/hare score 1..5 <why>` on a note,
   `/hare fate <path:line> fixed|wrong|wontfix <why>` on one finding. Hare
   records both and posts nothing.
4. Every Sunday the ledger run rebuilds `docs/hare-ledger.md` from the notes,
   Since lines, resolved threads and those comments, rewrites the block below
   from low scores, opens a PR, asks Hare to review it, and merges it unless
   Hare finds a real problem.

## Owner's rules

- **Tests run the real code.** Fake the network, the clock and the disk, never the function the test is named after. A test that stubs the unit it covers, or reads source text instead of running it, is a real finding, not a skip. (#269, #275)
- **Anything of unknown size has a bound.** A log, a response body, a file: stream it or cap it, or the PR says why not. An unbounded read is a real finding. (#269, #275)
- **A changed rule leaves no old copy behind.** When the diff changes how something works, check AGENTS.md, HARE.md and the docs for lines that still say the old thing. Agents read those files, so a contradiction is a real finding. (#269)
- **One read path.** Every read goes through `unlocker.fetch`; do not suggest routing reads by channel.
- **Doctor only reads.** Do not suggest wiring config keys that nothing uses.
- **Honest over clever.** searchts is a keyless reader: prefer saying plainly that a page could not be read over a feature that guesses.
- **CI scripts may log with `print`.** P4.6 (progress on stderr, never stdout) protects searchts's CLI and MCP output. Scripts under `scripts/` and `.github/` write to the Actions log, where stdout is only a log, and they do not import searchts. A `print` there is not a finding. (#233, #268)
- **What counts as real here.** On top of the general list in Hare's prompt: progress or ticks on stdout (P4.6: stdout is the CLI's and the MCP server's output), anything that breaks the MCP protocol, and a diff that misses PLAN.md's stated intent for the item it names.
- **Line length is the formatter's, not a finding.** The limit is `line-length = 100` in pyproject.toml, not 80, and ruff does not enforce it (E501 is off), so do not flag a long line. A line that is hard to read because of what it does is a finding about what it does.

<!-- hare-ledger:rules -->
**What the owner said Hare missed (from the ledger, PLAN R2c).** Each line is the reason behind a low score, filed by `scripts/hare_ledger.py` from `/hare score`. Hare reads these as rules for the next note. Each ledger run rewrites this block; to retire a line, delete its score comment or edit the score to 3 or higher.

- (none yet: a `/hare score 1..5 <why>` of 2 or less with a reason lands here)
<!-- /hare-ledger:rules -->
