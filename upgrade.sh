#!/usr/bin/env sh
# One-liner: bash upgrade.sh   (same as: python3 upgrade.py)
set -e
cd "$(dirname "$0")"
exec python3 upgrade.py "$@"
