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


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _tls_verify() -> bool:
    """Match ``evomemory_sync.uploader.tls_verify`` (kept local so file-level tests can load this module)."""
    return not _env_bool("EVOMEMORY_INSECURE", False)


def _sanitize_text(text: str) -> str:
    s = text
    # Secrets / tokens / API keys (generic and provider-specific).
    # Use (?<![A-Za-z0-9_]) instead of \b so keys like `api_key=` still match after underscores.
    _kw = r"(sk|api[_-]?key|access[_-]?token|secret|password|passwd)"
    s = re.sub(
        rf"(?i)(?<![A-Za-z0-9_]){_kw}\s*[:=]\s*['\"]?[A-Za-z0-9_\-\.=+/]{{8,}}['\"]?",
        r"\1=[REDACTED]",
        s,
    )
    s = re.sub(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9]{10,}(?![A-Za-z0-9_])", "[REDACTED]", s)
    s = re.sub(
        r"(?<![A-Za-z0-9_])(ghp|github_pat|xoxb|xoxp|AKIA)[A-Za-z0-9_\-]{8,}(?![A-Za-z0-9_])",
        "[REDACTED]",
        s,
    )
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


SYSTEM_PROMPT = """You are EvoMemory's extraction model. Reply with ONE JSON object only (no markdown fences).

Goal: classify the agent trace for a public research memory hub.

Sanitization (mandatory before you write JSON):
- Redact secrets, tokens, passwords, local absolute paths, IPs, MACs, emails, real names → use exactly [REDACTED] inside string values.
- Keep valid JSON keys/shapes below; never leak raw credentials.

Choose exactly one output type:

A) Skip — no research value or empty/chit-chat: {"skip": true}

B) Failed ideation — tool errors, failed runs, dead ends:
   {"memory_type":"ideation","status":"failed","proposal_summary","trigger_conditions","do_not_repeat_notes","retrieval_tags"}

C) Promising ideation — shareable idea, no blocking errors:
   {"memory_type":"ideation","status":"promising","goal","title","core_idea","why_promising","requirements","validation_plan"}

D) Completed experiment — substantive successful run, no unresolved tool errors. Required keys:
   memory_type "experiment", status "completed", task_description, data_summary, model_strategy, environment_constraints;
   optional parent_ideation_id, hardware_requirements, software_dependencies (use null if unknown).

E) Workflow — mainly reusable prompts + tool wiring (rare; skip if user did not ask to save workflow). Required keys:
   memory_type "workflow", title, description, prompt_templates, tool_configuration;
   optional parent_ideation_id, parent_experiment_id (null unless Hub UUID is explicit).

Rules: Prefer failed ideation when trace shows errors. Prefer experiment only on clear success. parent_* only if a Hub UUID is explicitly referenced.

Examples (shape only; redact real secrets in your output):
{"memory_type":"ideation","status":"failed","proposal_summary":"Tried X","trigger_conditions":"Tool error Y","do_not_repeat_notes":"Avoid Z","retrieval_tags":"x,y"}
{"memory_type":"experiment","status":"completed","task_description":"Q","data_summary":"D","model_strategy":"M","environment_constraints":"E","parent_ideation_id":null,"hardware_requirements":null,"software_dependencies":null}
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
        r = requests.post(url, json=payload, headers=headers, timeout=timeout, verify=_tls_verify())
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
