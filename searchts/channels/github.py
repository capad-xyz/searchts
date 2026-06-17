# -*- coding: utf-8 -*-
"""GitHub — check if gh CLI is available."""

from searchts.probe import probe_command

from .base import Channel


class GitHubChannel(Channel):
    name = "github"
    description = "GitHub repositories and code"
    backends = ["gh CLI"]
    tier = 0

    def can_handle(self, url: str) -> bool:
        from urllib.parse import urlparse
        return "github.com" in urlparse(url).netloc.lower()

    def check(self, config=None):
        # Actually run `gh auth status` to probe liveness. Note: when not logged in, rc != 0 is a normal
        # business state (warn), not an error.
        probe = probe_command("gh", ["auth", "status"], timeout=10, package="gh")
        if probe.status == "missing":
            self.active_backend = None
            return "warn", "gh CLI is not installed. Install: https://cli.github.com"
        if probe.status == "broken":
            # gh is a binary install (brew/official package), not a pip package, so the fix doesn't use pipx/uv wording
            self.active_backend = None
            return "error", (
                "The gh command exists but cannot execute -- the installation is broken. Reinstall to fix:\n"
                "  brew reinstall gh\n"
                "or reinstall the gh CLI from https://cli.github.com"
            )
        if probe.status == "timeout":
            # The gh binary itself can start (the tool is alive); only the status check timed out
            self.active_backend = "gh CLI"
            return "warn", "gh CLI status check timed out. Run gh auth status for details"
        if probe.ok:
            self.active_backend = "gh CLI"
            return "ok", "Fully available (read, search, fork, issues, PRs, etc.)"
        # rc != 0: gh is alive but not authenticated (the normal business state of gh auth status)
        self.active_backend = "gh CLI"
        return "warn", "gh CLI is installed but not authenticated. Run gh auth login to unlock full functionality"
