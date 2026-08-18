"""Client-side deduplication for middleware→worker uploads (no Hub idempotency key).

Uses a stable fingerprint of the extraction context JSON. If the same fingerprint was
successfully uploaded within a time window, skip LLM + upload to avoid N duplicate cards
when the agent retries the same task.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, BinaryIO, Iterator

logger = logging.getLogger(__name__)

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


@contextlib.contextmanager
def _locked_state_fp() -> Iterator[BinaryIO]:
    """Exclusive lock on the dedup state file for read–modify–write (cross-process safe)."""
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fp = open(path, "r+b")
    except FileNotFoundError:
        path.write_text(
            json.dumps({"v": 1, "entries": {}}, indent=2),
            encoding="utf-8",
        )
        fp = open(path, "r+b")
    try:
        if sys.platform == "win32":
            import msvcrt as _msvcrt
            # Non-blocking retry loop to avoid indefinite deadlock with LK_LOCK.
            _WIN_LOCK_RETRIES = 50
            _WIN_LOCK_DELAY = 0.1  # seconds
            acquired = False
            fp.seek(0)
            for _ in range(_WIN_LOCK_RETRIES):
                try:
                    _msvcrt.locking(fp.fileno(), _msvcrt.LK_NBLCK, 1)
                    acquired = True
                    break
                except OSError:
                    import time as _t
                    _t.sleep(_WIN_LOCK_DELAY)
            if not acquired:
                raise OSError("upload_dedup: could not acquire Windows file lock after retries")
        else:
            fcntl.flock(fp.fileno(), fcntl.LOCK_EX)
        yield fp
    finally:
        if sys.platform == "win32":
            try:
                fp.seek(0)
                msvcrt.locking(fp.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            try:
                fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        fp.close()


def _read_entries_fp(fp: BinaryIO) -> dict[str, float]:
    fp.seek(0)
    raw = fp.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
        ent = data.get("entries")
        if isinstance(ent, dict):
            out: dict[str, float] = {}
            for k, v in ent.items():
                if isinstance(k, str) and isinstance(v, (int, float)):
                    out[k] = float(v)
            return out
    except Exception:
        logger.warning("upload_dedup: could not read state file", exc_info=True)
    return {}


def _write_entries_fp(fp: BinaryIO, entries: dict[str, float]) -> None:
    try:
        payload = json.dumps({"v": 1, "entries": entries}, indent=2).encode("utf-8")
        fp.seek(0)
        fp.write(payload)
        fp.truncate()
        fp.flush()
        os.fsync(fp.fileno())
    except Exception:
        logger.warning("upload_dedup: could not write state file", exc_info=True)


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


def _prune_old(entries: dict[str, float], now: float, window: float) -> dict[str, float]:
    cutoff = now - window
    return {k: v for k, v in entries.items() if v >= cutoff}


def should_skip_duplicate(fingerprint: str) -> bool:
    """True only if this fingerprint was recorded after a successful Hub upload.

    Failed extract/upload must not occupy the slot — otherwise a later retry of
    the same context is silently skipped for the rest of the window.
    """
    if not dedup_enabled():
        return False
    now = time.time()
    window = _window_seconds()
    with _locked_state_fp() as fp:
        entries = _prune_old(_read_entries_fp(fp), now, window)
        hit = fingerprint in entries
        _write_entries_fp(fp, entries)
        if hit:
            logger.info(
                "upload_dedup: skip duplicate context fingerprint=%s… (uploaded at %s)",
                fingerprint[:16],
                entries[fingerprint],
            )
        return hit


def mark_upload_succeeded(fingerprint: str) -> None:
    if not dedup_enabled():
        return
    now = time.time()
    window = _window_seconds()
    with _locked_state_fp() as fp:
        entries = _prune_old(_read_entries_fp(fp), now, window)
        entries[fingerprint] = now
        _write_entries_fp(fp, entries)
    logger.debug("upload_dedup: recorded fingerprint=%s…", fingerprint[:16])
