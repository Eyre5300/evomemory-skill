"""LLM → structured EvoMemory JSON (OpenAI-compatible chat API)."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import requests
from .env_loader import env as _env, env_bool as _env_bool
from .extraction_fields import EXTRACTOR_SYSTEM_PROMPT
from .sanitize import sanitize_context as _sanitize_context
from .usage_telemetry import record_llm_usage

logger = logging.getLogger(__name__)


def _extractor_base_url() -> str:
    return _env("EVOMEMORY_EXTRACTOR_BASE_URL", "https://api.siliconflow.cn/v1").rstrip("/")


def _extractor_api_key() -> str:
    return _env("EVOMEMORY_EXTRACTOR_API_KEY") or _env("SILICONFLOW_API_KEY")


def _extractor_model() -> str:
    return _env("EVOMEMORY_EXTRACTOR_MODEL")


def _tls_verify() -> bool:
    """Match ``evomemory_sync.uploader.tls_verify`` (kept local so file-level tests can load this module)."""
    return not _env_bool("EVOMEMORY_INSECURE", False)


def _parse_json_object(text: str) -> dict[str, Any]:
    """Parse model output: optional markdown fence, then a single JSON object."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*\n?", text, re.IGNORECASE)
    if m:
        inner_start = m.end()
        inner_end = text.rfind("```")
        if inner_end > inner_start:
            text = text[inner_start:inner_end].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _call_llm_to_extract_json(context: dict[str, Any]) -> dict[str, Any] | None:
    """Call configured chat model; return parsed dict or None if misconfigured / request failed."""
    api_key = _extractor_api_key()
    model = _extractor_model()
    if not api_key or not model:
        logger.debug(
            "evomemory_sync: extractor disabled (set EVOMEMORY_EXTRACTOR_MODEL and "
            "EVOMEMORY_EXTRACTOR_API_KEY or SILICONFLOW_API_KEY)"
        )
        return None

    base = _extractor_base_url()
    url = f"{base}/chat/completions"
    timeout = float(_env("EVOMEMORY_EXTRACTOR_TIMEOUT_SECONDS", _env("EVOMEMORY_API_TIMEOUT_SECONDS", "120")) or "120")

    sanitize_enabled = _env_bool("EVOMEMORY_SYNC_SEND_RAW_CONTEXT", False) is False
    safe_context = _sanitize_context(context) if sanitize_enabled else context
    user_content = json.dumps(safe_context, ensure_ascii=False, indent=2)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    def _do_request(use_json_format: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": EXTRACTOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
            # Qwen/DashScope: empty content is common when thinking stays on.
            "enable_thinking": False,
        }
        if use_json_format:
            payload["response_format"] = {"type": "json_object"}
        r = requests.post(url, json=payload, headers=headers, timeout=timeout, verify=_tls_verify())
        r.raise_for_status()
        try:
            data = r.json()
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("evomemory_sync: LLM returned non-JSON (status %s): %.200s", r.status_code, r.text[:200])
            raise RuntimeError(f"LLM response is not valid JSON: {exc}") from exc
        record_llm_usage("extractor", model, data)
        choice = data["choices"][0]["message"]
        raw = choice.get("content") or ""
        if isinstance(raw, list):
            parts: list[str] = []
            for block in raw:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                elif isinstance(block, str):
                    parts.append(block)
            raw = "\n".join(parts)
        raw_s = str(raw).strip()
        if not raw_s:
            raise RuntimeError("LLM returned empty content")
        return _parse_json_object(raw_s)

    # Retry transient empty/parse failures — a silent None drop loses successful runs.
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            try:
                return _do_request(True)
            except Exception as e1:
                last_err = e1
                logger.debug(
                    "evomemory_sync: json_object mode failed (%s), retrying without response_format",
                    e1,
                )
                return _do_request(False)
        except Exception as e:
            last_err = e
            logger.warning(
                "evomemory_sync: LLM extraction attempt %d/3 failed: %s",
                attempt,
                e,
            )
            if attempt < 3:
                import time as _time

                _time.sleep(attempt)
    logger.warning("evomemory_sync: LLM extraction failed: %s", last_err)
    return None
