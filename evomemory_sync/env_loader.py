"""Shared environment loader for evomemory_sync.

Goal:
- Unify how `.env` is loaded across worker/middleware/tools.
- Prefer repo-root `.env`, but keep compatibility with legacy `scripts/.env`.
- Provide shared _env / _env_bool / _env_int / _env_float helpers to avoid duplication.
"""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    # evomemory_sync/ -> evomemory-skill/
    return Path(__file__).resolve().parent.parent


def candidate_env_paths() -> list[Path]:
    root = repo_root()
    return [
        root / ".env",
        root / "scripts" / ".env",
    ]


def load_env() -> None:
    """Load env files (best-effort). Never raise if dotenv is missing."""

    try:
        from dotenv import load_dotenv
    except Exception:
        return

    for p in candidate_env_paths():
        if p.exists():
            # override=True so edits to .env take effect on the next load_env() call (long-running agents).
            load_dotenv(dotenv_path=str(p), override=True)


# ---------------------------------------------------------------------------
# Shared env helpers — single source of truth for all modules
# ---------------------------------------------------------------------------

def env(name: str, default: str = "") -> str:
    """Get env var (string) with lazy load_env()."""
    val = os.getenv(name)
    if val is not None:
        return val
    load_env()
    return os.getenv(name, default)


def env_bool(name: str, default: bool) -> bool:
    """Get env var as bool (true/1/yes → True)."""
    val = env(name, "")
    if not val:
        return default
    return val.strip().lower() in ("true", "1", "yes")


def env_int(name: str, default: int) -> int:
    """Get env var as int."""
    val = env(name, "")
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    """Get env var as float."""
    val = env(name, "")
    if not val:
        return default
    try:
        return float(val)
    except ValueError:
        return default

