#!/usr/bin/env python3
"""
One-step install + Hub registration for evomemory-skill.

1. pip install -e .   (installs package evomemory_sync from this repo)
2. python scripts/setup.py share --base-url <hub>   (interactive email/password → token in .env)

Run from repository root OR from scripts/:

    python scripts/install.py
    python install.py

Optional: set EVOMEMORY_SETUP_EMAIL and EVOMEMORY_SETUP_PASSWORD to skip interactive prompts (CI only).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def main() -> int:
    root = _repo_root()
    ap = argparse.ArgumentParser(
        description="Install evomemory-sync (editable) and configure Hub token via register/login.",
    )
    ap.add_argument(
        "--base-url",
        default="http://evomem.club",
        help="EvoMemory Hub base URL (default: public Hub; vps_bundle-compatible)",
    )
    ap.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS verification (HTTPS + IP / cert mismatch troubleshooting)",
    )
    ap.add_argument(
        "--skip-pip",
        action="store_true",
        help="Skip pip install -e . (if you already installed the package)",
    )
    args = ap.parse_args()

    if not args.skip_pip:
        print("→ pip install -e . (installing evomemory_sync from this directory) …")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "-e", str(root)],
                cwd=str(root),
            )
        except subprocess.CalledProcessError as e:
            print(f"pip install failed: {e}", file=sys.stderr)
            return 1

    setup_py = root / "scripts" / "setup.py"
    if not setup_py.is_file():
        print(f"Cannot find {setup_py}", file=sys.stderr)
        return 2

    cmd = [
        sys.executable,
        str(setup_py),
        "share",
        "--base-url",
        args.base_url,
    ]
    if args.insecure:
        cmd.append("--insecure")

    print("→ Hub account: register or login (saves EVOMEMORY_API_BASE_URL + EVOMEMORY_API_TOKEN to .env) …")
    print()
    try:
        subprocess.check_call(cmd, cwd=str(root))
    except subprocess.CalledProcessError as e:
        return e.returncode if e.returncode else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
