"""#346: a JS shell whose served widget clears the length gate says what it is.

The read is kept (the content is real), and a note tells the agent that the
page's own app data holds far more text than the read does.
"""
import json

from searchts import more

TICKER = "\n".join(
    f"INDEX {i}  {10000 + i}.43  -0.50%" for i in range(120)
)
HEADLINES = [
    f"Story number {i} about markets, rates and the economy this week"
    for i in range(80)
]


def _page(state, body):
    blob = json.dumps(state)
    return (
        "<html><head></head><body><div id=\"__next\">"
        f"{body}</div><script id=\"__NEXT_DATA__\" type=\"application/json\">"
        f"{blob}</script></body></html>"
    )


def test_widget_read_of_a_js_shell_gets_an_app_shell_note():
    html = _page({"props": {"stories": [{"headline": h} for h in HEADLINES]}},
                 f"<pre>{TICKER}</pre>")
    note = more.app_shell_note(html, TICKER)
    assert note is not None and note.kind == "app-shell"
    assert "renders most of its text in JavaScript" in note.note
    assert "80 fields" in note.note
    # Counts only: the note never reads the state's text out.
    assert HEADLINES[0] not in note.note
    assert "app-shell" in [m.kind for m in more.detect(html, "https://x.test/", TICKER)]


def test_server_rendered_page_whose_data_matches_the_read_has_no_note():
    body = "\n\n".join(HEADLINES)
    html = _page({"props": {"stories": [{"headline": h} for h in HEADLINES]}},
                 "".join(f"<p>{h}</p>" for h in HEADLINES))
    assert more.app_shell_note(html, body) is None


def test_code_urls_and_ids_in_state_are_not_counted_as_prose():
    state = {
        "js": ["function f(a) { return a => a + 1; }"] * 200,
        "urls": [f"https://cdn.x.test/img/{i}/a-long-file-name.jpg" for i in range(200)],
        "ids": [f"815a6122-a71c-47a0-a311-32f264c80c8{i}" for i in range(200)],
    }
    html = _page(state, f"<pre>{TICKER}</pre>")
    assert more.app_shell_note(html, TICKER) is None


def test_a_little_missing_text_on_a_big_read_is_not_a_shell():
    read = "\n\n".join(HEADLINES * 4)
    html = _page(
        {"extra": ["A newsletter exploring the latest trends and the deeper story"]},
        "".join(f"<p>{h}</p>" for h in HEADLINES),
    )
    assert more.app_shell_note(html, read) is None
