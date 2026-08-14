"""Durable, privacy-minimized delivery queue for Hub application outcomes."""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Literal

from .env_loader import env as _env, env_int as _env_int

logger = logging.getLogger(__name__)

DeliveryResult = Literal["sent", "retry", "discard"]
Sender = Callable[[str, dict[str, Any], dict[str, str] | None], DeliveryResult]

_UUID_RE = re.compile(r"^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$", re.I)
_ALLOWED_PAYLOAD_KEYS = frozenset(
    {
        "task_fingerprint", "attribution", "application_id", "outcome",
        "validation_status", "evidence_type", "validation_reason", "agent_profile",
        "token_cost", "wall_time_ms", "tool_calls", "failure_type",
    }
)
_lock = threading.RLock()


def queue_path() -> Path:
    configured = _env("EVOMEMORY_OUTCOME_QUEUE_PATH", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".evomemory" / "outcomes.sqlite3"


def _connect() -> sqlite3.Connection:
    path = queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_outcomes (
          application_id TEXT PRIMARY KEY,
          memory_id TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'dead')),
          attempts INTEGER NOT NULL DEFAULT 0,
          next_attempt_at REAL NOT NULL DEFAULT 0,
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL,
          last_error TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pending_outcomes_due ON pending_outcomes(state, next_attempt_at, created_at)"
    )
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return conn


def _validated_payload(memory_id: str, payload: dict[str, Any]) -> tuple[str, str]:
    mid = str(memory_id or "").strip().lower()
    if not _UUID_RE.fullmatch(mid):
        raise ValueError("memory_id must be a UUID")
    if set(payload) - _ALLOWED_PAYLOAD_KEYS:
        raise ValueError("outcome payload contains non-approved fields")
    application_id = str(payload.get("application_id") or "").strip().lower()
    if not _UUID_RE.fullmatch(application_id):
        raise ValueError("application_id must be a UUID")
    fingerprint = str(payload.get("task_fingerprint") or "")
    if not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
        raise ValueError("task_fingerprint must be a lowercase HMAC-SHA256")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 16_384:
        raise ValueError("outcome payload exceeds queue size limit")
    return application_id, encoded


def enqueue_outcome(memory_id: str, payload: dict[str, Any]) -> bool:
    """Persist before network delivery; one row per Hub application."""
    application_id, encoded = _validated_payload(memory_id, payload)
    max_pending = max(100, _env_int("EVOMEMORY_OUTCOME_QUEUE_MAX", 50_000))
    now = time.time()
    with _lock, _connect() as conn:
        existing = conn.execute(
            "SELECT 1 FROM pending_outcomes WHERE application_id = ?", (application_id,)
        ).fetchone()
        if not existing:
            count = int(conn.execute(
                "SELECT count(*) FROM pending_outcomes WHERE state = 'pending'"
            ).fetchone()[0])
            if count >= max_pending:
                logger.error("outcome queue is full (%s); refusing unbounded local growth", max_pending)
                return False
        conn.execute(
            """
            INSERT INTO pending_outcomes
              (application_id, memory_id, payload_json, state, attempts,
               next_attempt_at, created_at, updated_at, last_error)
            VALUES (?, ?, ?, 'pending', 0, 0, ?, ?, '')
            ON CONFLICT(application_id) DO UPDATE SET
              memory_id = excluded.memory_id,
              payload_json = excluded.payload_json,
              state = 'pending',
              next_attempt_at = 0,
              updated_at = excluded.updated_at,
              last_error = ''
            """,
            (application_id, str(memory_id).strip().lower(), encoded, now, now),
        )
    return True


def flush_pending_outcomes(
    headers: dict[str, str] | None,
    *, sender: Sender | None = None, limit: int = 50, now: float | None = None,
) -> dict[str, int]:
    """Deliver due rows; retry transient failures and retain permanent failures as dead letters."""
    if sender is None:
        from .hub_usage import record_adaptation_by_id
        sender = record_adaptation_by_id
    current = time.time() if now is None else float(now)
    stats = {"sent": 0, "retry": 0, "discard": 0}
    with _lock, _connect() as conn:
        rows = conn.execute(
            """
            SELECT application_id, memory_id, payload_json, attempts
            FROM pending_outcomes
            WHERE state = 'pending' AND next_attempt_at <= ?
            ORDER BY created_at LIMIT ?
            """,
            (current, max(1, min(int(limit), 500))),
        ).fetchall()
        for row in rows:
            try:
                result = sender(row["memory_id"], json.loads(row["payload_json"]), headers)
            except Exception as exc:
                logger.debug("outcome delivery raised: %s", type(exc).__name__)
                result = "retry"
            if result == "sent":
                conn.execute("DELETE FROM pending_outcomes WHERE application_id = ?", (row["application_id"],))
                stats["sent"] += 1
            elif result == "discard":
                conn.execute(
                    """UPDATE pending_outcomes SET state = 'dead', updated_at = ?,
                       last_error = 'Hub permanently rejected outcome' WHERE application_id = ?""",
                    (current, row["application_id"]),
                )
                stats["discard"] += 1
            else:
                attempts = int(row["attempts"]) + 1
                delay = min(3600.0, float(2 ** min(attempts, 12)))
                conn.execute(
                    """UPDATE pending_outcomes SET attempts = ?, next_attempt_at = ?, updated_at = ?,
                       last_error = 'Transient delivery failure' WHERE application_id = ?""",
                    (attempts, current + delay, current, row["application_id"]),
                )
                stats["retry"] += 1
    return stats


def outcome_queue_counts() -> dict[str, int]:
    with _lock, _connect() as conn:
        rows = conn.execute("SELECT state, count(*) AS count FROM pending_outcomes GROUP BY state").fetchall()
    result = {"pending": 0, "dead": 0}
    result.update({str(row["state"]): int(row["count"]) for row in rows})
    return result
