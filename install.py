#!/usr/bin/env python3
"""Repo-root entry: forwards to scripts/install.py (same args)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
script = root / "scripts" / "install.py"
raise SystemExit(
    subprocess.call([sys.executable, str(script)] + sys.argv[1:])
)
