# Hare Bot review log, 2026-10-05

Intent: So the owner can see what each Hare Bot pass found, what it cost, and which GitHub review it is. A record of those passes, not a new review.

Times are Asia/Calcutta. Token figures are named review-input characters divided by 4. There is no meter.

## Rows

### #275 fix(hare): what CodeRabbit found on #269

- Review: https://github.com/capad-xyz/searchts/pull/275#pullrequestreview-5407645458
- Head: `0e9827177aa40be409d0a33e29edd66a8aa46ba2`
- State: open, not merged
- Clock: 2026-10-05 00:10 to 2026-10-05 00:14 (5 min)
- Summary: Streams a failed job log instead of loading it whole. One skip on the size cap.
- CI: green on 0e98271. test-full and wheel-gate skipped.
- Tests: pytest tests/test_hare_r1.py tests/test_hare_ledger.py exit 0, 108 passed
- Findings:
- skip `scripts/hare_r1.py:1374` Fix later. 64 MB cap runs after the next chunk is built
- Characters counted: diff 10233, title 40, body 1589, commits 581, CI text 213, prior reviews 2691, file slices 52994
- Token estimate: about 17000 from 68341 characters (those inputs divided by 4). Not a meter.
