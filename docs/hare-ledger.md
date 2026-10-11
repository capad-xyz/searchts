# Hare ledger

Every finding Hare posted here, what became of it, and what the owner said. Built by `scripts/hare_ledger.py` from the notes, the Since lines, resolved threads, `/hare score` and `/hare fate` comments; a PR closed unmerged drops its open findings. PLAN R2b.

Built 2026-10-11. 214 PRs, 293 notes, 41 real and 181 skip findings, 23 notes cut at the budget, 147 runs where no hop answered.

**Hit rate:** 13 of 41 real findings fixed or resolved (31%); 24 judged, 6 wrong, 2 wontfix, 1 dropped with a closed PR.
**Owner scores:** 45 given, average 3.67 of 5.

| Hop | Notes |
| --- | --- |
| `nous:poolside/laguna-s-2.1:free` | 106 |
| `openrouter:qwen/qwen3.8-27b:free` | 59 |
| `nous:meituan/longcat-2.5-preview:free` | 39 |
| `openrouter:nex-agi/nex-n2.5-pro:free` | 24 |
| `openrouter:poolside/laguna-s-2.1:free` | 18 |
| `groq:openai/gpt-oss-120b` | 15 |
| `openrouter:nvidia/nemotron-3.5-lightning:free` | 8 |
| `openrouter:stealth/space-bunny-alpha` | 7 |
| `gemini:gemini-3.1-flash-lite` | 4 |
| `openrouter:qwen/qwen3.8-27b:free · deep` | 3 |
| `nous:stealth/space-bunny-alpha` | 2 |
| `groq:openai/gpt-oss-120b · deep` | 1 |
| `nous:inclusionai/ling-3.0-flash-sante:free` | 1 |
| `nous:meituan/longcat-2.5-preview:free · deep` | 1 |
| `gemini:gemini-3.1-flash-lite · deep` | 1 |
| `gemini:gemini-3.5-flash` | 1 |

## By PR

| PR | Notes | Real | Skip | Fates of real | Scores |
| --- | --- | --- | --- | --- | --- |
| #361 | 1 | 0 | 0 |  |  |
| #359 | 12 | 6 | 6 | open 4, still applies 1, wrong 1 |  |
| #358 | 1 | 0 | 1 |  |  |
| #357 | 3 | 0 | 1 |  |  |
| #356 | 3 | 0 | 2 |  |  |
| #355 | 3 | 2 | 2 | open 2 |  |
| #354 | 1 | 0 | 4 |  |  |
| #353 | 1 | 0 | 1 |  |  |
| #351 | 3 | 0 | 2 |  |  |
| #350 | 1 | 0 | 2 |  |  |
| #349 | 9 | 8 | 16 | fixed 4, open 3, still applies 1 |  |
| #348 | 1 | 0 | 1 |  |  |
| #347 | 1 | 0 | 4 |  |  |
| #344 | 1 | 0 | 2 |  |  |
| #343 | 2 | 0 | 4 |  |  |
| #342 | 1 | 0 | 0 |  |  |
| #341 | 1 | 0 | 0 |  |  |
| #340 | 1 | 0 | 2 |  |  |
| #339 | 1 | 0 | 2 |  |  |
| #338 | 2 | 0 | 2 |  |  |
| #337 | 1 | 0 | 1 |  |  |
| #335 | 1 | 0 | 2 |  |  |
| #332 | 4 | 1 | 12 | open 1 |  |
| #331 | 3 | 0 | 3 |  |  |
| #330 | 3 | 0 | 2 |  | 4 (Caught a real defect I introduced, the missing newline at EOF, and named it precisely. Not 5: one pass. But the substance is right, and the two things it did not do matter as much as the one it did. I) |
| #329 | 2 | 0 | 1 |  | 4 (Correct read and correct verdict on a docs PR, and it picked the one real weakness: the doc cites line numbers it cannot verify. Not 5 because a plan doc whose citations have drifted is a plan doc tha) |
| #328 | 2 | 0 | 1 |  | 5 (Correct verdict, and it is the first hop answering under the Nous-first chain, so this is the first measured data point that the ordering change does what it was merged for. Not 4 because a comment wi) |
| #327 | 1 | 0 | 0 |  |  |
| #326 | 1 | 1 | 2 | open 1 |  |
| #325 | 2 | 0 | 1 |  |  |
| #324 | 3 | 0 | 0 |  | 2 (Held nothing, so it cost nothing, but it read an incremental diff as the whole PR again and returned prose where the prompt asks for JSON. The 2 is for the same reason as 321's: correct-by-accident is) |
| #323 | 1 | 0 | 0 |  |  |
| #322 | 0 | 0 | 0 |  |  |
| #321 | 2 | 1 | 2 | wrong 1 |  |
| #320 | 1 | 0 | 1 |  |  |
| #319 | 1 | 0 | 1 |  |  |
| #318 | 1 | 0 | 0 |  |  |
| #317 | 1 | 0 | 0 |  |  |
| #316 | 1 | 0 | 0 |  |  |
| #315 | 1 | 0 | 1 |  |  |
| #314 | 1 | 0 | 1 |  |  |
| #313 | 2 | 0 | 2 |  |  |
| #312 | 1 | 0 | 2 |  |  |
| #311 | 2 | 0 | 1 |  |  |
| #310 | 1 | 0 | 1 |  |  |
| #309 | 1 | 0 | 0 |  |  |
| #308 | 1 | 0 | 0 |  | 5 (caught the hole: a Hare Bot note posts as the owner, and the marker is the check. The test pins both the score and the fate.) |
| #307 | 2 | 0 | 1 |  | 4 (Ship was right. The line-length skip is not a finding under HARE.md.); 4 (Ship was right and the skip was a real wording miss. Not 5: it was a comment.) |
| #306 | 3 | 3 | 9 | fixed 1, open 1, wrong 1 | 3 (Ship on the class-token regex was right. Not 4: the skip tells us to switch back to \b, and a hyphen is a word boundary, so \bsidebar matches sidebar-right. That is the bug this PR removed.

/hare fat); 2 (Ship on the sidebar regex was already scored. This note holds the PR for the coverage carve-out and uninstall --browser. The carve-out arrived with main (#302). uninstall is #304. Neither is this diff) |
| #305 | 7 | 0 | 1 |  | 4 (Ship was right on a03dc7c. The flag, the filter, and the reset match the two red assertions from run 37394079827. Not 5: no miss to catch.) |
| #304 | 2 | 1 | 2 | open 1 | 4 (caught the orphaned help line that left --keep-config as a syntax error, and the later skip on flag order was right to leave. Not 5: the first note did not name the IndentationError, only the missing ) |
| #303 | 4 | 3 | 5 | fixed 1, open 1, wrong 1 | 4 (caught the duplicate --scrub help, which crashes argparse at startup, and the one-line fix was right. Not 5: the note did not say the JSON test would still fail.); 3 (the double-fetch and the guard move are what the diff does. Not 4: the pages key is already the whole-dict assertion in test_read_command_json, so the skip on tests/test_cli.py:212 is a miss.

/hare f); 2 (the double-fetch note was already scored. This note holds the PR for uninstall --browser and the Jina global. Neither file is in this diff. They are on main, from #304 and #305, because the branch mer) |
| #302 | 2 | 0 | 1 |  | 4 (Ship was right and the docstring skip was a real mismatch, not noise. Not 5: it was a comment, not a behavior miss.) |
| #301 | 1 | 0 | 1 |  | 3 (Ship was right and the bad permission key was named. The skip was wrong: a failed eval already stops the step before the copy, so the copy is not fragile.) |
| #300 | 1 | 0 | 0 |  | 4 (Ship was right: the pin, the default, and both tests were checked against each other. Not 5: there was no miss to catch.) |
| #299 | 4 | 0 | 1 |  | 2 (the same model asked to shorten this comment and then to lengthen it; the cause belongs in the comment, the flip does not) |
| #298 | 1 | 0 | 1 |  | 4 (right Ship on a docs log; it says it is not a review and does not touch the ledger) |
| #297 | 2 | 0 | 1 |  | 4 (right Ship on a docs sync; the one skip was a real run-on and the budgets matched the script) |
| #296 | 1 | 0 | 0 |  | 4 (right Ship on a docs-only fold) |
| #295 | 1 | 0 | 0 |  | 4 (right Ship; it checked that the test pins the fallback so a later edit cannot drop it) |
| #294 | 2 | 0 | 1 |  | 4 (caught the stale 'this file' in the moved text, the class of slip the no-old-copy rule is about; missed 'the block below' two lines down) |
| #293 | 1 | 0 | 1 |  | 4 (right Ship, and it checked that searchts's bar moved to HARE.md rather than vanished) |
| #292 | 1 | 0 | 1 |  | 4 (right Ship on a small additive change; it checked the line only appears when the graph was sent) |
| #291 | 2 | 0 | 1 |  | 4 (right Ship, and its one skip (case_root was faked) was real; the follow-up test runs it against a real repo) |
| #290 | 1 | 0 | 1 |  | 4 (right Ship; it checked the four files agree and that the chain keeps five providers) |
| #289 | 1 | 0 | 0 |  | 4 (right Ship on a one-line rule; it checked the rule does not contradict the others) |
| #288 | 1 | 0 | 2 |  | 4 (right Ship on a timing change, and it checked that the reserve applies only with a fallback ahead; the two nits are the recurring line-length one) |
| #287 | 4 | 0 | 1 |  | 3 (the first note said Ship on a head with three real issues CodeRabbit found (caps kept walk order, not rank; declarations with modifiers were not read; truncated hunks were skipped); the deep pass on t) |
| #286 | 1 | 0 | 2 |  | 4 (right Ship; both nits are accurate (PerDay is redundant under re.I, the last raise is unreachable)) |
| #285 | 1 | 0 | 1 |  | 4 (right Ship on a docs-only fold; nothing in it to find) |
| #284 | 1 | 0 | 0 |  | 4 (right Ship on an engine change; it checked the repair, the near-line dedupe and the all-die path) |
| #283 | 2 | 0 | 2 |  | 4 (right Ship twice, and the second pass, asked by /hare, came back with the quote line and the 🐇 removed; only a style nit) |
| #282 | 2 | 0 | 1 |  | 2 (said Ship while a comment Hare itself posts would start a run in the command's own concurrency group and cancel it; check what every new side effect triggers) |
| #281 | 2 | 0 | 5 |  | 4 (right Ship; its skips were useful, and two of them were fixed in the next commit) |
| #280 | 1 | 0 | 0 |  | 4 (right Ship; it checked every place that names the chain and noticed Zen's separate slug was left on purpose) |
| #279 | 1 | 0 | 0 |  | 3 (right Ship, but it did not check the claim the rule rests on, that the scripts import nothing from searchts) |
| #278 | 1 | 0 | 0 |  | 4 (right Ship on a docs change; it checked the new rules against AGENTS.md before passing them) |
| #277 | 1 | 0 | 0 |  | 4 (right Ship on a small fix it could check: it named the boundary (only issue_comment carries a command) and saw the test drives the real function) |
| #276 | 1 | 0 | 0 |  | 4 (right Ship on a data-only PR; it checked that the three log formats agree) |
| #275 | 4 | 1 | 1 | fixed 1 | 3 (missed the unbounded readline that Hare Bot caught; its real finding named the wrong failure but led to a better fix; the deep pass was right and added nothing new) |
| #274 | 2 | 1 | 0 | fixed 1 | 4 (caught a real bug, the one-page review read that could miss its own note, with a clear fix; Ship after the fix was right) |
| #273 | 1 | 0 | 0 |  |  |
| #272 | 1 | 0 | 0 |  |  |
| #271 | 2 | 0 | 2 |  |  |
| #270 | 2 | 3 | 1 | open 3 |  |
| #269 | 2 | 1 | 2 | fixed 1 | 5; 2 (missed an unbounded read of a whole job log and AGENTS.md lines contradicting the diff; called a test that checks source text instead of behaviour a skip, when it is real) |
| #268 | 2 | 2 | 0 | wontfix 1, wrong 1 |  |
| #267 | 2 | 0 | 0 |  |  |
| #266 | 1 | 0 | 1 |  |  |
| #265 | 1 | 0 | 1 |  |  |
| #264 | 1 | 0 | 1 |  |  |
| #263 | 1 | 0 | 0 |  |  |
| #262 | 2 | 1 | 1 | fixed 1 |  |
| #261 | 1 | 0 | 0 |  |  |
| #260 | 1 | 0 | 0 |  |  |
| #259 | 1 | 0 | 0 |  |  |
| #258 | 2 | 1 | 3 | wrong 1 |  |
| #257 | 1 | 0 | 1 |  |  |
| #256 | 1 | 0 | 0 |  |  |
| #255 | 1 | 0 | 1 |  |  |
| #254 | 3 | 0 | 4 |  |  |
| #253 | 1 | 0 | 1 |  |  |
| #252 | 1 | 0 | 0 |  |  |
| #251 | 1 | 0 | 0 |  |  |
| #250 | 1 | 0 | 1 |  |  |
| #249 | 1 | 0 | 0 |  |  |
| #248 | 2 | 1 | 1 | fixed 1 |  |
| #247 | 1 | 1 | 0 | resolved 1 |  |
| #246 | 1 | 0 | 2 |  |  |
| #245 | 1 | 1 | 0 | resolved 1 |  |
| #244 | 2 | 0 | 2 |  |  |
| #240 | 1 | 0 | 1 |  |  |
| #239 | 1 | 0 | 1 |  |  |
| #238 | 1 | 0 | 1 |  |  |
| #237 | 1 | 1 | 2 | dropped 1 |  |
| #236 | 3 | 0 | 3 |  |  |
| #235 | 2 | 0 | 4 |  |  |
| #234 | 1 | 0 | 2 |  |  |
| #233 | 1 | 1 | 0 | wontfix 1 |  |
| #232 | 30 | 0 | 6 |  |  |
| #231 | 0 | 0 | 0 |  |  |
| #230 | 1 | 0 | 2 |  |  |
| #229 | 0 | 0 | 0 |  |  |
| #228 | 0 | 0 | 0 |  |  |
| #227 | 0 | 0 | 0 |  |  |
| #226 | 0 | 0 | 0 |  |  |
| #225 | 0 | 0 | 0 |  |  |
| #224 | 1 | 0 | 0 |  |  |
| #223 | 1 | 0 | 0 |  |  |
| #222 | 0 | 0 | 0 |  |  |
| #221 | 2 | 0 | 0 |  |  |
| #220 | 1 | 0 | 0 |  |  |
| #219 | 0 | 0 | 0 |  |  |
| #218 | 0 | 0 | 0 |  |  |
| #217 | 0 | 0 | 0 |  |  |
| #216 | 1 | 0 | 0 |  |  |
| #215 | 0 | 0 | 0 |  |  |
| #214 | 1 | 0 | 0 |  |  |
| #213 | 0 | 0 | 0 |  |  |
| #212 | 0 | 0 | 0 |  |  |
| #211 | 0 | 0 | 0 |  |  |
| #210 | 0 | 0 | 0 |  |  |
| #209 | 1 | 0 | 0 |  |  |
| #208 | 0 | 0 | 0 |  |  |
| #207 | 0 | 0 | 0 |  |  |
| #206 | 0 | 0 | 0 |  |  |
| #205 | 0 | 0 | 0 |  |  |
| #204 | 0 | 0 | 0 |  |  |
| #203 | 0 | 0 | 0 |  |  |
| #202 | 0 | 0 | 0 |  |  |
| #201 | 1 | 0 | 0 |  |  |
| #199 | 1 | 0 | 0 |  |  |
| #198 | 8 | 0 | 0 |  |  |
| #196 | 0 | 0 | 0 |  |  |
| #195 | 0 | 0 | 0 |  |  |
| #194 | 0 | 0 | 0 |  |  |
| #193 | 2 | 0 | 0 |  |  |
| #192 | 0 | 0 | 0 |  |  |
| #191 | 0 | 0 | 0 |  |  |
| #189 | 0 | 0 | 0 |  |  |
| #188 | 0 | 0 | 0 |  |  |
| #185 | 1 | 0 | 0 |  |  |
| #184 | 1 | 0 | 0 |  |  |
| #183 | 0 | 0 | 0 |  |  |
| #182 | 0 | 0 | 0 |  |  |
| #181 | 1 | 0 | 0 |  |  |
| #180 | 1 | 0 | 0 |  |  |
| #179 | 0 | 0 | 0 |  |  |
| #177 | 0 | 0 | 0 |  |  |
| #176 | 0 | 0 | 0 |  |  |
| #175 | 1 | 0 | 0 |  |  |
| #174 | 6 | 0 | 0 |  |  |
| #173 | 2 | 0 | 0 |  |  |
| #172 | 1 | 0 | 0 |  |  |
| #171 | 1 | 0 | 0 |  |  |
| #170 | 1 | 0 | 0 |  |  |
| #169 | 2 | 0 | 0 |  |  |
| #168 | 1 | 0 | 0 |  |  |
| #167 | 0 | 0 | 0 |  |  |
| #166 | 1 | 0 | 0 |  |  |
| #165 | 2 | 0 | 0 |  |  |
| #164 | 0 | 0 | 0 |  |  |
| #163 | 0 | 0 | 0 |  |  |
| #162 | 0 | 0 | 0 |  |  |
| #161 | 0 | 0 | 0 |  |  |
| #160 | 1 | 0 | 0 |  |  |
| #159 | 0 | 0 | 0 |  |  |
| #158 | 0 | 0 | 0 |  |  |
| #156 | 6 | 0 | 0 |  |  |
| #155 | 0 | 0 | 0 |  |  |
| #154 | 0 | 0 | 0 |  |  |
| #153 | 0 | 0 | 0 |  |  |
| #151 | 0 | 0 | 0 |  |  |
| #150 | 0 | 0 | 0 |  |  |
| #149 | 0 | 0 | 0 |  |  |
| #148 | 0 | 0 | 0 |  |  |
| #147 | 0 | 0 | 0 |  |  |
| #146 | 0 | 0 | 0 |  |  |
| #145 | 0 | 0 | 0 |  |  |
| #144 | 0 | 0 | 0 |  |  |
| #143 | 0 | 0 | 0 |  |  |
| #142 | 0 | 0 | 0 |  |  |
| #141 | 1 | 0 | 0 |  |  |
| #140 | 0 | 0 | 0 |  |  |
| #139 | 0 | 0 | 0 |  |  |
| #138 | 0 | 0 | 0 |  |  |
| #137 | 0 | 0 | 0 |  |  |
| #136 | 0 | 0 | 0 |  |  |
| #134 | 2 | 0 | 0 |  |  |
| #128 | 0 | 0 | 0 |  |  |
| #126 | 1 | 0 | 0 |  |  |
| #125 | 1 | 0 | 0 |  |  |
| #124 | 1 | 0 | 0 |  |  |
| #38 | 1 | 0 | 0 |  |  |

## Owner feedback

- #330: 4/5, Caught a real defect I introduced, the missing newline at EOF, and named it precisely. Not 5: one pass. But the substance is right, and the two things it did not do matter as much as the one it did. I (capad-xyz, 2026-10-07)
- #329: 4/5, Correct read and correct verdict on a docs PR, and it picked the one real weakness: the doc cites line numbers it cannot verify. Not 5 because a plan doc whose citations have drifted is a plan doc tha (capad-xyz, 2026-10-07)
- #324: 2/5, Held nothing, so it cost nothing, but it read an incremental diff as the whole PR again and returned prose where the prompt asks for JSON. The 2 is for the same reason as 321's: correct-by-accident is (capad-xyz, 2026-10-07)
- #328: 5/5, Correct verdict, and it is the first hop answering under the Nous-first chain, so this is the first measured data point that the ordering change does what it was merged for. Not 4 because a comment wi (capad-xyz, 2026-10-07)
- #306: 2/5, Ship on the sidebar regex was already scored. This note holds the PR for the coverage carve-out and uninstall --browser. The carve-out arrived with main (#302). uninstall is #304. Neither is this diff (capad-xyz, 2026-10-06)
- #303: 2/5, the double-fetch note was already scored. This note holds the PR for uninstall --browser and the Jina global. Neither file is in this diff. They are on main, from #304 and #305, because the branch mer (capad-xyz, 2026-10-06)
- #306: 3/5, Ship on the class-token regex was right. Not 4: the skip tells us to switch back to \b, and a hyphen is a word boundary, so \bsidebar matches sidebar-right. That is the bug this PR removed.

/hare fat (capad-xyz, 2026-10-06)
- #303: 3/5, the double-fetch and the guard move are what the diff does. Not 4: the pages key is already the whole-dict assertion in test_read_command_json, so the skip on tests/test_cli.py:212 is a miss.

/hare f (capad-xyz, 2026-10-06)
- #305: 4/5, Ship was right on a03dc7c. The flag, the filter, and the reset match the two red assertions from run 37394079827. Not 5: no miss to catch. (capad-xyz, 2026-10-06)
- #307: 4/5, Ship was right and the skip was a real wording miss. Not 5: it was a comment. (capad-xyz, 2026-10-06)
- #308: 5/5, caught the hole: a Hare Bot note posts as the owner, and the marker is the check. The test pins both the score and the fate. (capad-xyz, 2026-10-06)
- #307: 4/5, Ship was right. The line-length skip is not a finding under HARE.md. (capad-xyz, 2026-10-06)
- #304: 4/5, caught the orphaned help line that left --keep-config as a syntax error, and the later skip on flag order was right to leave. Not 5: the first note did not name the IndentationError, only the missing  (capad-xyz, 2026-10-05)
- #303: 4/5, caught the duplicate --scrub help, which crashes argparse at startup, and the one-line fix was right. Not 5: the note did not say the JSON test would still fail. (capad-xyz, 2026-10-05)
- #302: 4/5, Ship was right and the docstring skip was a real mismatch, not noise. Not 5: it was a comment, not a behavior miss. (capad-xyz, 2026-10-05)
- #300: 4/5, Ship was right: the pin, the default, and both tests were checked against each other. Not 5: there was no miss to catch. (capad-xyz, 2026-10-05)
- #301: 3/5, Ship was right and the bad permission key was named. The skip was wrong: a failed eval already stops the step before the copy, so the copy is not fragile. (capad-xyz, 2026-10-05)
- #299: 2/5, the same model asked to shorten this comment and then to lengthen it; the cause belongs in the comment, the flip does not (capad-xyz, 2026-10-05)
- #298: 4/5, right Ship on a docs log; it says it is not a review and does not touch the ledger (capad-xyz, 2026-10-05)
- #297: 4/5, right Ship on a docs sync; the one skip was a real run-on and the budgets matched the script (capad-xyz, 2026-10-05)
- #296: 4/5, right Ship on a docs-only fold (capad-xyz, 2026-10-05)
- #295: 4/5, right Ship; it checked that the test pins the fallback so a later edit cannot drop it (capad-xyz, 2026-10-05)
- #294: 4/5, caught the stale 'this file' in the moved text, the class of slip the no-old-copy rule is about; missed 'the block below' two lines down (capad-xyz, 2026-10-05)
- #293: 4/5, right Ship, and it checked that searchts's bar moved to HARE.md rather than vanished (capad-xyz, 2026-10-05)
- #292: 4/5, right Ship on a small additive change; it checked the line only appears when the graph was sent (capad-xyz, 2026-10-05)
- #291: 4/5, right Ship, and its one skip (case_root was faked) was real; the follow-up test runs it against a real repo (capad-xyz, 2026-10-05)
- #287: 3/5, the first note said Ship on a head with three real issues CodeRabbit found (caps kept walk order, not rank; declarations with modifiers were not read; truncated hunks were skipped); the deep pass on t (capad-xyz, 2026-10-05)
- #290: 4/5, right Ship; it checked the four files agree and that the chain keeps five providers (capad-xyz, 2026-10-05)
- #289: 4/5, right Ship on a one-line rule; it checked the rule does not contradict the others (capad-xyz, 2026-10-05)
- #288: 4/5, right Ship on a timing change, and it checked that the reserve applies only with a fallback ahead; the two nits are the recurring line-length one (capad-xyz, 2026-10-05)
- #286: 4/5, right Ship; both nits are accurate (PerDay is redundant under re.I, the last raise is unreachable) (capad-xyz, 2026-10-05)
- #285: 4/5, right Ship on a docs-only fold; nothing in it to find (capad-xyz, 2026-10-05)
- #284: 4/5, right Ship on an engine change; it checked the repair, the near-line dedupe and the all-die path (capad-xyz, 2026-10-05)
- #283: 4/5, right Ship twice, and the second pass, asked by /hare, came back with the quote line and the 🐇 removed; only a style nit (capad-xyz, 2026-10-05)
- #282: 2/5, said Ship while a comment Hare itself posts would start a run in the command's own concurrency group and cancel it; check what every new side effect triggers (capad-xyz, 2026-10-05)
- #281: 4/5, right Ship; its skips were useful, and two of them were fixed in the next commit (capad-xyz, 2026-10-05)
- #280: 4/5, right Ship; it checked every place that names the chain and noticed Zen's separate slug was left on purpose (capad-xyz, 2026-10-05)
- #279: 3/5, right Ship, but it did not check the claim the rule rests on, that the scripts import nothing from searchts (capad-xyz, 2026-10-04)
- #276: 4/5, right Ship on a data-only PR; it checked that the three log formats agree (capad-xyz, 2026-10-04)
- #278: 4/5, right Ship on a docs change; it checked the new rules against AGENTS.md before passing them (capad-xyz, 2026-10-04)
- #275: 3/5, missed the unbounded readline that Hare Bot caught; its real finding named the wrong failure but led to a better fix; the deep pass was right and added nothing new (capad-xyz, 2026-10-04)
- #277: 4/5, right Ship on a small fix it could check: it named the boundary (only issue_comment carries a command) and saw the test drives the real function (capad-xyz, 2026-10-04)
- #274: 4/5, caught a real bug, the one-page review read that could miss its own note, with a clear fix; Ship after the fix was right (capad-xyz, 2026-10-04)
- #269: 2/5, missed an unbounded read of a whole job log and AGENTS.md lines contradicting the diff; called a test that checks source text instead of behaviour a skip, when it is real (capad-xyz, 2026-10-04)
- #269: 5/5 (capad-xyz, 2026-10-04)
