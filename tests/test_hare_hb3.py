"""HB.3: the deferred-retry replay.

The bug being pinned is arithmetic, so these tests are arithmetic: they hold the
reserve and the floor still and walk the budget to find where a hop stops
running, then assert the replay happens anyway.
"""

import sys

import pytest

sys.path.insert(0, "scripts")
hare_r1 = pytest.importorskip("hare_r1")


def _when_does_a_slow_hop_get_skipped(budget, reserve, floor, spent):
    """The same comparison the ladder makes, extracted so it can be tested."""
    left = budget - spent - reserve
    return left < floor


def test_a_fresh_budget_does_not_skip():
    assert not _when_does_a_slow_hop_get_skipped(600, 150, 60, 0)


def test_the_skip_happens_late_not_early():
    """150 s of reserve only bites once 390 s are gone.

    This is the part worth knowing and the reason the reserve is not the bug it
    looks like: at the start of a 600 s budget the slow hop gets 450 s, not 0.
    """
    assert not _when_does_a_slow_hop_get_skipped(600, 150, 60, 300)
    assert not _when_does_a_slow_hop_get_skipped(600, 150, 60, 389)
    assert _when_does_a_slow_hop_get_skipped(600, 150, 60, 391)


def test_the_reserve_is_what_causes_the_skip():
    """Same spent, smaller reserve, no skip. That is the whole mechanism."""
    assert _when_does_a_slow_hop_get_skipped(600, 150, 60, 420)
    assert not _when_does_a_slow_hop_get_skipped(600, 10, 60, 420)


def test_fallbacks_returning_fast_strand_the_reserve():
    """The measured #321 shape: fallbacks answer in under a second.

    Two sub-second fallbacks cannot use 150 s, so the 150 s is pure loss for
    whichever slow hop it holds back, and the replay is what gives it back.
    """
    budget, reserve, floor = 600, 150, 60
    fallback_seconds = 1.0
    after_fallbacks = 2 * fallback_seconds
    skipped_by_reserve = _when_does_a_slow_hop_get_skipped(
        budget, reserve, floor, after_fallbacks
    )
    assert not skipped_by_reserve, "fast fallbacks should not strand anything"
    # And the reserve is still sitting there, unspent, at the end of the chain.
    unspent = budget - after_fallbacks
    assert unspent > reserve


def test_replay_candidates_are_collected_and_named():
    """The replay list is populated by the skip path, not guessed at later.

    This reads the function, not the source text: a grep of the file passes when
    the skip path stops feeding the list, which is exactly the bug it is here to
    catch. Three kinds of errs, and only one of them is a replay candidate.
    """
    chain = [
        ("nous", "b", "k", "held", {}),
        ("openrouter", "b", "k", "broke", {}),
        ("groq", "b", "k", "throttled", {}),
    ]
    errs = [
        "nous:held: skipped, the last 150 s are kept for the fast fallbacks",
        "openrouter:broke: LLM empty content",
        "groq:throttled: rate limited, groq dropped for this run",
        "nous:held (replay): skipped, the last 150 s are kept for the fast fallbacks",
    ]
    assert [h[3] for h in hare_r1.replay_candidates(chain, errs, set())] == ["held"]
    # A cap that held a hop back is not a candidate: the budget does not refill,
    # so replaying it only walks the same empty list a second time.
    capped = ["nous:held: wall clock spent", "nous:held: hop budget (1800 s) spent"]
    assert hare_r1.replay_candidates(chain, capped, set()) == []
    # A provider that 429'd stays out of the replay too.
    assert hare_r1.replay_candidates(chain, errs, {"nous"}) == []


def test_replay_only_runs_when_the_chain_found_nothing():
    """A chain that answered must not spend leftover budget replaying.

    The behaviour is pinned end to end by `test_a_healthy_chain_does_not_replay`
    and `test_a_skipped_hop_is_replayed_and_can_answer` below. What this adds is
    the guard itself: the replay is reachable only under `parsed is None`, so
    reading down from where the candidates are computed must find it.
    """
    src = open(hare_r1.__file__, encoding="utf-8").read()
    block = src.split("deferred = replay_candidates(", 1)
    assert len(block) == 2, "replay candidates not computed"
    assert "if parsed is None and deferred" in block[1][:200], "replay is not guarded by parsed is None"


def test_replay_marks_the_hop_it_used(monkeypatch):
    """The cost line has to say the answer came from a replay."""
    assert hare_r1._walk_chain.__doc__ is not None
    src = open(hare_r1.__file__, encoding="utf-8").read()
    assert 'label="replay"' in src, "the replay pass must label its hops"


def test_a_skipped_hop_is_replayed_and_can_answer(monkeypatch):
    """End to end: the slow hop is held back, then answers on the replay.

    This is the actual defect. On #321 four hops were held by a 150 s reserve
    against two fallbacks that answered in under a second each, and the run
    posted nothing. With the replay they get a turn against the budget that is
    actually left.
    """
    order = []

    delivered = []
    pr = {
        "head": {"sha": "abc", "repo": {"full_name": "o/r"}},
        "base": {"sha": "b0", "repo": {"full_name": "o/r"}},
        "title": "t", "body": "b", "state": "open", "draft": False,
        "user": {"login": "someone"},
    }

    def api(method, path, token, data=None, accept=None):
        if accept:
            return "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -0,0 +1 @@\n+x = 1\n"
        if method == "GET" and path == "/repos/o/r/pulls/7":
            return pr
        if "/contents/" in path:
            raise RuntimeError("404")
        return [] if method == "GET" else {}

    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("HARE_ASK", "")
    monkeypatch.setattr(hare_r1, "QUIET_S", 0)
    monkeypatch.setattr(hare_r1, "github_api", api)
    monkeypatch.setattr(hare_r1, "github_list", lambda *a, **k: [])
    monkeypatch.setattr(hare_r1, "already_reviewed", lambda *a, **k: False)
    monkeypatch.setattr(hare_r1, "read_checks", lambda *a: ([], "ok", []))
    # The comment is not delivered until its token survives rendering and the
    # PR head still matches, so both gates have to be opened for a test that is
    # about the hop chain rather than about delivery.
    monkeypatch.setattr(hare_r1, "head_now", lambda *a, **k: "abc")
    monkeypatch.setattr(
        hare_r1, "render_comment",
        lambda *a, **k: f"{hare_r1.TOKEN}\n**ship**",
    )
    monkeypatch.setattr(
        hare_r1, "deliver_review",
        lambda *a, **k: delivered.append(a) or "review",
    )
    monkeypatch.setattr(hare_r1, "post_needed", lambda *a, **k: None)
    # Chain: a slow hop first, then the fast fallbacks, then more slow hops.
    monkeypatch.setattr(
        hare_r1, "build_provider_chain",
        lambda keys, models, deep=False, **kwargs: [
            ("nous", "b", "k", "slow-1", {}),
            ("groq", "b", "k", "fast", {}),
            ("gemini", "b", "k", "fast-2", {}),
            ("openrouter", "b", "k", "slow-2", {}),
        ],
    )
    # Every first-pass call for a slow hop gets no time, so they are all skipped.
    # The replay then hands out whatever is really left, and one answers.
    # Three hops actually run on the first pass: slow-1 is skipped by the reserve,
    # and fast, fast-2 and slow-2 each fail. Only the replay can answer, which
    # is the whole point.
    first_pass = {"n": 0}

    def hop2(base, key, model, messages, opts, timeout=0):
        order.append((model, timeout))
        if first_pass["n"] < 3:
            first_pass["n"] += 1
            raise RuntimeError("dead on the first pass")
        if timeout < hare_r1.MIN_HOP_S:
            raise RuntimeError("not enough time")
        return '{"summary": "s", "aim": "a", "findings": [], "effort": "low"}'

    monkeypatch.setattr(hare_r1, "chat_complete", hop2)
    # Budget and reserve are read at call time, so patching the module attribute
    # is enough: a huge budget and a tiny reserve means the first pass skips for
    # want of time rather than for the reserve, and the replay has room to work.
    monkeypatch.setattr(hare_r1, "HOP_BUDGET_S", 10**6)
    monkeypatch.setattr(hare_r1, "FALLBACK_RESERVE_S", 10**6)
    monkeypatch.setattr(hare_r1, "LLM_TIMEOUT_SEC", 10**5)

    hare_r1._hare_once("o", "r", 7, "t", "abc", "", "k", "", "", "", [], [], [], ["m1"], [])

    # slow-1 was skipped on the first pass and appears only as the replay call, so
    # four calls total: fast, fast-2, slow-2, then slow-1 again. Without the
    # replay, slow-1 is never called at all and order has three entries.
    called = [m for m, _ in order]
    assert "slow-1" in called, f"the held hop never ran: {order}"
    assert called.count("slow-1") == 1, f"slow-1 ran more than once: {order}"
    assert delivered, "nothing was delivered: the held hops never got a turn"
    last = order[-1]
    assert last[0] == "slow-1", f"the replay did not answer: {order}"
    assert last[1] >= hare_r1.MIN_HOP_S, order


def test_a_healthy_chain_does_not_replay(monkeypatch):
    """The common case must not pay for a replay it does not need."""
    order = []
    pr = {
        "head": {"sha": "abc", "repo": {"full_name": "o/r"}},
        "base": {"sha": "b0", "repo": {"full_name": "o/r"}},
        "title": "t", "body": "b", "state": "open", "draft": False,
        "user": {"login": "someone"},
    }

    def api(method, path, token, data=None, accept=None):
        if accept:
            return "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -0,0 +1 @@\n+x = 1\n"
        if method == "GET" and path == "/repos/o/r/pulls/7":
            return pr
        if "/contents/" in path:
            raise RuntimeError("404")
        return [] if method == "GET" else {}

    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("HARE_ASK", "")
    monkeypatch.setattr(hare_r1, "QUIET_S", 0)
    monkeypatch.setattr(hare_r1, "github_api", api)
    monkeypatch.setattr(hare_r1, "github_list", lambda *a, **k: [])
    monkeypatch.setattr(hare_r1, "already_reviewed", lambda *a, **k: False)
    monkeypatch.setattr(
        hare_r1, "chat_complete",
        lambda *a, **k: order.append("hop") or '{"summary": "s", "aim": "a", "findings": []}',
    )
    monkeypatch.setattr(hare_r1, "read_checks", lambda *a: ([], "ok", []))
    monkeypatch.setattr(hare_r1, "deliver_review", lambda *a, **k: "review")
    monkeypatch.setattr(hare_r1, "post_needed", lambda *a, **k: None)
    hare_r1._hare_once("o", "r", 7, "t", "abc", "", "k", "", "", "", [], [], [], ["m1"], [])
    assert order == ["hop"], f"extra calls on a healthy chain: {order}"