# -*- coding: utf-8 -*-
"""``python -m searchts`` must work (no searchts.__main__ was last night's miss)."""

from __future__ import annotations

import subprocess
import sys


def test_python_m_searchts_version() -> None:
    r = subprocess.run(
        [sys.executable, "-m", "searchts", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0, out
    assert "searchts v" in out


def test_python_m_searchts_cli_still_works() -> None:
    r = subprocess.run(
        [sys.executable, "-m", "searchts.cli", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0, out
    assert "searchts v" in out
