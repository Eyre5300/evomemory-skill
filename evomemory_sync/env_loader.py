"""Shared environment loader for evomemory_sync.

Goal:
- Unify how `.env` is loaded across worker/middleware/tools.
- Prefer repo-root `.env`, but keep compatibility with legacy `scripts/.env`.
"""

from __future__ import annotations

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
            load_dotenv(dotenv_path=str(p), override=False)

