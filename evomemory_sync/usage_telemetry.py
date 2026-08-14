"""Privacy-minimized JSONL telemetry for optional LLM token accounting."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .env_loader import env as _env


def _integer(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def record_llm_usage(stage: str, model: str, response_data: dict[str, Any]) -> None:
    """Append one usage-only record when ``EVOMEMORY_USAGE_LOG_FILE`` is set.

    The record deliberately excludes prompts, completions, tokens, account data,
    and request headers.  A single ``os.write`` to an append-only descriptor keeps
    short records intact when several detached workers finish concurrently.
    Telemetry must never interrupt extraction or upload.
    """
    target = _env("EVOMEMORY_USAGE_LOG_FILE").strip()
    if not target:
        return
    usage = response_data.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    input_tokens = _integer(usage.get("prompt_tokens", usage.get("input_tokens")))
    output_tokens = _integer(usage.get("completion_tokens", usage.get("output_tokens")))
    total_tokens = _integer(usage.get("total_tokens")) or input_tokens + output_tokens
    record = {
        "schema_version": 1,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "stage": str(stage or "unknown")[:80],
        "model": str(model or "unknown")[:200],
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "agent_instance_id": _env("EVOMEMORY_AGENT_INSTANCE_ID")[:200],
    }
    try:
        path = Path(target).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        fd = os.open(str(path), os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except Exception:
        return
