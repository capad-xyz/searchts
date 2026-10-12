"""The lifecycle verifier's last check actually runs.

The review caught a real defect here and it is worth saying why a test was
needed at all. The verifier printed its verdict from inside a ``try`` block,
returned from inside it, and kept the "throwaway profile is cleaned up" check
after the ``finally``. A ``return`` inside a ``try`` skips everything past the
matching ``finally``, so that check ran on no code path: a safety check that
read as part of the verifier and executed never. Nothing failed, because a
check that never runs cannot fail, and the verifier exited 0 while quietly
skipping the one thing it was there to prove.

Ruff does not catch this. Confirmed against ``--select ALL``: unreachable
statements after a return inside try/finally raise no rule. So the test is here.

Both tests run the real script as a subprocess and assert on its exit code and
its output, because that is what a person running the verifier observes. They
plant a stray directory rather than reading the source, because the defect was
never visible in the source -- it was visible in what the script failed to do.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "scripts" / "verify_login_lifecycle.py"
CLEANUP_CHECK = "the throwaway profile is cleaned up"


def _run() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VERIFIER)],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(ROOT),
    )


def test_a_verifier_that_ran_its_cleanup_check_reports_it():
    """The happy path still says the check passed, out loud.

    Asserting the check appears in the output is the load-bearing half. An
    earlier version of this verifier passed this test too while the check ran
    nowhere, because the suite never asked the script to perform anything.
    """
    out = _run()
    assert CLEANUP_CHECK in out.stdout, (
        "the cleanup check never reported, so it never ran; the verifier is "
        "reporting a verdict without performing its last check"
    )


def test_a_stray_profile_makes_the_verifier_fail(tmp_path):
    """A leftover profile must fail the run, not pass quietly.

    Without this the previous test cannot fail for the right reason: it passes
    whenever the script exits 0, which is also what it did while the check was
    dead code.
    """
    stray = Path(tempfile.gettempdir()) / f"searchts-verify-{tmp_path.name}"
    stray.mkdir(parents=True, exist_ok=True)
    try:
        out = _run()
    finally:
        import shutil

        shutil.rmtree(stray, ignore_errors=True)

    assert out.returncode != 0, "a leftover profile did not fail the verifier"
    assert CLEANUP_CHECK in out.stdout
