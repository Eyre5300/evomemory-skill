"""Shared environment loader for evomemory_sync.

Goal:
- Unify how `.env` is loaded across worker/middleware/tools.
- Prefer repo-root `.env`, but keep compatibility with legacy `scripts/.env`.
- Provide shared _env / _env_bool / _env_int / _env_float helpers to avoid duplication.
"""

from __future__ import annotations

import os
import secrets
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


def adaptation_fingerprint_key() -> str:
    """Return a stable local secret for privacy-preserving task fingerprints.

    A raw SHA-256 of common task text is vulnerable to dictionary guessing.  This
    per-installation key lets the client report stable HMAC fingerprints for local
    deduplication without making task text enumerable from the Hub database.  The
    value is persisted in the canonical root `.env` when possible; environments
    with a read-only skill directory retain a process-local fallback instead.
    """
    existing = os.getenv("EVOMEMORY_ADAPTATION_FINGERPRINT_KEY", "").strip()
    if existing:
        return existing

    path = repo_root() / ".env"
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == "EVOMEMORY_ADAPTATION_FINGERPRINT_KEY":
                persisted = value.strip()
                if persisted:
                    os.environ["EVOMEMORY_ADAPTATION_FINGERPRINT_KEY"] = persisted
                    return persisted
    except OSError:
        pass

    key = secrets.token_urlsafe(32)
    try:
        existing_text = path.read_text(encoding="utf-8") if path.exists() else ""
        separator = "" if not existing_text or existing_text.endswith("\n") else "\n"
        path.write_text(
            existing_text + separator + f"EVOMEMORY_ADAPTATION_FINGERPRINT_KEY={key}\n",
            encoding="utf-8",
        )
    except OSError:
        # Do not suppress adaptation evidence just because a packaged skill is
        # installed read-only. The caller still gets privacy protection for this
        # process, but cross-restart task deduplication will not be available.
        pass
    os.environ["EVOMEMORY_ADAPTATION_FINGERPRINT_KEY"] = key
    return key

