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


def test_private_module_constants_are_names() -> None:
    """A leading underscore must not hide a constant from the whole graph.

    ``CONST`` started with ``[A-Z]``, which fails at position 0, so every
    *private* module constant was invisible: ``_MIN_CHARS``,
    ``_EXTRACT_MIN_RECALL``, ``_AUTH_DENSITY_PER_100``. Measured over six real
    merges, #338 returned **zero** names from the parser for exactly this
    reason: its only new name was ``_REFUSAL_REPEAT_LIMIT = 2``. With no name,
    the graph had nothing to search and fell back to path matching.
    """
    diff = (
        "diff --git a/searchts/unlocker.py b/searchts/unlocker.py\n"
        "index e8c848a..38b1a2c 100644\n"
        "--- a/searchts/unlocker.py\n"
        "+++ b/searchts/unlocker.py\n"
        "@@ -631,2 +631,3 @@ _MIN_CRUDE_LINES = 20\n"
        " \n"
        "+_REFUSAL_REPEAT_LIMIT = 2\n"
    )
    names, _paths, _ranges = hare_graph.changed(diff)
    assert names == ["_REFUSAL_REPEAT_LIMIT"]


def test_private_constants_are_found_by_name_not_just_declared() -> None:
    """The point of a name is to be searched for, so prove the search works."""
    assert hare_graph.CONST.match("_MIN_CHARS = 500")
    assert hare_graph.CONST.match("_AUTH_DENSITY_PER_100 = 2.0")
    assert not hare_graph.CONST.match("_lower_case = 1"), "lowercase is not a constant"


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


def test_declarations_in_other_languages_are_names() -> None:
    """CodeRabbit on #287: `public class LedgerBook` (Java) was not read, nor a
    modifier-led method, Kotlin's fun, or a C signature in a hunk header."""
    diff = (
        "diff --git a/src/A.java b/src/A.java\n@@ -1,2 +1,2 @@ int parse_header(char *s)\n"
        "+public class LedgerBook {\n+    public static void tallyRows(int x) {\n+fun loadPageNow(url: String) {\n"
        "+    tallyRows(3);\n"
    )
    names = hare_graph.changed(diff)[0]
    assert {"parse_header", "LedgerBook", "tallyRows", "loadPageNow"} <= set(names)


def test_only_hunks_the_model_sees_are_skipped(tmp_path) -> None:
    """A hunk cut off the prompt is not in front of the model, so a caller
    inside it is not skipped as if it were."""
    (tmp_path / "s.py").write_text("".join(f"x{i} = load_rows()\n" if i in (2, 20, 25) else f"x{i} = {i}\n" for i in range(1, 30)))
    diff = (
        "diff --git a/s.py b/s.py\n@@ -2,1 +2,1 @@\n-x2 = load_rows()\n+x2 = load_rows(1)\n"
        "@@ -20,1 +20,1 @@\n-x20 = load_rows()\n+def load_rows(n=0):\n"
    )
    first_hunk_only = diff.split("@@ -20")[0]
    lines = [i for i, _ in hare_graph.uses(tmp_path, diff, visible=first_hunk_only)[0]["lines"]]
    assert lines == [20, 25]  # line 2 is in the visible hunk; line 20's hunk was cut off the prompt
    lines = [i for i, _ in hare_graph.uses(tmp_path, diff)[0]["lines"]]
    assert lines == [25]


def test_caps_drop_the_lowest_rank_first(tmp_path, monkeypatch) -> None:
    """CodeRabbit on #287: docs early in the alphabet used up the cap before a
    code caller late in it was read."""
    for i in range(5):
        (tmp_path / "a_docs").mkdir(exist_ok=True)
        (tmp_path / "a_docs" / f"n{i}.md").write_text("tally_rows here\n" * 3)
    (tmp_path / "z_src").mkdir()
    (tmp_path / "z_src" / "use.py").write_text("tally_rows()\n")
    monkeypatch.setattr(hare_graph, "MAX_USES", 3)
    diff = "diff --git a/z_src/t.py b/z_src/t.py\n@@ -1 +1 @@\n+def tally_rows():\n"
    assert hare_graph.uses(tmp_path, diff)[0]["file"] == "z_src/use.py"
    monkeypatch.setattr(hare_graph, "MAX_FILES", 1)
    assert hare_graph._files(tmp_path) == ["z_src/use.py"]
