"""Push EvoScientist-style memory JSON to EvoMemory Hub (OpenAI-style payloads → REST)."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import requests
import requests.exceptions
import urllib3

from .constants import BROWSER_UA, DEFAULT_ACCEPT, DEFAULT_ACCEPT_LANGUAGE
from .env_loader import env, env_bool as _env_bool
from .extraction_fields import normalize_llm_extraction
from .hub_url import get_base_url

logger = logging.getLogger(__name__)


def tls_verify() -> bool:
    """Default secure TLS verification; opt-out only for debugging."""
    return not _env_bool("EVOMEMORY_INSECURE", False)


def _max_upload_body_bytes() -> int:
    raw = env("EVOMEMORY_UPLOAD_MAX_BODY_BYTES", "524288")
    try:
        return max(4096, int(raw))
    except ValueError:
        return 524288


def hub_bearer_token() -> str:
    """Bearer token for Hub writes/reads. ``EVOMEMORY_API_TOKEN`` wins; ``EVOMEMORY_AGENT_TOKEN`` is fallback."""
    return (env("EVOMEMORY_API_TOKEN") or env("EVOMEMORY_AGENT_TOKEN") or "").strip()


def hub_headers() -> dict[str, str]:
    token = hub_bearer_token()
    if not token:
        raise RuntimeError(
            "EVOMEMORY_API_TOKEN (or EVOMEMORY_AGENT_TOKEN) is not set"
        )
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": BROWSER_UA,
        "Accept": DEFAULT_ACCEPT,
        "Accept-Language": DEFAULT_ACCEPT_LANGUAGE,
    }


def json_to_ideation_payload(data: dict[str, Any]) -> dict[str, Any]:
    mem_type = str(data.get("memory_type") or "").strip().lower()
    if mem_type != "ideation":
        raise ValueError("not an ideation JSON")

    goal = str(data.get("goal") or "").strip()
    title = str(data.get("title") or "").strip()
    core = str(data.get("core_idea") or "").strip()
    rationale = str(data.get("rationale") or data.get("why_promising") or "").strip()
    req = str(data.get("requirements") or "").strip()
    validation = str(data.get("validation_plan") or data.get("minimal_validation_plan") or "").strip()
    return {
        "goal": goal or "(unknown goal)",
        "title": title or "(untitled)",
        "core_idea": core or "(empty)",
        "rationale": rationale or None,
        "requirements": req or "(empty)",
        "validation_plan": validation or None,
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
    proposal_context = proposal or "(untitled experiment)"
    raw_outcome = str(data.get("outcome") or "inconclusive").strip().lower()
    outcome = {
        "failed": "failure",
        "fail": "failure",
        "failure": "failure",
        "successful": "success",
        "completed": "success",
        "success": "success",
        "partial": "partial",
        "inconclusive": "inconclusive",
    }.get(raw_outcome, "inconclusive")
    result_summary = str(data.get("result_summary") or data.get("result") or "(not recorded)").strip()
    conclusion = str(data.get("conclusion") or "(not recorded)").strip()
    failure_reason = str(data.get("failure_reason") or "").strip() or None
    if outcome == "failure" and not failure_reason:
        failure_reason = (
            result_summary
            if result_summary and result_summary != "(not recorded)"
            else conclusion
            if conclusion and conclusion != "(not recorded)"
            else "failure recorded without a detailed reason"
        )
    out: dict[str, Any] = {
        "proposal_context": proposal_context,
        "data_strategy": data_s or "(unknown)",
        "model_strategy": model_s or "(unknown)",
        "environment": env_s or "(none)",
        "outcome": outcome,
        "result_summary": result_summary,
        "metrics": data.get("metrics") if isinstance(data.get("metrics"), dict) else {},
        "failure_reason": failure_reason,
        "conclusion": conclusion,
        "evidence_type": str(data.get("evidence_type") or "not_applicable").strip(),
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

    # Suppress urllib3 InsecureRequestWarning only when verify=False
    _tls = tls_verify()
    if not _tls:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    raw_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    limit = _max_upload_body_bytes()
    if len(raw_body) > limit:
        raise RuntimeError(
            f"Request body size {len(raw_body)} bytes exceeds limit {limit} "
            f"(set EVOMEMORY_UPLOAD_MAX_BODY_BYTES to raise; default 524288)."
        )

    transient_net = (
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
        requests.exceptions.ChunkedEncodingError,
    )

    for attempt in range(max_retries):
        try:
            r = requests.post(url, data=raw_body, headers=req_headers, timeout=timeout, verify=_tls)
        except transient_net as e:
            last_exc = e
            if attempt < max_retries - 1:
                time.sleep(2**attempt)
                continue
            raise

        if 200 <= r.status_code < 300:
            return r.json()

        try:
            detail = r.json()
        except Exception:
            detail = r.text
        err = RuntimeError(f"HTTP {r.status_code}: {detail}")

        if 500 <= r.status_code < 600:
            last_exc = err
            if attempt < max_retries - 1:
                time.sleep(2**attempt)
                continue
            raise last_exc
        raise err


def put_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    """PUT JSON with the same retry semantics as post_json."""
    timeout = float(env("EVOMEMORY_API_TIMEOUT_SECONDS", "120") or "120")
    max_retries = 2
    last_exc: Exception | None = None
    req_headers = dict(headers)
    req_headers.setdefault("User-Agent", BROWSER_UA)
    req_headers.setdefault("Accept", DEFAULT_ACCEPT)
    req_headers.setdefault("Accept-Language", DEFAULT_ACCEPT_LANGUAGE)
    req_headers.setdefault("Content-Type", "application/json")

    _tls = tls_verify()
    if not _tls:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    raw_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    limit = _max_upload_body_bytes()
    if len(raw_body) > limit:
        raise RuntimeError(
            f"Request body size {len(raw_body)} bytes exceeds limit {limit} "
            f"(set EVOMEMORY_UPLOAD_MAX_BODY_BYTES to raise; default 524288)."
        )

    transient_net = (
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
        requests.exceptions.ChunkedEncodingError,
    )

    for attempt in range(max_retries):
        try:
            r = requests.put(url, data=raw_body, headers=req_headers, timeout=timeout, verify=_tls)
        except transient_net as e:
            last_exc = e
            if attempt < max_retries - 1:
                time.sleep(2**attempt)
                continue
            raise

        if 200 <= r.status_code < 300:
            return r.json()

        try:
            detail = r.json()
        except Exception:
            detail = r.text
        err = RuntimeError(f"HTTP {r.status_code}: {detail}")

        if 500 <= r.status_code < 600:
            last_exc = err
            if attempt < max_retries - 1:
                time.sleep(2**attempt)
                continue
            raise last_exc
        raise err


def json_to_recipe_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Map recipe extraction JSON to Hub upload payload."""
    from .recipe_format import prepare_recipe_hub_fields

    mem_type = str(data.get("memory_type") or "").strip().lower()
    if mem_type != "recipe":
        raise ValueError("not a recipe JSON")
    fields = prepare_recipe_hub_fields(data)
    out: dict[str, Any] = {
        "trigger": fields["trigger"] or "(unknown trigger)",
        "problem": fields["problem"] or "(unknown problem)",
        "solution": fields["solution"] or "(unknown solution)",
        "env_snapshot": fields["env_snapshot"] or "(none)",
        "result": fields["result"] or "(none)",
        "tags": fields["tags"],
    }
    # Optional parent linking
    pi = data.get("parent_ideation_id") or data.get("parent_ideation")
    if pi is not None and str(pi).strip():
        out["parent_ideation_id"] = str(pi).strip()
    pe = data.get("parent_experiment_id") or data.get("parent_experiment")
    if pe is not None and str(pe).strip():
        out["parent_experiment_id"] = str(pe).strip()
    # Internal attribution metadata is intentionally not part of the Hub REST
    # body. Application-bound outcomes carry trusted usage evidence separately.
    return out


def upload_memory_record(data: dict[str, Any]) -> dict[str, Any] | None:
    """Map extractor JSON to Hub upload endpoints. Returns API JSON or None if skipped."""
    if not isinstance(data, dict) or data.get("skip") is True:
        return None

    data = normalize_llm_extraction(data)

    from .upload_curator import upload_memory_record_with_agent

    return upload_memory_record_with_agent(data)
