# Hare Bot review log, 2026-10-04

Intent: So the owner can see what each Hare Bot pass found, what it cost, and which GitHub review it is. A record of those passes, not a new review.

Times are Asia/Calcutta. Token figures are named review-input characters divided by 4. There is no meter. A blank estimate means the inputs were not counted. Do not treat output length as input.

## Who posted

- Reviewer: Hare Bot. Not the GitHub App Hare (`searchts-hare`, `@hare`, `/hare`).
- Posts as `capad-xyz` through the `cursor-github` connector. Event is COMMENT.
- Review marker: `<!-- harebot:review head=<full 40-char SHA> -->`
- Inline marker: `<!-- harebot:bubble -->`
- Models cell on GitHub: `Hare Bot (Grok Bot) · purpose: <what that pass did> · Grok`
- Model slug: none was returned. The cell says Grok. Do not invent a slug.
- Pass effort requested for these reviews: high.
- The app's own marker is `<!-- searchts-r1-review -->`. On #244 it reported `gemini:gemini-3.1-flash-lite`, 11,670 prompt + 183 answer tokens, 17 s. That line is the app, not Hare Bot.

## Rows

### #235 ci(hare): a hop answers, or says why it did not

- Review: https://github.com/capad-xyz/searchts/pull/235#pullrequestreview-5402501651
- Head: `a747bad8d161ac4107b54023b174aa144a447970`
- State: merged 2026-10-03T21:11:30Z, reviewed while open
- Clock: 2026-10-04 01:31 to 2026-10-04 01:32 (1 min)
- Summary: Timeout, JSON brace walk, and named nags so a hop answers or says why.
- CI: green on a747bad: test, lint, typecheck, mcp2-compat, version-sync, r1. test-full and wheel-gate skipped.
- Tests: /tmp/hare-venv/bin/python -m pytest -q tests/test_hare_r1.py → 66 passed, exit 0
- Owner: eye ball
- Findings:
- real `scripts/hare_r1.py:527` Fix yes. reasoning-knob retry can raise bare HTTPError and hide the cause
- skip `scripts/hare_r1.py:48` Fix later. Nous pinned to effort=none (fast pass as default)
- skip `scripts/hare_r1.py:983` Fix yes. stale comment says no reasoning control
- Characters counted: diff 18611, title 47, body 3085, commit_message 862, conversation_hare 766, conversation_coderabbit_approx 2500, ci_text_approx 1500
- Token estimate: about 6800 from about 27000 characters. Rounded from the named inputs. Unused commits page left out.

### #236 chore(hare): refresh the free catalogs against what answers

- Review: https://github.com/capad-xyz/searchts/pull/236#pullrequestreview-5402506750
- Head: `805b81a027d4b949aa6cc076dd0d5978c4b6ab92`
- State: merged 2026-10-03T21:13:31Z, reviewed while open
- Clock: 2026-10-04 01:31 to 2026-10-04 01:32:57 (2 min)
- Summary: Catalog refresh. OpenRouter leads with the hop that answered, Groq gains a second slug, Zen drops two TUI-only ids.
- CI: green on 805b81a: lint, mcp2-compat, version-sync, typecheck, test, r1. test-full and wheel-gate skipped.
- Tests: pytest -q tests/test_hare_r1.py → 56 passed, exit 0
- Owner: eye ball
- Inlines:
  - https://github.com/capad-xyz/searchts/pull/236#discussion_r4174637455
  - https://github.com/capad-xyz/searchts/pull/236#discussion_r4174637466
- Findings:
- real `scripts/hare_r1.py:81` Fix yes. note says Nous sends effort none, but build_provider_chain still passes Nous {} so a dead hop waits 60s
- skip `.github/workflows/hare.yml:101` Fix later. OpenRouter list is a ${{ }} fallback and the test skips any value containing ${{ }}
- Characters counted: diff 5884, title 59, body 2186, commit_message 731, review_body 1121, issue_comment_body 2650, source_slices 32121
- Token estimate: about 11000 from about 45000 characters. Tighter sum of bodies and slices. Envelope upper bound about 26,000 if overlap is counted.

### #237 fix(hare): make the reasoning hop answer, and stop losing the answer

- Review: https://github.com/capad-xyz/searchts/pull/237#pullrequestreview-5402622302
- Head: `bbce9850b0ac124c87884fdfd78529ab4079be3b`
- State: closed not merged 2026-10-03T20:53:27Z
- Clock: 2026-10-04 01:57:27 to 2026-10-04 02:05:39 (8 min)
- Summary: Nous effort=none measurement is wired in, but the first hop (Groq openai/gpt-oss-120b) is sent a nested reasoning object Groq does not use.
- CI: bbce985: lint, test, typecheck, mcp2-compat, version-sync, r1, copilot success. test-full and wheel-gate skipped. mergeable_state unstable at submit.
- Tests: pytest never started. shell failed to spawn. no exit code.
- Owner: eye ball
- Inlines:
  - https://github.com/capad-xyz/searchts/pull/237#discussion_r4174749545
  - https://github.com/capad-xyz/searchts/pull/237#discussion_r4174749550
  - https://github.com/capad-xyz/searchts/pull/237#discussion_r4174749551
- Findings:
- real `scripts/hare_r1.py:977` Fix yes. Groq knob is top-level reasoning_effort; nested object is ignored or a 400. none is Qwen-only.
- real `scripts/hare_r1.py:295` Fix yes. fence regex matches backslashes, not markdown fences. already raised, no new bubble
- skip `docs/hare-thinking-ab.md:8` Fix later. Same PRs is false: only #221 and #224 are in both tables
- skip `scripts/hare_r1.py:544` Fix later. urlopen timeouts arrive as URLError, so TimeoutError handler never runs
- skip `scripts/hare_local.py:81` Fix later. local runner cannot select Groq or Gemini. already raised
- skip `tests/test_hare_r1.py:784` Fix later. hop_override test only checks the parameter name. already raised
- skip `scripts/hare_local.py:7` Fix later. doc shows --skip-checks, which is not a flag. already raised
- skip `scripts/hare_r1.py:232` Fix later. docstring has a real tab and form feed. already raised
- Characters counted: title 70
- Token estimate: not counted. Shell died before wc. Only the title length is known. No token estimate.

### #242 ci(hare): answer budget 32000, the owner's call

- Review: https://github.com/capad-xyz/searchts/pull/242#pullrequestreview-5403009947
- Head: `21ffefbfdae1792e64dec66cdd81ce4ed175d6b4`
- State: merged 2026-10-03T21:31:08Z before this review
- Clock: 2026-10-04 03:41:44 to 2026-10-04 03:44:40 (2.9 min)
- Summary: Default answer budget goes from 16000 to 32000, and the two test pins follow.
- CI: green on 21ffefb: test, lint, version-sync, mcp2-compat, typecheck, r1.
- Tests: /tmp/hare-venv/bin/pytest -q tests/test_hare_r1.py → 68 passed, exit 0
- Owner: no widget. already merged, no findings
- Findings:
No line findings.
- Characters counted: diff 1722, title 47, body 515, commit_message 280, reviews 0, threads 0, issue_comments 2650, ci_text 330, source_slices 32433
- Token estimate: about 9500 from about 38000 characters. Source slices are most of it and overlap the small diff.

### #241 docs(plan): fold 2026-10-04: Hare answers, thinking off by default, deep on request

- Review: https://github.com/capad-xyz/searchts/pull/241#pullrequestreview-5403014502
- Head: `47174a59a61aaa1650972384c9c5384cf9c8dd94`
- State: merged 2026-10-03T21:17:53Z before this review
- Clock: 2026-10-04 03:41:40 to 2026-10-04 03:45:25 (3.75 min)
- Summary: Docs fold of the live chain, thinking-off default, and cadence. AGENTS trigger line still describes the old chain.
- CI: green on 47174a5
- Tests: docs-only. no suite
- Owner: widget skipped
- Inlines:
  - https://github.com/capad-xyz/searchts/pull/241#discussion_r4175085020
  - https://github.com/capad-xyz/searchts/pull/241#discussion_r4175085023
- Findings:
- real `AGENTS.md:45` Fix later. trigger still says OpenRouter is Laguna / Qwen. fold chain is Qwen, Inkling, Gemma, Laguna last. line not in the diff, no bubble
- skip `PLAN.md:260` Fix later. 6-of-6 empty table is the 32000-token runs only
- skip `PLAN.md:259` Fix later. Space Bunny left OpenRouter 2026-10-05 is past tense for a date still ahead of the commit
- Characters counted: diff 14788, title 83, body 1109, commits 435, issue_comments 2650, ci_text 310, source_slices 39589
- Token estimate: about 15000 from about 59000 characters. Slices are most of it and overlap the diff.

### #243 ci(hare): start at once, size the spend to the diff, print what it cost

- Review: https://github.com/capad-xyz/searchts/pull/243#pullrequestreview-5403015854
- Head: `63efc15c39dad2142e7b88bd0a0085c25532cdce`
- State: merged 2026-10-03T21:41:17Z before this review
- Clock: 2026-10-04 03:41:49 to 2026-10-04 03:45:37 (3.8 min)
- Summary: Hop starts on the push, a diff over 1000 changed lines gets twice the call and hop time, and the fold prints what the winning call spent.
- CI: green on 63efc15
- Tests: pytest -q tests/test_hare_r1.py → 72 passed, exit 0
- Owner: no widget. skip only, already merged
- Findings:
- skip `scripts/hare_r1.py:743` Fix later. big-diff timeout waits 600s but the short line still says 300s. line not in the diff, no bubble
- Characters counted: diff 14647, title 71, body 1855, commits 692, reviews 0, threads 0, issue_comments 2651, ci_text 319, source_slices 46338
- Token estimate: about 17000 from about 67000 characters. Slices are most of it and overlap the diff.

### #244 ci(hare): near the limit, wrap up instead of throwing the answer away

- Review: https://github.com/capad-xyz/searchts/pull/244#pullrequestreview-5403024630
- Head: `d25ba95ccd06e2d8034c6a0fc5088debc7267715`
- State: merged 2026-10-03T22:09:40Z before this review. squash 7291fa70, same tree
- Clock: 2026-10-04 03:41:56 to 2026-10-04 03:47:01 (5.1 min)
- Summary: A cut answer is kept and finished, except the close step can still drop it.
- CI: green on d25ba95
- Tests: pytest -q tests/test_hare_r1.py → 79 passed, exit 0
- Owner: widget skipped
- Inlines:
  - https://github.com/capad-xyz/searchts/pull/244#discussion_r4175092666
  - https://github.com/capad-xyz/searchts/pull/244#discussion_r4175092668
- Findings:
- real `scripts/hare_r1.py:612` Fix yes. odd raw quote count treated as an open string, so one escaped quote makes repair_json append a quote and the fallback stops
- real `scripts/hare_r1.py:840` Fix yes. a continuation that starts with { replaces the partial, and an 800-token restart cannot hold the findings just kept
- Characters counted: diff 22970, title 69, body 2112, commit_messages 2967, review_body 1008, thread_body 238, issue_comment_body 2650, ci_text 302, source_slices 27195
- Token estimate: about 15000 from about 60000 characters. Slices overlap the diff.

### #246 ci(hare): the findings ledger, and /hare score

- Review: https://github.com/capad-xyz/searchts/pull/246#pullrequestreview-5403145293
- Head: `932f5b88c302a60682b970b8606bad85347a09e4`
- State: merged 2026-10-03T22:29:25Z before this review
- Clock: 2026-10-04 04:00:41 to 2026-10-04 04:03:59 (3.3 min)
- Summary: Ledger is the right place for notes, fates, and scores, but a resolved thread applies to every open finding on that path, and the hop table only parses the new Models row.
- CI: green on 932f5b8
- Tests: pytest -q tests/test_hare_ledger.py tests/test_hare_r1.py → 86 passed, exit 0
- Owner: widget skipped
- Inlines:
  - https://github.com/capad-xyz/searchts/pull/246#discussion_r4175189560
  - https://github.com/capad-xyz/searchts/pull/246#discussion_r4175189567
  - https://github.com/capad-xyz/searchts/pull/246#discussion_r4175189571
- Findings:
- real `scripts/hare_ledger.py:81` Fix yes. resolved threads keyed by path only, so one resolved thread marks every open finding on that file resolved
- real `scripts/hare_ledger.py:46` Fix yes. hop parsing only matches a backticked Models row, so 55 of 72 older notes never get a hop
- skip `.github/workflows/hare-ledger.yml:45` Fix later. gh pr create || echo turns every create failure into a green step after the force-push
- Characters counted: diff 58501, title 46, body 2315, commit_message 768, reviews 1180, threads 332, issue_comments 2650, ci_text 382, source_slices 33320
- Token estimate: about 25000 from about 99000 characters. Commit payload that repeated the patches was not added on top. Slices overlap the diff.

### #245 ci(hare): repair walks strings, a restart never shrinks the review

- Review: https://github.com/capad-xyz/searchts/pull/245#pullrequestreview-5403161779
- Head: `944ef4d77958922a11304a4e0501db5ffdc93730`
- State: merged 2026-10-03T22:23:33Z before this review
- Clock: 2026-10-04 04:00:49 to 2026-10-04 04:06:32 (5.7 min)
- Summary: Quote repair holds, and a bare { restart no longer shrinks the review. A restart that does not start on { still does.
- CI: green on 944ef4d
- Tests: pytest -q tests/test_hare_r1.py → 82 passed, exit 0
- Owner: widget skipped
- Inlines:
  - https://github.com/capad-xyz/searchts/pull/245#discussion_r4175198783
- Findings:
- real `scripts/hare_r1.py:840` Fix yes. a non-{ tail is still concatenated, and extract_json keeps the later shorter findings list
- Characters counted: diff 5950, title 66, body 1173, commit_message 657, reviews 1231, threads 246, issue_comments_approx 3200, ci_text 315, source_slices 34682
- Token estimate: about 12000 from about 48000 characters. CodeRabbit body about 3,200 was not remeasured from a saved payload. Slices overlap the diff.

### #249 docs(plan): fold 2026-10-04, second pass: cadence, wrap-up, ledger, HARE.md

- Review: https://github.com/capad-xyz/searchts/pull/249#pullrequestreview-5403208505
- Head: `0e2da56e2510f7fbb0a8f9e7a6b95732b187ed9e`
- State: merged 2026-10-03T22:39:43Z before this review
- Clock: 2026-10-04 04:10:34 to 2026-10-04 04:13:49 (3.25 min)
- Summary: Chain, cadence, wrap-up, ledger, and HARE.md match the code. The log calls both Flash-Lite cost lines streamed, and the 17s one was not.
- CI: green on 0e2da56
- Tests: docs-only. no suite
- Owner: widget skipped
- Inlines:
  - https://github.com/capad-xyz/searchts/pull/249#discussion_r4175222983
- Findings:
- real `PLAN.md:523` Fix yes. 17s Flash-Lite note on #244 ran from the base, which had no HARE_STREAM. The 18s deep run after merge did stream.
- Token estimate: not counted. Input was not counted. Do not use the output lengths as a token estimate.

### #248 ci(hare): low scores with a reason become rules in AGENTS.md

- Review: https://github.com/capad-xyz/searchts/pull/248#pullrequestreview-5403213965
- Head: `031b6ff2d0ed83090e44ddfabbe73c52accefbc9`
- State: merged 2026-10-03T22:37:45Z before this review
- Clock: 2026-10-04 04:10:29 to 2026-10-04 04:14:38 (4.2 min)
- Summary: Low-score reasons are filed into HARE.md, but the retire line and the AGENTS.md copy do not match the run that writes them.
- CI: green on 031b6ff
- Tests: pytest -q tests/test_hare_ledger.py → 6 passed, exit 0
- Owner: widget skipped
- Inlines:
  - https://github.com/capad-xyz/searchts/pull/248#discussion_r4175226349
- Findings:
- real `AGENTS.md:26` Fix yes. marked block still says the ledger rewrites it. workflow writes --rules HARE.md only. already in a thread
- real `HARE.md:9` Fix yes. resolve or edit does not drop a rule. scores are issue comments with no resolved state
- skip `.github/workflows/hare-ledger.yml:44` Fix later. title still says AGENTS.md. already in a thread
- Characters counted: diff 13838, title 60, body 1606, commits 1188, reviews 3231, threads 367, issue_comments 2650, ci_text 303, source_slices 24125
- Token estimate: about 12000 from about 47000 characters. Slices overlap the diff.
- Note: Rules come from /hare score text only. proposed_rules does not read finding fates, so the #246 path-keyed resolve bug is not baked into a rule.

### #247 ci(hare): Gemini is the fallback, not the default

- Review: https://github.com/capad-xyz/searchts/pull/247#pullrequestreview-5403210947
- Head: `2d26fa8574e096a4fe5b63e17bcd1151cce503b8`
- State: merged 2026-10-03T22:32:11Z before this review
- Clock: 2026-10-04 04:10:24 to 2026-10-04 04:14:12 (3.8 min)
- Summary: Hop list is Groq, OpenRouter, Nous, Gemini, Zen. The two order tests match that tuple.
- CI: green on 2d26fa8
- Tests: five named chain tests, 5 passed, exit 0
- Owner: no widget. skip only, already merged
- Findings:
- skip `scripts/hare_r1.py:1356` Fix later. build_provider_chain still calls the new order the PLAN.md R1c contract, and the docstring still walks Groq, Gemini, Nous, OpenRouter. already in a thread
- Characters counted: diff 2750, title 49, body 856, commits 361, reviews 1062, threads 210, issue_comments 2650, ci_text 310, source_slices 11641
- Token estimate: about 5000 from about 20000 characters. Counts are Unicode code points as reported.

## Earlier the same night, not remeasured

### #234 ci(hare): a reasoning hop now answers instead of dying silently

- Review: https://github.com/capad-xyz/searchts/pull/234#pullrequestreview-5401811255
- Overall note, edited in place: https://github.com/capad-xyz/searchts/pull/234#issuecomment-5971852491
- Head: `89d8d34973267b2feb85cd5407d50ad24866c097`
- State: reviewed while open. later closed not merged 2026-10-03T18:55:07Z
- Summary: Hold. reasoning-off is the fast pass, reasoning-on is the default good review. Still in the way: main conflict, --post bug, non-JSON span.
- Tests: pytest tests/test_hare_r1.py → 57 passed
- Owner: eye ball
- Findings:
- real `scripts/hare_local.py:149` Fix yes. --post never posts, dry run can resolve threads
- real `scripts/hare_r1.py:245` Fix yes. closed non-JSON span jumps to j+1 and can hide a valid review
- skip `scripts/hare_r1.py:274` Fix later. first object with findings wins
- Token estimate: about 9000. Earlier pass, about 8,900 to 9,000 from chars/4 plus a local hare unit-test run. Character breakdown was not kept. Not remeasured for this file.
