"""Client-side deduplication for middleware→worker uploads (no Hub idempotency key).

Uses a stable fingerprint of the extraction context JSON. If the same fingerprint was
successfully uploaded within a time window, skip LLM + upload to avoid N duplicate cards
when the agent retries the same task.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _state_path() -> Path:
    custom = os.getenv("EVOMEMORY_UPLOAD_DEDUP_STATE_FILE", "").strip()
    if custom:
        return Path(custom).expanduser()
    return Path.home() / ".evomemory" / "upload_dedup.json"


def _window_seconds() -> float:
    raw = os.getenv("EVOMEMORY_UPLOAD_DEDUP_WINDOW_SECONDS", "86400").strip()
    try:
        return max(60.0, float(raw))
    except ValueError:
        return 86400.0


def dedup_enabled() -> bool:
    raw = os.getenv("EVOMEMORY_UPLOAD_DEDUP_ENABLED", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def fingerprint_context(ctx: Any) -> str:
    """Stable SHA256 hex digest of canonical JSON (sorted keys)."""
    blob = json.dumps(ctx, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _load_entries() -> dict[str, float]:
    path = _state_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ent = data.get("entries")
        if isinstance(ent, dict):
            out: dict[str, float] = {}
            for k, v in ent.items():
                if isinstance(k, str) and isinstance(v, (int, float)):
                    out[k] = float(v)
            return out
    except Exception:
        logger.warning("upload_dedup: could not read %s", path, exc_info=True)
    return {}


def _save_entries(entries: dict[str, float]) -> None:
    path = _state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"v": 1, "entries": entries}, indent=2),
            encoding="utf-8",
        )
    except Exception:
        logger.warning("upload_dedup: could not write %s", path, exc_info=True)


def _prune_old(entries: dict[str, float], now: float, window: float) -> dict[str, float]:
    cutoff = now - window
    return {k: v for k, v in entries.items() if v >= cutoff}


def should_skip_duplicate(fingerprint: str) -> bool:
    """True if this fingerprint was recorded as successfully uploaded within the window."""
    if not dedup_enabled():
        return False
    now = time.time()
    window = _window_seconds()
    entries = _prune_old(_load_entries(), now, window)
    if fingerprint in entries:
        logger.info(
            "upload_dedup: skip duplicate context fingerprint=%s… (seen at %s)",
            fingerprint[:16],
            entries[fingerprint],
        )
        _save_entries(entries)
        return True
    _save_entries(entries)
    return False


def mark_upload_succeeded(fingerprint: str) -> None:
    if not dedup_enabled():
        return
    now = time.time()
    window = _window_seconds()
    entries = _prune_old(_load_entries(), now, window)
    entries[fingerprint] = now
    _save_entries(entries)
    logger.debug("upload_dedup: recorded fingerprint=%s…", fingerprint[:16])
