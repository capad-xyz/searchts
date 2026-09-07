# -*- coding: utf-8 -*-
"""``python -m searchts`` → the CLI.

The console script ``searchts`` is a different file on PATH (pipx vs editable).
``python -m searchts`` always uses this interpreter's package.
"""

from searchts.cli import main

if __name__ == "__main__":
    main()
