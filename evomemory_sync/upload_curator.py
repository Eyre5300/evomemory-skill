"""Agent-style upload curation: search similar memories, LLM decides + refines, then upload."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Literal

from .env_loader import env as _env
from .extraction_fields import normalize_llm_extraction
from .extractor import _extractor_api_key, _extractor_model
from .upload_semantic import (
    build_search_query,
    fetch_current_user_id,
    search_similar,
    update_url,
)
from .uploader import (
    hub_headers,
    json_to_experiment_payload,
    json_to_ideation_payload,
    json_to_recipe_payload,
    json_to_workflow_payload,
    post_json,
    put_json,
)

logger = logging.getLogger(__name__)

CuratorAction = Literal["create", "update", "skip"]

CURATOR_SYSTEM_PROMPT = """You are EvoMemory's upload curator. Reply with ONE JSON object only.

You receive:
- draft_extraction: memory JSON from an agent run (may be imperfect)
- similar_own_top1: the most similar memory **already published by this user** (or null)
- similar_others_top3: up to 3 similar **other users'** public memories

Your job: decide whether to publish, and if so, **rewrite/refine** the draft into the best possible Hub entry.

Actions (choose exactly one):
- "skip": Community (or the user's existing card) already covers this; the draft adds no meaningful new detail. Do NOT upload.
- "update": The user's similar_own_top1 is the same experience; merge the draft's new facts into a **better** version and set update_memory_id to that id.
- "create": This is genuinely new compared to own + others; output a polished draft.

Output schema:
{
  "action": "create" | "update" | "skip",
  "skip_category": "duplicate" | "low_quality" | null,
  "update_memory_id": "<uuid or null>",
  "reason": "one short sentence",
  "refined": { ...same memory_type fields as draft, improved text... }
}

Rules:
- Prefer **recipe** shape when memory_type is recipe.
- For recipe, **problem** / **solution** / **env_snapshot** MUST be **complete prose strings** (not nested objects). Each paragraph must semantically cover the usual dimensions (task type, domain, constraints, state; method, parameters, rationale; creator, deps, environment) in natural language — you write the full text; upload layer does not stitch fields.
- On **update**, update_memory_id MUST equal similar_own_top1.id when provided.
- On **skip**, still include "reason"; "refined" may be omitted.
- On **skip**, set skip_category to "duplicate" only when a supplied similar card already covers it; otherwise use "low_quality".
- On **create** or **update**, "refined" MUST keep the same memory_type and include all required fields for that type.
- Make text **more specific** (versions, commands, metrics). Remove fluff. Do not invent facts absent from the draft/trace.
- If others' cards already solve the same problem and the user has nothing new, choose **skip**.
- If the draft is low quality, choose **skip** with reason.
- If `correcting_after_hub_failure` is true: the agent cited Hub experience but the run failed — prefer **update** on similar_own_top1 to merge the fix; only **skip** when the correction adds nothing new; use **create** only when no own card matches.

Examples:
{"action":"skip","update_memory_id":null,"reason":"Same Flask Blueprint fix already in similar_others_top3"}
{"action":"update","update_memory_id":"abc-...","reason":"Merge new env versions into existing recipe","refined":{"memory_type":"recipe","trigger":"...","problem":"...完整问题段落...","solution":"...完整方案段落（含理由）...","env_snapshot":"...完整环境段落...","result":"...","tags":"..."}}
{"action":"create","update_memory_id":null,"reason":"New OOM workaround not in similar results","refined":{...}}
"""


def agent_curate_enabled() -> bool:
    raw = _env("EVOMEMORY_UPLOAD_AGENT_CURATE", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _curator_llm_available() -> bool:
    return bool(_extractor_api_key() and _extractor_model())


def _draft_memory_type(draft: dict[str, Any]) -> str:
    return str(draft.get("memory_type") or draft.get("memory_kind") or "").strip().lower()


def _draft_to_payload(draft: dict[str, Any]) -> dict[str, Any]:
    mt = _draft_memory_type(draft)
    if mt == "ideation":
        return json_to_ideation_payload(draft)
    if mt == "experiment":
        return json_to_experiment_payload(draft)
    if mt == "workflow":
        return json_to_workflow_payload(draft)
    if mt == "recipe":
        return json_to_recipe_payload(draft)
    raise ValueError(f"unknown memory_type {mt!r}")


def _similarity(item: dict[str, Any] | None) -> float:
    if not item:
        return 0.0
    raw = item.get("similarity_score", item.get("similarity"))
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _curator_update_min_similarity() -> float:
    """Hard gate for LLM-proposed updates, shared with rule-based dedup by default."""
    raw = _env(
        "EVOMEMORY_CURATOR_UPDATE_MIN_SIMILARITY",
        _env("EVOMEMORY_UPLOAD_UPDATE_SIMILARITY", "0.82"),
    )
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.82


def _curator_skip_duplicate_min_similarity() -> float:
    raw = _env(
        "EVOMEMORY_CURATOR_SKIP_DUPLICATE_MIN_SIMILARITY",
        _env("EVOMEMORY_UPLOAD_SKIP_SIMILARITY", "0.90"),
    )
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.90


def _best_similar_similarity(similar_ctx: dict[str, Any]) -> float:
    candidates = [similar_ctx.get("similar_own_top1")]
    candidates.extend(similar_ctx.get("similar_others_top3") or [])
    return max((_similarity(item) for item in candidates if item), default=0.0)


def _compact_similar(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    mt_fields = (
        "id",
        "author_user_id",
        "similarity_score",
        "similarity",
        "title",
        "goal",
        "core_idea",
        "requirements",
        "proposal_context",
        "data_strategy",
        "model_strategy",
        "environment",
        "trigger",
        "problem",
        "solution",
        "env_snapshot",
        "result",
        "tags",
        "description",
    )
    out: dict[str, Any] = {}
    for k in mt_fields:
        if k in item and item[k] is not None:
            v = item[k]
            if isinstance(v, str) and len(v) > 1200:
                v = v[:1200] + "…"
            out[k] = v
    if "similarity_score" not in out and "similarity" in out:
        out["similarity_score"] = out["similarity"]
    return out or None


def gather_similar_context(
    draft: dict[str, Any],
    headers: dict[str, str],
) -> dict[str, Any]:
    mt = _draft_memory_type(draft)
    payload = _draft_to_payload(draft)
    query = build_search_query(mt, payload)
    results = search_similar(mt, query, headers, top_k=10) if query else []
    my_id = fetch_current_user_id(headers)
    own: list[dict[str, Any]] = []
    others: list[dict[str, Any]] = []
    for row in results:
        author = str(row.get("author_user_id") or row.get("owner_user_id") or "").strip()
        if my_id and author and author == my_id:
            own.append(row)
        else:
            others.append(row)
    return {
        "memory_type": mt,
        "query_text": query,
        "similar_own_top1": _compact_similar(own[0] if own else None),
        "similar_others_top3": [_compact_similar(r) for r in others[:3]],
        "own_ids": [str(r.get("id") or "").strip() for r in own if r.get("id")],
    }


@dataclass
class CuratorDecision:
    action: CuratorAction
    reason: str
    update_memory_id: str | None
    refined: dict[str, Any] | None


def _call_curator_llm(draft: dict[str, Any], similar_ctx: dict[str, Any]) -> dict[str, Any] | None:
    """Reuse extractor HTTP stack via a synthetic context + dedicated system prompt."""
    if not _curator_llm_available():
        return None
    user_payload = {
        "draft_extraction": draft,
        "similar_own_top1": similar_ctx.get("similar_own_top1"),
        "similar_others_top3": similar_ctx.get("similar_others_top3"),
        "hub_references": draft.get("_hub_references") or [],
        "correcting_after_hub_failure": bool(draft.get("_correcting_after_hub_failure")),
    }
    # Re-use extractor's HTTP client by temporarily swapping prompt through monkeypatch pattern:
    # duplicate minimal call here importing from extractor internals.
    from .extractor import _extractor_base_url, _extractor_api_key, _extractor_model, _parse_json_object, _tls_verify
    from .usage_telemetry import record_llm_usage

    import requests

    base = _extractor_base_url()
    url = f"{base}/chat/completions"
    timeout = float(_env("EVOMEMORY_CURATOR_TIMEOUT_SECONDS", _env("EVOMEMORY_EXTRACTOR_TIMEOUT_SECONDS", "120")) or "120")
    model = _env("EVOMEMORY_CURATOR_MODEL") or _extractor_model()
    headers = {
        "Authorization": f"Bearer {_extractor_api_key()}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": CURATOR_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)},
        ],
        "temperature": 0.15,
        "response_format": {"type": "json_object"},
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=timeout, verify=_tls_verify())
        r.raise_for_status()
        data = r.json()
        record_llm_usage("upload_curator", model, data)
        raw = data["choices"][0]["message"].get("content") or ""
        return _parse_json_object(str(raw))
    except Exception as e:
        logger.warning("upload curator LLM failed: %s", e)
        return None


def _validate_decision(
    raw: dict[str, Any],
    *,
    similar_ctx: dict[str, Any],
    draft: dict[str, Any],
) -> CuratorDecision | None:
    action = str(raw.get("action") or "").strip().lower()
    if action not in ("create", "update", "skip"):
        return None
    reason = str(raw.get("reason") or "").strip() or "(no reason)"
    update_id = str(raw.get("update_memory_id") or "").strip() or None
    own_ids = {x for x in (similar_ctx.get("own_ids") or []) if x}

    if action == "skip":
        category = str(raw.get("skip_category") or "").strip().lower()
        reason_lower = reason.lower()
        duplicate_claim = category == "duplicate" or (
            not category
            and any(word in reason_lower for word in ("duplicate", "same", "already", "covered", "overlap"))
        )
        best_similarity = _best_similar_similarity(similar_ctx)
        min_similarity = _curator_skip_duplicate_min_similarity()
        if duplicate_claim and best_similarity < min_similarity:
            logger.warning(
                "curator duplicate skip forced to create: best similarity %.3f below hard gate %.3f",
                best_similarity,
                min_similarity,
            )
            return CuratorDecision(
                action="create",
                reason=f"duplicate skip rejected below similarity gate ({best_similarity:.3f} < {min_similarity:.3f})",
                update_memory_id=None,
                refined=normalize_llm_extraction(dict(draft)),
            )
        return CuratorDecision(action="skip", reason=reason, update_memory_id=None, refined=None)

    refined = raw.get("refined")
    if not isinstance(refined, dict):
        refined = dict(draft)
    refined = normalize_llm_extraction(refined)
    if refined.get("skip") is True:
        return CuratorDecision(action="skip", reason=reason or "curator refined skip", update_memory_id=None, refined=None)

    mt = _draft_memory_type(draft)
    if _draft_memory_type(refined) != mt:
        refined["memory_type"] = mt

    if action == "update":
        own_top = similar_ctx.get("similar_own_top1") or {}
        own_similarity = _similarity(own_top)
        min_similarity = _curator_update_min_similarity()
        if own_similarity < min_similarity:
            logger.warning(
                "curator update forced to create: own similarity %.3f below hard gate %.3f",
                own_similarity,
                min_similarity,
            )
            # The LLM may have already merged unrelated own-card content into
            # ``refined``. Use the original normalized draft for the new card.
            return CuratorDecision(
                action="create",
                reason=f"update rejected below similarity gate ({own_similarity:.3f} < {min_similarity:.3f})",
                update_memory_id=None,
                refined=normalize_llm_extraction(dict(draft)),
            )
        if not update_id or update_id not in own_ids:
            fallback = str(own_top.get("id") or "").strip()
            if fallback and fallback in own_ids:
                update_id = fallback
            else:
                logger.warning("curator update rejected: id %s not in own results", update_id)
                action = "create"
                update_id = None
        if action == "update" and update_id:
            return CuratorDecision(
                action="update",
                reason=reason,
                update_memory_id=update_id,
                refined=refined,
            )

    return CuratorDecision(action="create", reason=reason, update_memory_id=None, refined=refined)


def decide_with_agent(
    draft: dict[str, Any],
    headers: dict[str, str],
) -> tuple[CuratorDecision | None, dict[str, Any]]:
    """Return (decision, similar_ctx). decision None → fall back to rule-based dedup."""
    similar_ctx = gather_similar_context(draft, headers)
    raw = _call_curator_llm(draft, similar_ctx)
    if not raw:
        return None, similar_ctx
    decision = _validate_decision(raw, similar_ctx=similar_ctx, draft=draft)
    if decision:
        logger.info(
            "upload curator: action=%s reason=%s update_id=%s own_sim=%.3f",
            decision.action,
            decision.reason[:120],
            decision.update_memory_id,
            _similarity(similar_ctx.get("similar_own_top1")),
        )
    return decision, similar_ctx


def upload_memory_record_with_agent(draft: dict[str, Any]) -> dict[str, Any] | None:
    """Entry: agent curate when enabled, else rule-based semantic dedup."""
    if draft.get("skip") is True:
        return None
    draft = normalize_llm_extraction(draft)
    headers = hub_headers()

    if agent_curate_enabled() and _curator_llm_available():
        decision, similar_ctx = decide_with_agent(draft, headers)
        if decision:
            if decision.action == "skip":
                return {
                    "status": "skipped",
                    "action": "skip",
                    "reason": decision.reason,
                    "curator": True,
                    "similar_own": similar_ctx.get("similar_own_top1"),
                    "similar_others": similar_ctx.get("similar_others_top3"),
                }
            refined = normalize_llm_extraction(decision.refined or draft)
            mt = _draft_memory_type(refined)
            payload = _draft_to_payload(refined)
            if decision.action == "update" and decision.update_memory_id and mt in ("ideation", "experiment", "recipe"):
                result = put_json(update_url(mt, decision.update_memory_id), payload, headers)
                result["action"] = "updated"
                result["id"] = decision.update_memory_id
                result["curator_reason"] = decision.reason
                result["curator"] = True
                return result
            from .hub_url import get_base_url

            base = get_base_url()
            url = f"{base}/memory/{mt}/upload"
            result = post_json(url, payload, headers)
            result["action"] = "created"
            result["curator_reason"] = decision.reason
            result["curator"] = True
            return result
        logger.info("upload curator unavailable or invalid; falling back to rule-based dedup")

    from .upload_semantic import upload_or_update_memory_record

    mt = _draft_memory_type(draft)
    payload = _draft_to_payload(draft)
    return upload_or_update_memory_record(mt, payload, headers)
