# -*- coding: utf-8 -*-
"""Twitter/X — check if twitter-cli or bird CLI is available."""

from .base import Channel
from searchts.probe import probe_command


class TwitterChannel(Channel):
    name = "twitter"
    description = "Twitter/X tweets"
    backends = ["twitter-cli", "OpenCLI", "bird CLI (legacy)"]
    tier = 1

    def can_handle(self, url: str) -> bool:
        from urllib.parse import urlparse
        d = urlparse(url).netloc.lower()
        return "x.com" in d or "twitter.com" in d

    def check(self, config=None):
        """Probe candidates in order; first fully-usable backend wins.

        Same two-phase scheme as the other multi-backend channels: first collect every candidate's
        status, the first ok wins; only when there is no ok does the first warn get its turn --
        otherwise an "installed but not logged in" twitter-cli would block the fully-usable OpenCLI
        that comes after it.
        """
        self.active_backend = None
        findings = []

        for backend in self.ordered_backends(config):
            if backend == "twitter-cli":
                result = self._check_twitter_cli()
            elif backend == "OpenCLI":
                result = self._check_opencli()
            elif backend == "bird CLI (legacy)":
                result = self._check_bird()
            else:
                continue

            if result is None:
                continue  # not installed -- does not participate as a candidate
            findings.append((backend, *result))

        for wanted in ("ok", "warn"):
            for backend, status, message in findings:
                if status == wanted:
                    self.active_backend = backend
                    return status, message

        if findings:  # only broken/timeout candidates remain
            return "error", "\n".join(m for _, _, m in findings)

        return "warn", (
            "Twitter CLI is not installed. Install with:\n"
            "  pipx install twitter-cli\n"
            "or:\n"
            "  uv tool install twitter-cli"
        )

    def _check_twitter_cli(self):
        """Probe twitter-cli. Returns None if not installed, otherwise (status, message).

        `twitter status` is the real health signal: when logged in it prints "ok: true", and when
        not logged in it prints "not_authenticated" with a non-zero exit code -- the tool itself is
        alive, so the probe's error status must also be classified by inspecting the output content.
        """
        probe = probe_command(
            "twitter", ["status"], timeout=15, retries=1, package="twitter-cli"
        )
        if probe.status == "missing":
            return None
        if probe.status == "broken":
            return "error", "The twitter-cli command exists but cannot execute.\n" + probe.hint
        if probe.status == "timeout":
            return "error", "twitter-cli health check timed out (already retried once).\n" + probe.hint

        output = probe.output
        if "ok: true" in output:
            return "ok", (
                "twitter-cli fully available (search, read tweets, timeline, long-form/Article, "
                "user queries, threads)"
            )
        if "not_authenticated" in output:
            return "warn", (
                "twitter-cli is installed but not authenticated. Set it up with:\n"
                "  export TWITTER_AUTH_TOKEN=\"xxx\"\n"
                "  export TWITTER_CT0=\"yyy\"\n"
                "or make sure you are logged into x.com in the browser"
            )
        return "warn", (
            "twitter-cli is installed but the authentication check failed. Run:\n"
            "  twitter -v status for detailed information"
        )

    def _check_opencli(self):
        """OpenCLI candidate. None = not installed."""
        from searchts.backends import opencli_status

        st = opencli_status()
        if not st.installed:
            return None
        if st.broken:
            return "error", st.hint
        if st.ready:
            return "ok", (
                "OpenCLI available (reuses the browser's login session). Usage: "
                "opencli twitter search/article/user-posts -f yaml"
            )
        return "warn", st.hint

    def _check_bird(self):
        """Probe bird/birdx (legacy fallback). Returns None if neither is installed, otherwise (status, message)."""
        last_failure = None
        for cmd in ("bird", "birdx"):
            probe = probe_command(
                cmd, ["check"], timeout=15, retries=1, package="@steipete/bird"
            )
            if probe.status == "missing":
                continue
            if probe.status == "broken":
                last_failure = (
                    "error",
                    f"The {cmd} command exists but cannot execute (bird is an npm package; reinstall with "
                    "npm install -g @steipete/bird).\n" + probe.hint,
                )
                continue  # bird is broken, try birdx next
            if probe.status == "timeout":
                last_failure = (
                    "error",
                    f"{cmd} health check timed out (already retried once).\n" + probe.hint,
                )
                continue

            output = probe.output
            if probe.ok:
                return "ok", "bird CLI available (read and search tweets, including long-form/X Article)"
            if "Missing credentials" in output or "missing" in output.lower():
                return "warn", (
                    "bird CLI is installed but has no authentication configured. Set environment variables:\n"
                    "  export AUTH_TOKEN=\"xxx\"\n"
                    "  export CT0=\"yyy\""
                )
            return "warn", (
                "bird CLI is installed but the authentication check failed."
            )
        return last_failure
