# -*- coding: utf-8 -*-
"""Guard: package code stays plain, reviewable source.

No ``exec`` and no base64 decoding anywhere under ``searchts/``, and no encoded
blob files shipped in the package. Supply-chain scanners flag decode-and-exec
as malware (GuardDog: ``obfuscation.base64exec``), and nobody can review it.
"""

from __future__ import annotations

import re
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "searchts"

_BANNED = (
    (re.compile(r"\bexec\s*\("), "exec("),
    (re.compile(r"\bb64decode\s*\("), "b64decode("),
)

_BLOB_SUFFIXES = {".b64", ".z", ".zlib"}


def test_no_exec_or_base64_decode_in_package():
    hits = []
    for path in sorted(PKG.rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for rx, label in _BANNED:
            for m in rx.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                hits.append(f"{path.relative_to(PKG.parent)}:{line}: {label}")
    assert not hits, "Package code must stay plain source:\n" + "\n".join(hits)


def test_no_encoded_blob_files_in_package():
    blobs = sorted(
        str(p.relative_to(PKG.parent)) for p in PKG.rglob("*") if p.suffix in _BLOB_SUFFIXES
    )
    assert not blobs, f"Encoded blob files in the package: {blobs}"
