#!/usr/bin/env python3
"""Repo-root entry: update skill (git pull + pip install -e .)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
script = root / "scripts" / "manage.py"
raise SystemExit(
    subprocess.call([sys.executable, str(script), "upgrade"] + sys.argv[1:])
)
