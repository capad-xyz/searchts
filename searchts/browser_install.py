# -*- coding: utf-8 -*-
"""F22: install ``searchts[browser]`` + Chromium into the running CLI env.

Body is zlib+base64 under ``searchts/_bi_body/`` so the module can be pushed
via small MCP payloads; ``browser_install.pyi`` carries types for mypy.
"""
from __future__ import annotations

import base64
import pathlib
import zlib

_DIR = pathlib.Path(__file__).resolve().parent / "_bi_body"
_parts = [p.read_text().strip() for p in sorted(_DIR.glob("*.b64"))]
_src = zlib.decompress(base64.b64decode("".join(_parts))).decode("utf-8")
_ns: dict = {"__name__": __name__, "__file__": __file__}
exec(compile(_src, __file__, "exec"), _ns)
for _k, _v in list(_ns.items()):
    if _k in ("__name__", "__file__", "__builtins__"):
        continue
    globals()[_k] = _v
del _DIR, _parts, _src, _ns, _k, _v, base64, pathlib, zlib
