# -*- coding: utf-8 -*-
"""Environment health checker — powered by channels.

Each channel knows how to check itself. Doctor just collects the results.
"""

import csv
import io
import os
import re
import subprocess
import sys
from typing import Callable, Dict, Optional, Sequence

from searchts.channels import get_all_channels
from searchts.config import Config

# Rich styles used by format_report. Do not match status tokens like [ok] / [X] / [!].
_RICH_TAG = re.compile(
    r"\[\/?(?:bold|italic|underline|strike|dim|"
    r"cyan|green|yellow|red|blue|magenta|white|black)"
    r"(?: [a-z]+)?\]",
    re.IGNORECASE,
)


def strip_rich_markup(text: str) -> str:
    """Drop Rich tags. Keep the [ok] / [!] / [X] tokens the report already uses."""
    return _RICH_TAG.sub("", text)
