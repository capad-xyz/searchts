# -*- coding: utf-8 -*-
"""
Searchts — installer, doctor, and configuration tool.

searchts helps AI agents install and configure upstream platform tools
(twitter-cli, yt-dlp, mcporter, gh CLI, etc.). After installation, agents
call the upstream tools directly — no wrapper layer needed.

Usage:
    from searchts.doctor import check_all, format_report
    from searchts.config import Config

    config = Config()
    results = check_all(config)
    print(format_report(results))
"""

from typing import Dict, Optional

from searchts.config import Config


class Searchts:
    """Give your AI Agent eyes to see the entire internet.

    This class provides health-check functionality.
    For reading/searching, use the upstream tools directly
    (see SKILL.md for commands).
    """

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()

    def doctor(self) -> Dict[str, dict]:
        """Check all channel availability."""
        from searchts.doctor import check_all
        return check_all(self.config)

    def doctor_report(self) -> str:
        """Health report as plain text.

        MCP ``get_status`` prints this string as-is, so Rich tags cannot stay.
        The CLI still calls ``format_report`` when it wants color.
        """
        from searchts.doctor import check_all, format_report, strip_rich_markup
        return strip_rich_markup(format_report(check_all(self.config)))
