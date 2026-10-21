"""Tests for the user-facing message shaping (UX pass, 2026-10-08).

Every case here is a message someone actually typed. The two that motivated the
change cost 18.6s each and produced a Playwright call log; see the PR body for
the before/after. These are hermetic: no network, no timing assertions that
could flake, just "is the message the one a user needs".
"""

import pytest

from searchts import ux


class TestCheckUrl:
    """Nothing that used to read must be rejected."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com",
            "http://example.com",
            "HTTPS://EXAMPLE.COM",
            "https://example.com/path?q=1&r=2#frag",
            "https://sub.domain.co.uk/a/b/c.html",
            "http://localhost:8080/x",
            "https://user:pass@example.com/x",
            "https://xn--80ak6aa92e.com/",
            "https://例え.jp/",
        ],
    )
    def test_accepts_real_urls(self, url):
        assert ux.check_url(url) is None

    def test_a_bare_word_is_a_typo(self):
        """The 18.6s case. A bare word is a valid hostname in a lab, never here."""
        msg = ux.check_url("not-a-url")
        assert msg is not None
        assert "not a URL" in msg
        assert "https://not-a-url/" in msg, "must offer the URL they probably meant"

    def test_a_single_common_word_is_still_a_typo(self):
        assert "https://example/" in (ux.check_url("example") or "")

    def test_a_bare_word_with_a_path_is_still_caught(self):
        assert ux.check_url("example/page") is not None

    def test_names_the_bad_scheme_and_offers_the_target(self):
        msg = ux.check_url("htp://example.com")
        assert msg is not None
        assert "'htp'" in msg
        assert "https://example.com" in msg
        # The old draft suggested a bare "https://", which is not a URL and
        # would be a second failure. This pins the usable suggestion.
        assert "https:// ?\"" not in msg

    def test_preserves_path_and_query_in_the_suggestion(self):
        msg = ux.check_url("htp://a.b/c?x=1") or ""
        assert "https://a.b/c?x=1" in msg

    def test_a_scheme_with_no_host_gets_no_invented_url(self):
        """file:///etc/passwd must not be 'fixed' into https:///etc/passwd."""
        msg = ux.check_url("file:///etc/passwd")
        assert msg is not None
        assert "names no site" in msg
        assert "https:///" not in msg

    def test_a_space_is_named_as_the_problem(self):
        msg = ux.check_url("https://exa mple.com")
        assert msg is not None and "space" in msg

    def test_empty_input(self):
        assert ux.check_url("") == "no URL given"
        assert ux.check_url("   ") == "no URL given"


class TestTidyReason:
    """Library debugging help is for the integrator, not the person who mistyped."""

    def test_strips_the_playwright_call_log(self):
        raw = (
            "Page.goto: net::ERR_NAME_NOT_RESOLVED at https://x/\n"
            "Call log:\n"
            '  - navigating to "https://x/", waiting until "domcontentloaded"'
        )
        out = ux.tidy_reason(raw)
        assert "Call log" not in out
        assert "domcontentloaded" not in out
        assert "ERR_NAME_NOT_RESOLVED" in out, "the actual cause must survive"

    def test_strips_the_curl_documentation_pointer(self):
        raw = (
            "DNSError: Failed to perform, curl: (6) Could not resolve host: x. "
            "See https://curl.se/libcurl/codes.html first for more details."
        )
        out = ux.tidy_reason(raw)
        assert "curl.se" not in out
        assert "Could not resolve host: x." in out

    def test_leaves_an_ordinary_reason_untouched(self):
        for raw in ("http-403", "cookie-wall", "thin-41b",
                    "HTTPError: HTTP Error 403: Forbidden"):
            assert ux.tidy_reason(raw) == raw

    def test_never_returns_empty(self):
        assert ux.tidy_reason("") == "failed"
        assert ux.tidy_reason("   \n ") == "failed"

    def test_does_not_mangle_a_reason_that_merely_mentions_a_url(self):
        raw = "thin-200b (page has 3 of 4 sections, see https://example.com/x)"
        assert ux.tidy_reason(raw) == raw


class TestFolderLink:
    """The grab folder has to be something a person can open with a click."""

    def test_a_posix_path_becomes_a_file_uri(self, tmp_path):
        folder = tmp_path / "my kit"
        folder.mkdir()
        uri = ux.file_uri(str(folder))
        expected = "file:///" + str(folder).lstrip("/").replace(" ", "%20")
        assert uri == expected
        assert " " not in uri

    def test_a_windows_drive_path_opens_as_a_file_uri(self, monkeypatch):
        monkeypatch.setattr(ux.os, "name", "nt")
        monkeypatch.setattr(ux.os.path, "abspath", lambda p: p)
        uri = ux.file_uri(r"C:\Users\Aadarsh Upadhyay\searchts-grab-stripe.com")
        assert uri == "file:///C:/Users/Aadarsh%20Upadhyay/searchts-grab-stripe.com"

    def test_the_visible_text_is_the_path_and_the_target_is_the_uri(self, tmp_path):
        folder = tmp_path / "kit"
        folder.mkdir()
        shown = ux.clickable_path(str(folder), link=True)
        assert shown.startswith("\033]8;;file://")
        assert shown.endswith("\033]8;;\033\\")
        # The label between the open and the close is the path, not the URI.
        label = shown.split("\033\\", 1)[1]
        assert label.startswith(str(folder))

    def test_a_pipe_gets_the_path_and_no_escapes(self, tmp_path):
        folder = str(tmp_path / "kit")
        assert ux.clickable_path(folder, link=False) == folder

    def test_dumb_terminals_and_pipes_do_not_get_links_or_color(self, monkeypatch):
        class Stream:
            def __init__(self, tty):
                self.tty = tty

            def isatty(self):
                return self.tty

        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("TERM", "xterm")
        assert ux.links_enabled(Stream(True)) is True
        assert ux.color_enabled(Stream(True)) is True
        assert ux.links_enabled(Stream(False)) is False
        monkeypatch.setenv("TERM", "dumb")
        assert ux.links_enabled(Stream(True)) is False
        assert ux.color_enabled(Stream(True)) is False
        monkeypatch.setenv("TERM", "xterm")
        monkeypatch.setenv("NO_COLOR", "1")
        assert ux.color_enabled(Stream(True)) is False
        assert ux.links_enabled(Stream(True)) is True

    def test_a_chip_keeps_the_hex_and_paints_only_six_digit_colors(self):
        text = ux.palette_text(["#0a0a23", "#fff", ""], color=True)
        assert "\033[48;2;10;10;35m  \033[0m #0a0a23" in text
        assert "#fff" in text
        assert "\033[48;2;" in text.split("#fff")[0]
        assert ux.palette_text(["#0a0a23"], color=False) == "#0a0a23"
