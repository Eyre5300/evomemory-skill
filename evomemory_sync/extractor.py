"""LLM → structured EvoMemory JSON (OpenAI-compatible chat API)."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import requests
import urllib3

from .uploader import tls_verify

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


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _sanitize_text(text: str) -> str:
    s = text
    # Secrets / tokens / API keys (generic and provider-specific)
    s = re.sub(r"(?i)\b(sk|api[_-]?key|access[_-]?token|secret|password|passwd)\b\s*[:=]\s*['\"]?[A-Za-z0-9_\-\.=+/]{8,}['\"]?", r"\1=[REDACTED]", s)
    s = re.sub(r"\bsk-[A-Za-z0-9]{10,}\b", "[REDACTED]", s)
    s = re.sub(r"\b(ghp|github_pat|xoxb|xoxp|AKIA)[A-Za-z0-9_\-]{8,}\b", "[REDACTED]", s)
    # File paths (Windows + Unix-like absolute paths)
    s = re.sub(r"[A-Za-z]:\\(?:[^\\\s\"']+\\)*[^\\\s\"']*", "[REDACTED]", s)
    s = re.sub(r"/(?:Users|home|root|var|tmp|private|opt|etc)/[^\s\"']+", "[REDACTED]", s)
    # IPv4
    s = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[REDACTED]", s)
    # MAC
    s = re.sub(r"\b(?:[0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}\b", "[REDACTED]", s)
    # Email
    s = re.sub(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b", "[REDACTED]", s)
    return s


def _sanitize_context(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _sanitize_context(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_context(v) for v in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    return value


def _parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


SYSTEM_PROMPT = """You are EvoMemory's extraction model. Output ONE JSON object only (no markdown).

Classify the agent run for a shared research memory hub:

Core safety rule (MANDATORY SANITIZATION BEFORE OUTPUT):
- Before generating the JSON, sanitize all sensitive information from the provided context (code, commands, logs, paths, errors, etc.).
- Replace any detected sensitive value with exactly: [REDACTED]
- Sensitive data that MUST be redacted includes:
  1) API keys, access tokens, passwords, secrets, credentials of any kind.
  2) Local absolute filesystem paths (e.g. C:\\Users\\xxx\\..., /Users/xxx/..., /home/xxx/...).
  3) Real IP addresses, MAC addresses, personal emails, and real person names.
- Never emit raw secrets, raw local machine identifiers, or personally identifying information.
- Keep the original JSON schema exactly as required below; only redact sensitive substrings inside field values.

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
     "status": "completed",
     "parent_ideation_id": null,
     "hardware_requirements": null,
     "software_dependencies": null
   }
   Include parent_ideation_id only if the trace references a specific prior ideation memory UUID on the Hub; otherwise omit or use null.

3) Skip
   If the conversation is empty, pure chit-chat, or has no research content worth sharing:
   { "skip": true }

Prefer M_I when any ToolMessage indicated failure or the trace shows execution errors. Prefer M_E only for clear successful experiment closure.
Use M_W rarely, only when the run is mainly about defining or refining a reusable workflow (prompts + tools). If both an experiment outcome and a workflow are present, prefer M_E and omit M_W unless the user explicitly asked to save the workflow recipe.

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

4) M_W — Workflow memory (reusable agent configuration)
   Use when the trace clearly documents prompt templates, tool wiring, or a repeatable workflow worth sharing.
   Optional links: set parent IDs only if the conversation references existing Hub memory UUIDs (otherwise omit or null).
   {
     "memory_type": "workflow",
     "title": "...",
     "description": "...",
     "prompt_templates": "main prompts / system instructions (redacted)",
     "tool_configuration": "tools, MCP, or agent graph notes (redacted)",
     "parent_ideation_id": null,
     "parent_experiment_id": null
   }
"""


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
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
        }
        if use_json_format:
            payload["response_format"] = {"type": "json_object"}
        r = requests.post(url, json=payload, headers=headers, timeout=timeout, verify=tls_verify())
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
