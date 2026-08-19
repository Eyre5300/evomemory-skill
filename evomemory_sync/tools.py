"""LangChain tools for querying EvoMemory Hub during agent execution."""

from __future__ import annotations

import os
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests
from langchain_core.tools import tool

from .constants import BROWSER_UA, DEFAULT_ACCEPT, DEFAULT_ACCEPT_LANGUAGE
from .env_loader import env as _env, load_env
from .hub_url import get_base_url
from .uploader import tls_verify


try:
    load_env()
except Exception:
    pass


def _default_top_k() -> int:
    raw = _env("EVOMEMORY_SEARCH_TOP_K", "3")
    try:
        k = int(raw)
        return max(1, min(3, k))
    except ValueError:
        return 3


def _default_min_similarity() -> float:
    raw = _env("EVOMEMORY_SEARCH_MIN_SIMILARITY", "0.5")
    try:
        v = float(raw)
        return max(0.0, min(1.0, v))
    except ValueError:
        return 0.5


def _positive_int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(_env(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def _problem_profile(
    query: str,
    constraints: str,
    current_state: str,
    observed_failure: str,
    environment: str,
) -> str:
    fields = (
        ("Objective", query, 1000),
        ("Constraints and acceptance", constraints, 800),
        ("Current state and attempted paths", current_state, 800),
        ("Observed failure or uncertainty", observed_failure, 800),
        ("Environment and dependencies", environment, 600),
    )
    lines = [
        f"{label}: {_truncate_preview_text(str(value or ''), limit)}"
        for label, value, limit in fields
        if str(value or "").strip()
    ]
    return "\n".join(lines)


def _optional_auth_headers() -> Dict[str, str]:
    from .uploader import hub_bearer_token

    token = hub_bearer_token()
    headers: Dict[str, str] = {
        "User-Agent": BROWSER_UA,
        "Accept": DEFAULT_ACCEPT,
        "Accept-Language": DEFAULT_ACCEPT_LANGUAGE,
        "Content-Type": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# Last search recommendations by memory id (lowercased). Used so apply can refuse avoid.
_LAST_CANDIDATE_META: Dict[str, Dict[str, str]] = {}


def _normalize_retrieval_proof(raw: str) -> str:
    """Accept bare v1.… or the display wrapper [HUB_APPLY_PROOF:v1.…]."""
    proof = str(raw or "").strip()
    if not proof:
        return ""
    lower = proof.lower()
    if lower.startswith("[hub_apply_proof:") and "]" in lower:
        start = lower.find("[hub_apply_proof:") + len("[hub_apply_proof:")
        end = proof.rfind("]")
        if end > start:
            proof = proof[start:end].strip()
    return proof.strip()


def _bounded_output(text: str, env_name: str, default: int) -> str:
    budget = _positive_int_env(env_name, default, minimum=800, maximum=20_000)
    if len(text) <= budget:
        return text
    proof_lines = [ln for ln in text.splitlines() if "HUB_APPLY_PROOF:" in ln]
    head = text[:budget].rstrip() + "\n…[EvoMemory context budget reached]"
    # Re-attach any proof lines that the hard cut may have destroyed.
    for ln in proof_lines:
        if ln not in head:
            head = head + "\n" + ln
    return head


def _truncate_preview_text(text: str, max_chars: int) -> str:
    """Compact single-line preview; avoid ending mid-combining-character for cleaner display."""
    t = (text or "").replace("\n", " ").strip()
    if max_chars <= 0:
        return ""
    if len(t) <= max_chars:
        return t
    cut = t[:max_chars]
    while cut and unicodedata.combining(cut[-1]):
        cut = cut[:-1]
    cut = cut.rstrip()
    if len(cut) < len(t):
        return cut + "…"
    return cut


def _validate_kind(memory_kind: str) -> Tuple[bool, str]:
    kind = (memory_kind or "").strip().lower()
    if kind in {"ideation", "experiment", "workflow", "recipe"}:
        return True, kind
    return False, kind


def _format_results(kind: str, results: List[Dict[str, Any]], max_items: int) -> str:
    def pick_similarity(item: Dict[str, Any]) -> str:
        sim = item.get("similarity_score", None)
        if sim is None:
            sim = item.get("similarity", None)
        if sim is None:
            return ""
        try:
            return f"(similarity={float(sim):.3f})"
        except Exception:
            return ""

    shown = results[: max_items]
    blocks: List[str] = []
    for i, item in enumerate(shown, 1):
        mem_id = str(item.get("id") or item.get("memory_id") or "unknown")
        # Only the authenticated Hub can issue an application capability. An
        # anonymous/malformed result remains viewable but cannot produce trusted
        # quality evidence.
        hub_proof = str(item.get("hub_retrieval_proof") or "").strip()
        proof_tag = f" [HUB_APPLY_PROOF:{hub_proof}]" if hub_proof else ""
        id_line = f"ID: {mem_id} [HUB_REF:{mem_id}]{proof_tag}"
        action = str(item.get("recommended_action") or "").strip().lower()
        mid_key = mem_id.strip().lower()
        if mid_key and mid_key != "unknown":
            _LAST_CANDIDATE_META[mid_key] = {
                "recommended_action": action,
                "hub_retrieval_proof": hub_proof,
            }
        lifecycle = str(item.get("lifecycle_state") or "candidate")
        if kind == "ideation":
            title = str(item.get("title") or item.get("goal") or "(untitled)")
            core = str(
                item.get("core_idea_summary")
                or item.get("core_idea")
                or item.get("core idea")
                or ""
            )
            requirements = str(
                item.get("requirements_summary")
                or item.get("requirements")
                or item.get("do_not_repeat_notes")
                or item.get("countermeasures")
                or ""
            )
            goal = str(item.get("goal") or "")
            mem_type = str(item.get("type") or item.get("memory_type") or item.get("status") or "")
            core_preview = _truncate_preview_text(core, 260)
            req_preview = _truncate_preview_text(requirements, 200)

            lines = [
                f"[{i}] 标题: {title}",
                id_line,
                f"类型/状态: {mem_type}" if mem_type else "",
                f"质量状态: {lifecycle}",
                f"目标: {goal}" if goal else "",
                f"核心思路摘要: {core_preview}" if core_preview else "核心思路摘要: (empty)",
                f"要点/约束摘要: {req_preview}" if req_preview else "",
                f"全文预计 {int(item.get('estimated_full_text_tokens') or 0)} tokens"
                if item.get("estimated_full_text_tokens")
                else "",
                f"相似度 {pick_similarity(item)}" if pick_similarity(item) else "",
                "选中后须 apply_evomemory 获取完整正文。",
            ]
            blocks.append("\n".join([x for x in lines if x]))
        elif kind == "workflow":
            title = str(item.get("title") or "(untitled)")
            desc = _truncate_preview_text(
                str(item.get("description_summary") or item.get("description") or ""),
                260,
            )
            pid = str(item.get("parent_ideation_id") or "") or "—"
            peid = str(item.get("parent_experiment_id") or "") or "—"
            lines = [
                f"[{i}] {title}",
                id_line,
                f"    描述摘要: {desc}" if desc else "",
                f"    质量状态: {lifecycle}",
                f"    parent_ideation_id: {pid}" if pid != "—" else "",
                f"    parent_experiment_id: {peid}" if peid != "—" else "",
                f"    全文预计 {int(item.get('estimated_full_text_tokens') or 0)} tokens"
                if item.get("estimated_full_text_tokens")
                else "",
                f"    相似度 {pick_similarity(item)}" if pick_similarity(item) else "",
                "    选中后须 apply_evomemory 获取完整正文。",
            ]
            blocks.append("\n".join([x for x in lines if x]))
        elif kind == "recipe":
            trigger = str(item.get("trigger") or "").strip()
            problem = str(item.get("problem_summary") or item.get("problem") or "").strip()
            tags = str(item.get("tags") or "").strip()
            evidence = item.get("evidence") or {}
            recommendation = str(item.get("recommended_action") or "inspect")
            reason = str(item.get("recommendation_reason") or "核对当前约束后决定")
            lines = [
                f"[{i}] 📋 {trigger or '(untitled recipe)'}",
                id_line,
                f"    问题摘要: {_truncate_preview_text(problem, 260)}" if problem else "",
                f"    标签: {tags}" if tags else "",
                f"    质量状态: {lifecycle}",
                f"    建议: {recommendation} — {reason}",
                (
                    "    成效: "
                    f"成功 {int(evidence.get('explicit_success_count') or 0)} / "
                    f"应用后失败 {int(evidence.get('failure_after_application_count') or 0)} / "
                    f"平均 Token {evidence.get('avg_application_token_cost') or '未知'}"
                ),
                f"    相似度 {pick_similarity(item)} · 效用 {float(item.get('utility_score') or 0):.3f}",
                f"    全文预计 {int(item.get('estimated_full_text_tokens') or 0)} tokens",
            ]
            blocks.append("\n".join([x for x in lines if x]))
        else:
            proposal = str(item.get("proposal_context") or item.get("task") or item.get("title") or "(untitled)")
            result_s = str(
                item.get("result_summary")
                or item.get("conclusion_summary")
                or item.get("conclusion")
                or ""
            )
            outcome = str(item.get("outcome") or "")
            mem_status = str(item.get("status") or item.get("memory_type") or "")

            prop_preview = _truncate_preview_text(proposal, 260)
            result_preview = _truncate_preview_text(result_s, 200)

            lines = [
                f"[{i}] 实验上下文: {prop_preview}",
                id_line,
                f"状态: {mem_status}" if mem_status else "",
                f"outcome: {outcome}" if outcome else "",
                f"质量状态: {lifecycle}",
                f"结果摘要: {result_preview}" if result_preview else "",
                f"全文预计 {int(item.get('estimated_full_text_tokens') or 0)} tokens"
                if item.get("estimated_full_text_tokens")
                else "",
                f"相似度 {pick_similarity(item)}" if pick_similarity(item) else "",
                "选中后须 apply_evomemory 获取完整正文。",
            ]
            blocks.append("\n".join([x for x in lines if x]))

    total = len(results)
    return (
        f"找到 {total} 条相关 {kind} 记忆（展示前 {len(shown)} 条）：\n\n"
        + "\n\n---\n\n".join(blocks)
    )


@tool
def search_evomemory(
    query: str,
    memory_kind: str,
    constraints: str = "",
    current_state: str = "",
    observed_failure: str = "",
    environment: str = "",
) -> str:
    """检索结构相似的社区经验，而不是查找相同题目。

    query 写清真正目标；并尽量提供 constraints、current_state、
    observed_failure、environment。工具只返回 Top-3 轻量候选。逐项核对适用
    条件和当前约束；没有正净效用候选时必须 abstain，不要为了使用而使用。
    memory_kind 为 ideation、experiment、workflow 或 recipe。
    """

    ok, kind = _validate_kind(memory_kind)
    if not ok:
        return f"无效 memory_kind: {memory_kind!r}。请传入 'ideation'、'experiment'、'workflow' 或 'recipe'。"

    q = (query or "").strip()
    if not q:
        return "检索失败：query 不能为空。"
    profile = _problem_profile(q, constraints, current_state, observed_failure, environment)

    base = get_base_url()
    headers = _optional_auth_headers()
    timeout = float(_env("EVOMEMORY_API_TIMEOUT_SECONDS", "30") or "30")

    try:
        url = f"{base}/memory/{kind}/search"
        payload: Dict[str, Any] = {
            "top_k": _default_top_k(),
            "min_similarity": _default_min_similarity(),
            "query_text": profile,
            "response_mode": "summary",
        }
        r = requests.post(url, json=payload, headers=headers, timeout=timeout, verify=tls_verify())
        if r.status_code >= 400:
            try:
                detail = r.json()
            except Exception:
                detail = r.text
            detail_s = str(detail)
            if len(detail_s) > 1000:
                detail_s = detail_s[:1000] + "…"
            return f"检索失败：Hub 返回 HTTP {r.status_code}。详细信息：{detail_s}"

        data = r.json()
        results = data.get("results") or []
        if not results:
            return f"没有搜到与 {q!r} 相关的 {kind} 记忆。你可以换个关键词再试。"

        rendered = _format_results(kind, results, max_items=3)
        avoid_count = sum(
            str(row.get("recommended_action") or "") == "avoid" for row in results[:3]
        )
        decision = (
            "\n\n全部候选均建议 avoid：本次应 abstain 并独立解决。"
            if results and avoid_count == len(results[:3])
            else "\n\n只在候选适用条件覆盖当前约束且预期净效用为正时调用 apply_evomemory；否则 abstain。"
        )
        return _bounded_output(
            rendered + decision,
            "EVOMEMORY_SEARCH_CONTEXT_MAX_CHARS",
            3600,
        )
    except Exception as e:
        return f"检索失败：{type(e).__name__}: {e}。建议检查 `EVOMEMORY_API_BASE_URL` 与网络连接。"


@tool
def apply_evomemory(
    memory_id: str,
    retrieval_proof: str,
    fit_reason: str,
    adaptation_plan: str,
    force_apply: bool = False,
) -> str:
    """选择一条候选、创建可信应用并按需获取其完整正文。

    retrieval_proof 必须复制检索结果中的 HUB_APPLY_PROOF（裸 v1.… 签名，或带
    [HUB_APPLY_PROOF:…] 包装均可）。不能用 memory_id 或 [HUB_REF:…] 代替。
    recommended_action=avoid 的候选默认拒绝；仅当用户明确要求时设 force_apply=true。
    只有适用条件覆盖当前约束且预期净效用为正时才调用；否则 abstain。
    """
    mid = str(memory_id or "").strip().lower()
    proof = _normalize_retrieval_proof(retrieval_proof)
    fit = str(fit_reason or "").strip()
    plan = str(adaptation_plan or "").strip()
    if not mid or not proof:
        return (
            "应用未记录：请使用 search_evomemory 返回的 memory_id 和已签名的 HUB_APPLY_PROOF"
            "（不是 HUB_REF，也不是裸 UUID）。"
        )
    if proof.lower().startswith("[hub_ref:") or (
        len(proof) == 36 and all(c in "0123456789abcdef-" for c in proof.lower())
    ):
        return (
            "应用未记录：retrieval_proof 不能是 memory_id 或 [HUB_REF:…]。"
            "请粘贴检索结果中的 HUB_APPLY_PROOF（通常以 v1. 开头）。"
        )
    if not proof.lower().startswith("v1."):
        return (
            "应用未记录：retrieval_proof 须为 Hub 签名（通常以 v1. 开头）。"
            "可直接粘贴 [HUB_APPLY_PROOF:v1.…]，工具会自动剥掉包装。"
        )
    meta = _LAST_CANDIDATE_META.get(mid) or {}
    if str(meta.get("recommended_action") or "").lower() == "avoid" and not force_apply:
        return (
            "应用未记录：该候选 recommended_action=avoid，请 abstain。"
            "若用户明确要求仍要试用，请设 force_apply=true。"
        )
    if len(fit) < 24 or len(plan) < 24:
        return "应用未记录：fit_reason 与 adaptation_plan 须说明为何适用以及如何改写（各至少约一句话），否则请 abstain。"
    try:
        from .agent_tools import headers_or_error
        from .hub_usage import create_application_by_id

        headers, err = headers_or_error()
        if not headers:
            return f"应用未记录：{err or '需要 Hub 登录（EVOMEMORY_API_TOKEN 或 EVOMEMORY_AGENT_TOKEN）。'}"
        application = create_application_by_id(mid, proof, headers=headers)
    except Exception as e:
        return f"应用未记录：Hub 请求失败（{type(e).__name__}）。"
    if not application or not application.get("application_id"):
        extra = ""
        if isinstance(application, dict) and application.get("error"):
            extra = f" {application.get('error')}"
            if application.get("detail"):
                extra += f" {application.get('detail')}"
        return f"应用未记录：Hub 拒绝或无法校验 retrieval_proof。{extra}".rstrip()
    app_id = str(application.get("application_id") or "").strip().lower()
    if not app_id:
        return "应用未记录：Hub 响应缺少 application_id。"
    content = application.get("memory_content") or {}
    kind = str(application.get("memory_kind") or "memory")
    sections = [
        f"{key}: {value}"
        for key, value in content.items()
        if value not in (None, "", [], {})
    ]
    selected = "\n\n".join(sections) if sections else "(The legacy Hub did not return selected content.)"
    body = (
        f"EvoMemory application recorded by the Hub. kind={kind}.\n"
        f"Fit reason: {_truncate_preview_text(fit, 600)}\n"
        f"Adaptation plan: {_truncate_preview_text(plan, 600)}\n"
        # Keep the legacy marker for older middleware/consumers while the typed
        # marker carries the memory kind needed for Ideation -> Experiment links.
        f"[HUB_APPLIED:{mid}:{app_id}]\n"
        f"[HUB_APPLIED:{kind}:{mid}:{app_id}]\n\nSelected experience:\n{selected}"
    )
    return _bounded_output(body, "EVOMEMORY_APPLIED_CONTEXT_MAX_CHARS", 7000)


def _require_auth_headers() -> tuple[dict[str, str] | None, str | None]:
    from .agent_tools import headers_or_error

    return headers_or_error()


@tool
def delete_evomemory(memory_kind: str, memory_id: str) -> str:
    """删除自己在 EvoMemory Hub 上发布的记忆（仅作者）。

    第一次删除：移入垃圾桶（visibility=hidden，社区不可见，可在 dashboard 恢复）。
    对已在垃圾桶中的同一 ID 再次删除：永久删除，不可恢复。
    `memory_kind` 为 ideation / experiment / workflow / recipe。"""

    headers, err = _require_auth_headers()
    if err:
        return f"删除失败：{err}"
    try:
        from .memory_manage import trash_or_delete_memory

        out = trash_or_delete_memory(memory_kind, memory_id, headers=headers)
        if out.get("status") == "error":
            return f"删除失败：{out.get('error')}"
        return str(out.get("message") or out)
    except ValueError as e:
        return f"删除失败：{e}"
    except Exception as e:
        return f"删除失败：{type(e).__name__}: {e}"


@tool
def list_my_evomemory(memory_kind: str, include_hidden: bool = True) -> str:
    """列出当前登录用户在 Hub 上自己上传的记忆（含 id 与 visibility），便于管理或删除。

    `include_hidden=true` 时包含垃圾桶（hidden）中的条目。"""

    headers, err = _require_auth_headers()
    if err:
        return f"列表失败：{err}"
    try:
        from .memory_manage import list_my_memories

        rows = list_my_memories(memory_kind, headers=headers, include_hidden=include_hidden, limit=50)
        if not rows:
            return f"你没有上传过任何 {memory_kind} 记忆。"
        lines: list[str] = []
        for row in rows[:30]:
            vis = row.get("visibility") or "public"
            rid = row.get("id")
            title = (
                row.get("title")
                or row.get("goal")
                or row.get("trigger")
                or row.get("proposal_context")
                or row.get("description")
                or "(no title)"
            )
            title = _truncate_preview_text(str(title), 80)
            lines.append(f"- id={rid} visibility={vis} · {title}")
        return f"共 {len(rows)} 条 {memory_kind}（展示前 {min(len(rows), 30)} 条）：\n" + "\n".join(lines)
    except ValueError as e:
        return f"列表失败：{e}"
    except Exception as e:
        return f"列表失败：{type(e).__name__}: {e}"


@tool
def restore_evomemory(memory_kind: str, memory_id: str) -> str:
    """将垃圾桶（hidden）中的自己的记忆恢复为公开（public）。"""

    headers, err = _require_auth_headers()
    if err:
        return f"恢复失败：{err}"
    try:
        from .memory_manage import restore_memory_from_trash

        out = restore_memory_from_trash(memory_kind, memory_id, headers=headers)
        if out.get("status") == "error":
            return f"恢复失败：{out.get('error')}"
        return str(out.get("message") or out)
    except ValueError as e:
        return f"恢复失败：{e}"
    except Exception as e:
        return f"恢复失败：{type(e).__name__}: {e}"

