# -*- coding: utf-8 -*-
import base64
import zlib
from pathlib import Path

def decode(stem: str, n: int, dest: str) -> None:
    parts = []
    for i in range(n):
        parts.append(Path(f".github/f22-review/{stem}.{i}.b64").read_text().strip())
    data = zlib.decompress(base64.b64decode("".join(parts)))
    Path(dest).write_bytes(data)
    print("wrote", dest, len(data))

decode("bi", 2, "searchts/browser_install.py")
decode("test", 1, "tests/test_browser_install.py")
decode("docs", 1, "docs/install.md")
decode("readme", 3, "README.md")
