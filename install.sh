#!/usr/bin/env sh
# One-liner-friendly: bash install.sh   (same as: python3 scripts/install.py)
set -e
cd "$(dirname "$0")"
exec python3 scripts/install.py "$@"
