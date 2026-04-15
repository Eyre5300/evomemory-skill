"""Push EvoScientist-style memory JSON to EvoMemory Hub (OpenAI-style payloads → REST)."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
DEFAULT_ACCEPT = "application/json"
DEFAULT_ACCEPT_LANGUAGE = "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7"


def env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return v.strip() if isinstance(v, str) and v.strip() else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def tls_verify() -> bool:
    """Default secure TLS verification; opt-out only for debugging."""
    return not _env_bool("EVOMEMORY_INSECURE", False)


def get_base_url() -> str:
    from .hub_url import DEFAULT_PUBLIC_HUB, resolve_working_hub_base_url_cached

    base = env("EVOMEMORY_API_BASE_URL", DEFAULT_PUBLIC_HUB).strip()
    if not base:
        base = DEFAULT_PUBLIC_HUB
    return resolve_working_hub_base_url_cached(base, default=DEFAULT_PUBLIC_HUB)


def hub_headers() -> dict[str, str]:
    token = env("EVOMEMORY_API_TOKEN")
    if not token:
        raise RuntimeError("EVOMEMORY_API_TOKEN is not set")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": BROWSER_UA,
        "Accept": DEFAULT_ACCEPT,
        "Accept-Language": DEFAULT_ACCEPT_LANGUAGE,
    }


def json_to_ideation_payload(data: dict[str, Any]) -> dict[str, Any]:
    mem_type = str(data.get("memory_type") or "").strip().lower()
    status = str(data.get("status") or "").strip().lower()
    if mem_type != "ideation":
        raise ValueError("not an ideation JSON")

    if status == "failed":
        proposal = str(data.get("proposal_summary") or "").strip()
        trigger = str(data.get("trigger_conditions") or data.get("trigger") or "").strip()
        do_not = str(
            data.get("do_not_repeat_notes")
            or data.get("do_not_repeat")
            or data.get("countermeasures")
            or ""
        ).strip()
        tags = str(data.get("retrieval_tags") or data.get("tags") or "").strip()
        first_line = (proposal.split("\n")[0] or "Failed proposal").strip()
        core_parts = [proposal]
        if trigger:
            core_parts.append("\n\nTrigger: " + trigger)
        if do_not:
            core_parts.append("\n\nDo-not-repeat: " + do_not)
        return {
            "goal": "Failed ideation",
            "type": "failed",
            "title": first_line[:200],
            "core_idea": "".join(core_parts).strip(),
            "requirements": tags or "(none)",
        }

    goal = str(data.get("goal") or "").strip()
    title = str(data.get("title") or "").strip()
    core = str(data.get("core_idea") or "").strip()
    why = str(data.get("why_promising") or "").strip()
    req = str(data.get("requirements") or "").strip()
    validation = str(data.get("validation_plan") or data.get("minimal_validation_plan") or "").strip()
    core_idea = (core + ("\n\nWhy promising: " + why if why else "")).strip()
    requirements = (req + ("\n\nValidation plan: " + validation if validation else "")).strip()
    return {
        "goal": goal or "(unknown goal)",
        "type": "promising",
        "title": title or "(untitled)",
        "core_idea": core_idea or "(empty)",
        "requirements": requirements or "(empty)",
    }


def json_to_experiment_payload(data: dict[str, Any]) -> dict[str, Any]:
    mem_type = str(data.get("memory_type") or "").strip().lower()
    if mem_type != "experiment":
        raise ValueError("not an experiment JSON")
    proposal = str(
        data.get("task_description")
        or data.get("proposal_context")
        or data.get("research_task")
        or ""
    ).strip()
    data_s = str(data.get("data_summary") or data.get("data_strategy") or "").strip()
    model_s = str(data.get("model_summary") or data.get("model_strategy") or "").strip()
    env_s = str(data.get("environment_constraints") or data.get("environment") or "").strip()
    status = str(data.get("status") or "").strip()
    if status:
        env_s = (env_s + "\n\nStatus: " + status).strip()
    out: dict[str, Any] = {
        "proposal_context": proposal or "(untitled experiment)",
        "data_strategy": data_s or "(unknown)",
        "model_strategy": model_s or "(unknown)",
        "environment": env_s or "(none)",
    }
    pid = data.get("parent_ideation_id") or data.get("parent_ideation")
    if pid is not None and str(pid).strip():
        out["parent_ideation_id"] = str(pid).strip()
    hw = data.get("hardware_requirements")
    if hw is not None and str(hw).strip():
        out["hardware_requirements"] = str(hw).strip()
    sw = data.get("software_dependencies")
    if sw is not None and str(sw).strip():
        out["software_dependencies"] = str(sw).strip()
    return out


def json_to_workflow_payload(data: dict[str, Any]) -> dict[str, Any]:
    mem_type = str(data.get("memory_type") or "").strip().lower()
    if mem_type != "workflow":
        raise ValueError("not a workflow JSON")
    title = str(data.get("title") or "").strip() or "(untitled workflow)"
    desc = str(data.get("description") or "").strip() or "(none)"
    prompts = str(
        data.get("prompt_templates") or data.get("prompt_template") or data.get("prompts") or ""
    ).strip() or "(none)"
    tools_s = str(data.get("tool_configuration") or data.get("tools") or "").strip() or "(none)"
    out: dict[str, Any] = {
        "title": title[:255],
        "description": desc,
        "prompt_templates": prompts,
        "tool_configuration": tools_s,
    }
    pe = data.get("parent_experiment_id") or data.get("parent_experiment")
    if pe is not None and str(pe).strip():
        out["parent_experiment_id"] = str(pe).strip()
    pi = data.get("parent_ideation_id") or data.get("parent_ideation")
    if pi is not None and str(pi).strip():
        out["parent_ideation_id"] = str(pi).strip()
    return out


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    timeout = float(env("EVOMEMORY_API_TIMEOUT_SECONDS", "120") or "120")
    max_retries = 2
    last_exc: Exception | None = None
    req_headers = dict(headers)
    req_headers.setdefault("User-Agent", BROWSER_UA)
    req_headers.setdefault("Accept", DEFAULT_ACCEPT)
    req_headers.setdefault("Accept-Language", DEFAULT_ACCEPT_LANGUAGE)
    req_headers.setdefault("Content-Type", "application/json")

    for attempt in range(max_retries):
        try:
            r = requests.post(url, json=payload, headers=req_headers, timeout=timeout, verify=tls_verify())
            if 200 <= r.status_code < 300:
                return r.json()
            try:
                detail = r.json()
            except Exception:
                detail = r.text
            raise RuntimeError(f"HTTP {r.status_code}: {detail}")
        except Exception as e:
            last_exc = e
            if attempt < max_retries - 1:
                time.sleep(2**attempt)
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("post_json failed")


def upload_memory_record(data: dict[str, Any]) -> dict[str, Any] | None:
    """Map extractor JSON to Hub upload endpoints. Returns API JSON or None if skipped."""
    if not isinstance(data, dict) or data.get("skip") is True:
        return None

    base = get_base_url()
    headers = hub_headers()
    mem_type = str(data.get("memory_type") or "").strip().lower()

    if mem_type == "ideation":
        body = json_to_ideation_payload(data)
        url = f"{base}/memory/ideation/upload"
    elif mem_type == "experiment":
        body = json_to_experiment_payload(data)
        url = f"{base}/memory/experiment/upload"
    elif mem_type == "workflow":
        body = json_to_workflow_payload(data)
        url = f"{base}/memory/workflow/upload"
    else:
        logger.debug("evomemory_sync: unknown memory_type %r, skip upload", data.get("memory_type"))
        return None

    return post_json(url, body, headers)
