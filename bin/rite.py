#!/usr/bin/env python3
"""Rite CLI entry point. Requires Python >= 3.11 (tomllib); stdlib only."""

import sys
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit("rite: Python 3.11+ required (found %d.%d)" % sys.version_info[:2])

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rite_lib.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
