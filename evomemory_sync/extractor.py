"""LLM → structured EvoMemory JSON (OpenAI-compatible chat API)."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return v.strip() if isinstance(v, str) and v.strip() else default


def _extractor_base_url() -> str:
    return _env("EVOMEMORY_EXTRACTOR_BASE_URL", "https://api.siliconflow.cn/v1").rstrip("/")


def _extractor_api_key() -> str:
    return _env("EVOMEMORY_EXTRACTOR_API_KEY") or _env("SILICONFLOW_API_KEY")


def _extractor_model() -> str:
    return _env("EVOMEMORY_EXTRACTOR_MODEL")


def _parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


SYSTEM_PROMPT = """You are EvoMemory's extraction model. Output ONE JSON object only (no markdown).

Classify the agent run for a shared research memory hub:

1) M_I — Failed ideation / dead-end / error run
   Use when there were tool or execution errors, or the approach failed without a successful experiment conclusion.
   Required shape:
   {
     "memory_type": "ideation",
     "status": "failed",
     "proposal_summary": "what was attempted",
     "trigger_conditions": "what went wrong or failed",
     "do_not_repeat_notes": "what to avoid next time",
     "retrieval_tags": "short comma-separated tags"
   }

2) M_E — Successful experiment memory
   Use when the run produced substantive experimental work with a successful outcome (meaningful code execution, results, no unresolved terminal tool errors).
   Required shape:
   {
     "memory_type": "experiment",
     "task_description": "title + research question / context",
     "data_summary": "data / method summary",
     "model_strategy": "model / algorithm / key metrics",
     "environment_constraints": "conclusion, artifacts paths, env notes",
     "status": "completed"
   }

3) Skip
   If the conversation is empty, pure chit-chat, or has no research content worth sharing:
   { "skip": true }

Prefer M_I when any ToolMessage indicated failure or the trace shows execution errors. Prefer M_E only for clear successful experiment closure.

Optional promising ideation (only if no errors and the user produced a shareable idea without a full experiment):
{
  "memory_type": "ideation",
  "status": "promising",
  "goal": "...",
  "title": "...",
  "core_idea": "...",
  "why_promising": "...",
  "requirements": "...",
  "validation_plan": "..."
}
"""


def call_llm_to_extract_json(context: dict[str, Any]) -> dict[str, Any] | None:
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

    user_content = json.dumps(context, ensure_ascii=False, indent=2)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    def _do_request(use_json_format: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
        }
        if use_json_format:
            payload["response_format"] = {"type": "json_object"}
        r = requests.post(url, json=payload, headers=headers, timeout=timeout, verify=False)
        r.raise_for_status()
        data = r.json()
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
        return _parse_json_object(str(raw))

    try:
        try:
            return _do_request(True)
        except Exception as e1:
            logger.debug("evomemory_sync: json_object mode failed (%s), retrying without response_format", e1)
            return _do_request(False)
    except Exception as e:
        logger.warning("evomemory_sync: LLM extraction failed: %s", e)
        return None
