"""Regression: a page-chosen URL may not appear in the MCP envelope.

The failure this pins is subtle and I hit it twice while writing the fix: the
URL survives in ``pages[].text``, because that text is the annotated body and
``more.annotate`` puts the note inside it. That copy is *inside the fence*,
which is correct. The bug is the copy in the envelope proper, so the assertion
has to look at the envelope's own fields, not at a flattened dump of everything
that happens to contain the string.
"""

import json
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
sys.path.insert(0, "scripts")


import searchts.integrations.mcp_server as mcp_server  # noqa: E402

URL = "https://example.test/page/1/"
NEXT = "https://example.test/page/2/"

PAGE = (
    '<html><head><link rel="next" href="/page/2/"></head><body><article><p>'
    "Real article text about a thing that matters here. "
    + "filler sentence about the subject. " * 60
    + "</p></article><a href=\"/page/2/\">Next page</a></body></html>"
)


def _envelope_fields(doc):
    """Every envelope value that is NOT the fenced text or a copy of it.

    ``text`` and ``pages[].text`` hold the annotated body, which is fenced and
    is allowed to name the page's own next URL. Everything else is the envelope
    proper, and that is what must be clean.
    """
    out = {}
    for key, value in doc.items():
        if key == "text":
            continue
        if key == "pages":
            out[key] = [
                {k: v for k, v in p.items() if k != "text"} if isinstance(p, dict) else p
                for p in value
            ]
        else:
            out[key] = value
    return out


def _stub(monkeypatch, warnings=None):
    """read_url with a page that declares its own next page."""
    from searchts import more, unlocker

    body = (
        "Real article text about a thing that matters here. "
        + "filler sentence about the subject. " * 60
    )
    found = more.detect(PAGE, URL, body)

    class R:
        pass

    r = R()
    r.text = more.annotate(body, found)
    r.status = 200
    r.backend = "curl_cffi"
    r.final_url = URL
    r.fetched_at = "2026-10-08T00:00:00Z"
    r.warnings = warnings or []
    r.next_url = NEXT
    r.more = [m.as_dict() for m in found]
    r.page_html = None
    # F27: the envelope reports whether the read was authenticated. A stub that
    # omits it fails with an AttributeError here, which is the point: the field
    # is part of the receipt every caller now depends on.
    r.authenticated = False

    monkeypatch.setattr(unlocker, "fetch", lambda url, **kw: r)
    monkeypatch.setattr(unlocker, "read_pages", lambda url, p=None, **kw: [r])
    monkeypatch.setattr(unlocker, "read_items", lambda url, i=0, **kw: [r])
    monkeypatch.setattr(unlocker, "reset_jina_spend", lambda: None)
    return r


def test_the_envelope_carries_no_next_url(monkeypatch):
    """A page must not author the next request. #339 added the cursor; this
    removes the leftover URL the page still gets to name."""
    _stub(monkeypatch)
    doc = json.loads(mcp_server.read_url(URL))
    assert "next_url" not in doc
    assert NEXT not in json.dumps(_envelope_fields(doc))


def test_more_still_says_there_is_more_without_naming_it(monkeypatch):
    """The useful half is kept: the model learns there is more and is told how
    to ask. Only the page's choice of destination is withheld."""
    _stub(monkeypatch)
    doc = json.loads(mcp_server.read_url(URL))
    notes = " ".join(m.get("note") or "" for m in doc["more"])
    assert "next_cursor" in notes, "the model must be told how to continue"
    assert "http" not in notes


def test_the_fenced_text_still_names_the_page_s_own_next_url(monkeypatch):
    """Sanity on the other direction: we are not hiding what the page said.

    The URL stays inside the fence, where it is labelled as page data. That is
    the point of the fence, not a leak.
    """
    _stub(monkeypatch)
    doc = json.loads(mcp_server.read_url(URL))
    assert NEXT in doc["text"]


def test_a_page_with_no_more_findings_is_unaffected(monkeypatch):
    """The common case must not gain a field or lose one."""
    r = _stub(monkeypatch)
    r.more = []
    r.next_url = None
    r.text = "An ordinary article with nothing else on it."
    doc = json.loads(mcp_server.read_url("https://example.test/plain"))
    assert "next_url" not in doc
    assert doc["more"] == []
    assert doc["chars"] == len(r.text)


def test_more_without_urls_is_pure():
    """Directly, because it is where the second leak was."""
    found = [
        {"kind": "next-page", "note": "[more: the next page is https://x.test/2/]",
         "url": "https://x.test/2/"},
        {"kind": "fold", "note": "[more: 3 sections folded]"},
        {"kind": "feed", "note": "[more: an RSS feed]", "url": "https://x.test/f.xml"},
    ]
    cleaned = mcp_server._more_without_urls(found)
    assert all("url" not in item for item in cleaned)
    assert "https://" not in json.dumps(cleaned)
    # The non-URL note survives untouched: it never carried one.
    assert cleaned[1]["note"] == "[more: 3 sections folded]"
    assert "next_cursor" in cleaned[0]["note"]


def test_more_without_urls_survives_junk():
    """A non-list, or a non-dict inside the list, must not raise here."""
    assert mcp_server._more_without_urls(None) is None
    assert mcp_server._more_without_urls(["odd"]) == ["odd"]