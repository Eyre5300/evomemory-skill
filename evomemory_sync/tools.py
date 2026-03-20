"""LangChain tools for querying EvoMemory Hub during agent execution."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Literal, Tuple

import requests
from langchain_core.tools import tool

from .uploader import (
    BROWSER_UA,
    DEFAULT_ACCEPT,
    DEFAULT_ACCEPT_LANGUAGE,
    embed_enabled,
    embed_model_id,
    embed_text,
    get_base_url,
)


def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return v.strip() if isinstance(v, str) and v.strip() else default


def _default_top_k() -> int:
    raw = _env("EVOMEMORY_SEARCH_TOP_K", "10")
    try:
        k = int(raw)
        return max(1, min(100, k))
    except ValueError:
        return 10


def _default_min_similarity() -> float:
    raw = _env("EVOMEMORY_SEARCH_MIN_SIMILARITY", "0")
    try:
        v = float(raw)
        return max(0.0, min(1.0, v))
    except ValueError:
        return 0.0


def _optional_auth_headers() -> Dict[str, str]:
    token = _env("EVOMEMORY_API_TOKEN", "")
    headers: Dict[str, str] = {
        "User-Agent": BROWSER_UA,
        "Accept": DEFAULT_ACCEPT,
        "Accept-Language": DEFAULT_ACCEPT_LANGUAGE,
        "Content-Type": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _validate_kind(memory_kind: str) -> Tuple[bool, str]:
    kind = (memory_kind or "").strip().lower()
    if kind in {"ideation", "experiment"}:
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
        if kind == "ideation":
            title = str(item.get("title") or item.get("goal") or "(untitled)")
            core = str(item.get("core_idea") or item.get("core idea") or "")
            requirements = str(item.get("requirements") or item.get("do_not_repeat_notes") or item.get("countermeasures") or "")
            goal = str(item.get("goal") or "")
            mem_type = str(item.get("type") or item.get("memory_type") or item.get("status") or "")
            core_preview = core[:800].strip().replace("\n", " ")
            req_preview = requirements[:800].strip().replace("\n", " ")

            lines = [
                f"[{i}] 标题: {title}",
                f"类型/状态: {mem_type}" if mem_type else "",
                f"目标: {goal}" if goal else "",
                f"核心思路/避坑指南: {core_preview}" if core_preview else "核心思路/避坑指南: (empty)",
                f"要点/约束: {req_preview}" if req_preview else "",
                f"相似度 {pick_similarity(item)}" if pick_similarity(item) else "",
            ]
            blocks.append("\n".join([x for x in lines if x]))
        else:
            proposal = str(item.get("proposal_context") or item.get("task") or item.get("title") or "(untitled)")
            data_s = str(item.get("data_strategy") or item.get("data") or "")
            model_s = str(item.get("model_strategy") or item.get("model") or "")
            env_s = str(item.get("environment") or item.get("environment_constraints") or "")
            mem_status = str(item.get("status") or item.get("memory_type") or "")

            prop_preview = proposal[:800].strip().replace("\n", " ")
            data_preview = data_s[:800].strip().replace("\n", " ")
            model_preview = model_s[:800].strip().replace("\n", " ")
            env_preview = env_s[:800].strip().replace("\n", " ")

            lines = [
                f"[{i}] 实验上下文: {prop_preview}",
                f"状态: {mem_status}" if mem_status else "",
                f"数据策略: {data_preview}" if data_preview else "",
                f"模型策略: {model_preview}" if model_preview else "",
                f"环境/约束: {env_preview}" if env_preview else "",
                f"相似度 {pick_similarity(item)}" if pick_similarity(item) else "",
            ]
            blocks.append("\n".join([x for x in lines if x]))

    total = len(results)
    return (
        f"找到 {total} 条相关 {kind} 记忆（展示前 {len(shown)} 条）：\n\n"
        + "\n\n---\n\n".join(blocks)
    )


@tool
def search_evomemory(query: str, memory_kind: str) -> str:
    """当你缺乏研究思路，或者代码执行遇到棘手报错时，调用此工具检索 EvoMemory Hub 社区的历史经验、避坑指南和成功实验。这能帮你快速找到相似研究方向、复用可行方案并避免重复踩坑。参数 `memory_kind` 只允许 `ideation` 或 `experiment`。"""

    ok, kind = _validate_kind(memory_kind)
    if not ok:
        return f"无效 memory_kind: {memory_kind!r}。请传入 'ideation' 或 'experiment'。"

    q = (query or "").strip()
    if not q:
        return "检索失败：query 不能为空。"

    base = get_base_url()
    url = f"{base}/memory/{kind}/search"
    payload: Dict[str, Any] = {
        "top_k": _default_top_k(),
        "min_similarity": _default_min_similarity(),
    }

    headers = _optional_auth_headers()
    timeout = float(_env("EVOMEMORY_API_TIMEOUT_SECONDS", "30") or "30")

    try:
        if embed_enabled():
            payload["query_embedding"] = embed_text(q)
            payload["embedding_model_id"] = embed_model_id()
        else:
            payload["query_text"] = q

        r = requests.post(url, json=payload, headers=headers, timeout=timeout, verify=False)
        if r.status_code >= 400:
            try:
                detail = r.json()
            except Exception:
                detail = r.text
            return f"检索失败：Hub 返回 HTTP {r.status_code}。详细信息：{detail}"

        data = r.json()
        results: List[Dict[str, Any]] = data.get("results") or []
        if not results:
            return f"没有搜到与 {q!r} 相关的 {kind} 记忆。你可以换个关键词再试。"

        # 保持 Observation 紧凑：最多展示 5 条
        return _format_results(kind, results, max_items=5)
    except Exception as e:
        return f"检索失败：{type(e).__name__}: {e}。建议检查 `EVOMEMORY_API_BASE_URL`、网络连接以及（如需向量化）Embedding 相关环境变量。"

