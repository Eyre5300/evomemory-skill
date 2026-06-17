"""Semantic dedup before upload: search similar own/others, update or skip when appropriate."""

from __future__ import annotations

import logging
from typing import Any, Literal

import requests

from .env_loader import env as _env, env_bool as _env_bool
from .hub_url import get_base_url
from .uploader import hub_headers, post_json, put_json, tls_verify

logger = logging.getLogger(__name__)

UploadAction = Literal["upload", "update", "skip_duplicate"]


def semantic_dedup_enabled() -> bool:
    raw = _env("EVOMEMORY_UPLOAD_SEMANTIC_DEDUP", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _update_threshold() -> float:
    raw = _env("EVOMEMORY_UPLOAD_UPDATE_SIMILARITY", "0.82")
    try:
        return max(0.5, min(0.99, float(raw)))
    except ValueError:
        return 0.82


def _skip_others_threshold() -> float:
    raw = _env("EVOMEMORY_UPLOAD_SKIP_SIMILARITY", "0.90")
    try:
        return max(0.5, min(0.99, float(raw)))
    except ValueError:
        return 0.90


def _similarity(item: dict[str, Any]) -> float:
    raw = item.get("similarity_score", item.get("similarity"))
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def build_search_query(mem_type: str, payload: dict[str, Any]) -> str:
    t = mem_type.strip().lower()
    if t == "ideation":
        parts = [
            payload.get("goal"),
            payload.get("title"),
            payload.get("core_idea"),
            payload.get("requirements"),
        ]
    elif t == "experiment":
        parts = [
            payload.get("proposal_context"),
            payload.get("data_strategy"),
            payload.get("model_strategy"),
            payload.get("environment"),
        ]
    elif t == "workflow":
        parts = [
            payload.get("title"),
            payload.get("description"),
            payload.get("prompt_templates"),
            payload.get("tool_configuration"),
        ]
    elif t == "recipe":
        parts = [
            payload.get("trigger"),
            payload.get("problem"),
            payload.get("solution"),
            payload.get("env_snapshot"),
            payload.get("result"),
            payload.get("tags"),
        ]
    else:
        parts = []
    return "\n".join(str(p).strip() for p in parts if p and str(p).strip())


def fetch_current_user_id(headers: dict[str, str]) -> str | None:
    base = get_base_url()
    timeout = float(_env("EVOMEMORY_API_TIMEOUT_SECONDS", "30") or "30")
    try:
        r = requests.get(
            f"{base}/auth/me",
            headers=headers,
            timeout=timeout,
            verify=tls_verify(),
        )
        if r.status_code >= 400:
            return None
        data = r.json()
        uid = data.get("id") or data.get("user_id")
        return str(uid).strip() if uid else None
    except Exception as e:
        logger.debug("fetch_current_user_id failed: %s", e)
        return None


def search_similar(
    mem_type: str,
    query_text: str,
    headers: dict[str, str],
    *,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    q = (query_text or "").strip()
    if not q:
        return []
    base = get_base_url()
    timeout = float(_env("EVOMEMORY_API_TIMEOUT_SECONDS", "60") or "60")
    url = f"{base}/memory/{mem_type}/search"
    body = {"query_text": q, "top_k": max(3, min(100, top_k)), "min_similarity": 0.0}
    try:
        r = requests.post(url, json=body, headers=headers, timeout=timeout, verify=tls_verify())
        if r.status_code >= 400:
            logger.warning("semantic dedup search failed HTTP %s for %s", r.status_code, mem_type)
            return []
        data = r.json()
        results = data.get("results") or []
        return [x for x in results if isinstance(x, dict)]
    except Exception as e:
        logger.warning("semantic dedup search error: %s", e)
        return []


def decide_upload_action(
    mem_type: str,
    payload: dict[str, Any],
    headers: dict[str, str],
) -> tuple[UploadAction, str | None, dict[str, Any] | None, list[dict[str, Any]]]:
    """
    Returns (action, memory_id_to_update, own_top1, others_top3).
    - update: PUT existing own memory when top1 own similarity >= threshold
    - skip_duplicate: community already has very similar memory (no own match)
    - upload: create new row
    """
    if not semantic_dedup_enabled():
        return "upload", None, None, []

    query = build_search_query(mem_type, payload)
    if not query:
        return "upload", None, None, []

    results = search_similar(mem_type, query, headers, top_k=10)
    if not results:
        return "upload", None, None, []

    my_id = fetch_current_user_id(headers)
    own: list[dict[str, Any]] = []
    others: list[dict[str, Any]] = []
    for row in results:
        author = str(row.get("author_user_id") or row.get("owner_user_id") or "").strip()
        if my_id and author and author == my_id:
            own.append(row)
        else:
            others.append(row)

    own_top1 = own[0] if own else None
    others_top3 = others[:3]

    if own_top1 and _similarity(own_top1) >= _update_threshold():
        mid = str(own_top1.get("id") or "").strip()
        logger.info(
            "semantic dedup: update own %s %s (sim=%.3f)",
            mem_type,
            mid,
            _similarity(own_top1),
        )
        return "update", mid or None, own_top1, others_top3

    if not own_top1 and others_top3:
        best_other = max(_similarity(r) for r in others_top3)
        if best_other >= _skip_others_threshold():
            logger.info(
                "semantic dedup: skip upload %s (community sim=%.3f >= %.3f)",
                mem_type,
                best_other,
                _skip_others_threshold(),
            )
            return "skip_duplicate", None, None, others_top3

    if own_top1:
        logger.info(
            "semantic dedup: new upload %s (own sim=%.3f below update threshold %.3f)",
            mem_type,
            _similarity(own_top1),
            _update_threshold(),
        )
    return "upload", None, own_top1, others_top3


def update_url(mem_type: str, memory_id: str) -> str:
    base = get_base_url()
    return f"{base}/memory/{mem_type}/{memory_id}/update"


def upload_or_update_memory_record(
    mem_type: str,
    payload: dict[str, Any],
    headers: dict[str, str],
) -> dict[str, Any]:
    action, update_id, own_top1, others_top3 = decide_upload_action(mem_type, payload, headers)

    if action == "skip_duplicate":
        return {
            "status": "skipped",
            "reason": "similar_community_memory_exists",
            "memory_type": mem_type,
            "similar_others": [
                {
                    "id": r.get("id"),
                    "similarity": _similarity(r),
                    "author_user_id": r.get("author_user_id"),
                }
                for r in others_top3
            ],
        }

    if action == "update" and update_id and mem_type in ("ideation", "experiment", "recipe"):
        url = update_url(mem_type, update_id)
        result = put_json(url, payload, headers)
        result["action"] = "updated"
        result["id"] = update_id
        return result

    if action == "update" and update_id:
        logger.info("semantic dedup: update unsupported for %s, uploading new", mem_type)

    if mem_type == "ideation":
        url = f"{get_base_url()}/memory/ideation/upload"
    elif mem_type == "experiment":
        url = f"{get_base_url()}/memory/experiment/upload"
    elif mem_type == "workflow":
        url = f"{get_base_url()}/memory/workflow/upload"
    elif mem_type == "recipe":
        url = f"{get_base_url()}/memory/recipe/upload"
    else:
        raise ValueError(f"unknown memory_type {mem_type!r}")

    result = post_json(url, payload, headers)
    result["action"] = "created"
    if own_top1:
        result["similar_own"] = {
            "id": own_top1.get("id"),
            "similarity": _similarity(own_top1),
        }
    if others_top3:
        result["similar_others"] = [
            {"id": r.get("id"), "similarity": _similarity(r)} for r in others_top3
        ]
    return result
