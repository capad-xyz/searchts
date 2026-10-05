# How Hare works

Hare reviews this repo's pull requests with free models on the owner's own keys. Its rules for this repo are in [HARE.md](../HARE.md), which Hare reads before every note; this page is for people and is not sent to the model.

1. A PR opens or gets a push, or someone with write access comments `/hare`.
   A command gets 🐇 at once, or 🐢 for `/hare think`; the note quotes the request
   and the sign is removed when it lands. Re-run on Hare's check also reviews
   again, and the note says who pressed it.
   The Action `hare / r1` runs `scripts/hare_r1.py` from main. A fixed list of
   free model hops (PLAN R1c) is tried in order; the first that answers writes
   the review. If none answers, Hare posts a needed comment instead.
2. Hare reads AGENTS.md, [HARE.md](../HARE.md), and what the ledger knows about the files in
   the diff. It also builds a codebase graph (`scripts/hare_graph.py`): names and
   files the diff changes, and where the trusted base checkout still uses them.
   Text only, never run. Ranked code, then workflows and config, then docs.
   Each hop gets its own budget (Groq 4k characters, Gemini 40k, the rest 20k);
   a small workflow that names a changed file goes in whole. The note says how
   much of that graph the model saw. Then one review: summary, CI, intent, a verdict (Ship, Hold, or Wait
   while CI runs, from CI and the real findings, then the model's case), findings with bubbles
   on the lines (a one-click fix where the fix is small), a checks fold, and a
   fold on how to answer. A later push gets a Since section on each old finding.
3. The owner answers with PR comments: `/hare score 1..5 <why>` on a note,
   `/hare fate <path:line> fixed|wrong|wontfix <why>` on one finding. Hare
   records both and posts nothing.
4. Every Sunday the ledger run rebuilds `docs/hare-ledger.md` from the notes,
   Since lines, resolved threads and those comments, rewrites the learned block in HARE.md
   from low scores, opens a PR, asks Hare to review it, and merges it unless
   Hare finds a real problem.
