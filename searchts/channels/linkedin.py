# -*- coding: utf-8 -*-
"""LinkedIn — check if linkedin-scraper-mcp is available."""

from searchts.probe import probe_command

from .base import Channel

#: mcporter is an npm package, so its broken-install fix differs from the default pipx/uv prescription
_MCPORTER_BROKEN_HINT = "mcporter cannot execute (broken node environment). Reinstall:\n  npm install -g mcporter"


class LinkedInChannel(Channel):
    name = "linkedin"
    description = "LinkedIn professional network"
    backends = ["linkedin-scraper-mcp", "Jina Reader"]
    tier = 2

    def can_handle(self, url: str) -> bool:
        from urllib.parse import urlparse
        return "linkedin.com" in urlparse(url).netloc.lower()

    def check(self, config=None):
        self.active_backend = None
        probe = probe_command("mcporter", ["config", "list"], timeout=10, package="mcporter")
        if probe.status == "missing":
            return "off", (
                "Basic content can be read via Jina Reader. Full functionality requires:\n"
                "  pip install linkedin-scraper-mcp\n"
                "  mcporter config add linkedin http://localhost:3000/mcp\n"
                "  See https://github.com/stickerdaniel/linkedin-mcp-server for details"
            )
        if probe.status == "broken":
            return "error", _MCPORTER_BROKEN_HINT
        if not probe.ok:  # timeout / error
            return "error", f"mcporter execution error: {probe.hint or probe.output or probe.status}"
        if "linkedin" in probe.output.lower():
            self.active_backend = "linkedin-scraper-mcp"
            return "ok", "Fully available (profiles, companies, job search)"
        return "off", (
            "mcporter is installed but the LinkedIn MCP is not configured. Run:\n"
            "  pip install linkedin-scraper-mcp\n"
            "  mcporter config add linkedin http://localhost:3000/mcp"
        )
