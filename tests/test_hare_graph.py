import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import hare_graph  # noqa: E402

DIFF = """diff --git a/scripts/tool.py b/scripts/tool.py
--- a/scripts/tool.py
+++ b/scripts/tool.py
@@ -3,2 +3,3 @@ def fetch_page(url):
-    return get(url)
+    return get(url, timeout=TIMEOUT_S)
+TIMEOUT_S = 30
@@ -9,1 +10,2 @@ class LedgerBook:
+    def tally_rows(self):
"""


def _repo(tmp: Path) -> Path:
    files = {
        "scripts/tool.py": "import os\n\ndef fetch_page(url):\n    return get(url)\n\n\ndef helper():\n    return fetch_page('x')\n\nclass LedgerBook:\n    pass\n",
        "scripts/other.py": "from tool import fetch_page\n\nfetch_page('y')\nLedgerBook()\n",
        "tests/test_tool.py": "from tool import fetch_page\nassert fetch_page\n",
        ".github/workflows/run.yml": "on: issue_comment\nconcurrency:\n  group: run-${{ github.event_name }}\n  cancel-in-progress: true\njobs:\n  r:\n    steps:\n      - run: python scripts/tool.py\n",
        "docs/guide.md": "Call fetch_page with a URL.\n",
        "node_modules/x/index.js": "fetch_page()\n",
        "assets/logo.png": "fetch_page",
    }
    for rel, text in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp


def test_changed_names_come_from_defs_constants_and_hunk_headers() -> None:
    names, paths, ranges = hare_graph.changed(DIFF)
    assert {"fetch_page", "TIMEOUT_S", "LedgerBook", "tally_rows"} <= set(names)
    assert paths == ["scripts/tool.py"] and ranges["scripts/tool.py"] == [(3, 5), (9, 10)]
    assert hare_graph.changed("diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-def test_x():\n+def main():\n")[0] == []


def test_uses_are_ranked_code_then_config_then_docs_and_skip_the_diff(tmp_path) -> None:
    found = hare_graph.uses(_repo(tmp_path), DIFF)
    files = [u["file"] for u in found]
    assert files == ["scripts/other.py", "scripts/tool.py", "tests/test_tool.py", ".github/workflows/run.yml", "docs/guide.md"]
    tool = next(u for u in found if u["file"] == "scripts/tool.py")
    assert [i for i, _ in tool["lines"]] == [8]  # the caller; lines 3-4 and 9 are in the diff
    wf = next(u for u in found if u["file"] == ".github/workflows/run.yml")
    assert "cancel-in-progress: true" in wf["whole"]  # read whole: it names a changed file


def test_each_hop_gets_what_its_budget_holds(tmp_path) -> None:
    found = hare_graph.uses(_repo(tmp_path), DIFF)
    big = hare_graph.section(found, hare_graph.budget_for("gemini"))
    assert "cancel-in-progress" in big and "docs/guide.md" in big
    small = hare_graph.section(found, len(hare_graph.HEADER) + 140)
    assert "scripts/other.py" in small and "cancel-in-progress" not in small
    assert hare_graph.section(found, 10) == "" and hare_graph.section([], 99_999) == ""
    assert hare_graph.budget_for("groq") < hare_graph.budget_for("openrouter") < hare_graph.budget_for("gemini")


def test_bounds_hold(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(hare_graph, "MAX_FILES", 2)
    assert len(hare_graph._files(_repo(tmp_path))) == 2


def test_only_distinctive_names_are_searched() -> None:
    """A plain word floods the search: on #282's replay `link` matched 30 files."""
    assert not hare_graph._keep("link") and not hare_graph._keep("Ledger") and not hare_graph._keep("test_thing")
    assert all(hare_graph._keep(n) for n in ("render_comment", "ACK_MARK", "LedgerBook", "_hare_once", "summarize_rows", "fetchPage"))
