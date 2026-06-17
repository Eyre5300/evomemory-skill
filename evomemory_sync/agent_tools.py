"""
Async helpers for agents to explicitly archive ideation / experiment memories to EvoMemory Hub.

This module lives in **evomemory-skill** (package `evomemory_sync`) — the same package agents install
via `pip install -e .` from the skill repo. It is **not** part of the Hub server package.

Environment (aligned with the rest of `evomemory_sync` — see `references/CONFIG.md`):

- ``EVOMEMORY_API_BASE_URL`` — Hub base URL (same as `scripts/setup.py` / middleware).
- ``EVOMEMORY_API_TOKEN`` — JWT with upload permission.

Optional aliases (e.g. dedicated agent keys):

- ``EVOMEMORY_API_URL`` — if set, overrides base URL (takes precedence over ``EVOMEMORY_API_BASE_URL``).
- ``EVOMEMORY_AGENT_TOKEN`` — if ``EVOMEMORY_API_TOKEN`` is empty, this is used as the bearer token.

Embeddings are computed on the Hub; uploads do not send client-side vectors.

**Misconfiguration:** when the Hub token is missing, ``share_*`` / ``patch_*`` return
``{"error": "<message>"}`` instead of raising, so LangGraph agents are not aborted mid-run.
Use :func:`headers_or_error` in new code; :func:`get_headers` remains for scripts and raises if unset.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx
import re as _re

from .constants import BROWSER_UA, DEFAULT_ACCEPT, DEFAULT_ACCEPT_LANGUAGE
from .env_loader import load_env
from .hub_url import get_base_url
from .uploader import env, tls_verify, upload_memory_record

try:
    load_env()
except Exception:
    pass

_DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_UNSET = object()
_UUID_RE = _re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", _re.IGNORECASE)


def _validate_uuid(value: str, name: str = "id") -> str:
    """Raise ValueError if *value* is not a valid UUID string."""
    if not _UUID_RE.match(str(value).strip()):
        raise ValueError(f"Invalid {name}: expected UUID format, got {value!r}")
    return value.strip()

_MISSING_TOKEN_MSG = (
    "EvoMemory Hub: set EVOMEMORY_API_TOKEN or EVOMEMORY_AGENT_TOKEN "
    "(e.g. run `python scripts/setup.py share` from the skill repository)."
)


def _base_url() -> str:
    override = env("EVOMEMORY_API_URL")
    if override:
        return override.strip().rstrip("/")
    return get_base_url()


def headers_or_error() -> tuple[dict[str, str] | None, str | None]:
    """Return ``(headers, None)`` or ``(None, error_message)`` if no bearer token is configured."""
    token = env("EVOMEMORY_API_TOKEN") or env("EVOMEMORY_AGENT_TOKEN")
    if not token:
        return None, _MISSING_TOKEN_MSG
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": BROWSER_UA,
        "Accept": DEFAULT_ACCEPT,
        "Accept-Language": DEFAULT_ACCEPT_LANGUAGE,
    }, None


def get_headers() -> dict[str, str]:
    """Same headers as Hub uploads; raises ``RuntimeError`` if token missing (CLI / internal use)."""
    h, err = headers_or_error()
    if err:
        raise RuntimeError(err)
    return h


def _strip_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


async def share_failed_ideation(
    goal: str,
    title: str,
    core_idea: str,
    requirements: str,
) -> dict[str, Any]:
    """
    供 Agent 调用的工具：当任务彻底失败、走入死胡同或遇到无法解决的 Bug 时调用此函数，将失败经验归档。
    若未配置 token，返回 ``{"error": "..."}`` 而非抛错。
    """
    headers, err = headers_or_error()
    if err:
        return {"error": err}
    payload: dict[str, Any] = {
        "memory_type": "ideation",
        "status": "failed",
        "goal": goal,
        "title": title,
        "core_idea": core_idea,
        "requirements": requirements,
    }
    try:
        result = await asyncio.to_thread(upload_memory_record, payload)
        if result is None:
            return {"error": "upload skipped or empty payload"}
        return result
    except Exception as e:
        return {"error": f"Hub upload failed: {type(e).__name__}: {e}"}


async def share_successful_experiment(
    proposal_context: str,
    data_strategy: str,
    model_strategy: str,
    environment: str,
    hardware_requirements: Optional[str] = None,
    software_dependencies: Optional[str] = None,
    parent_ideation_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    供 Agent 调用的工具：当任务顺利完成且具有复现价值时调用此函数，将实验配置归档。
    若未配置 token，返回 ``{"error": "..."}``。
    """
    headers, err = headers_or_error()
    if err:
        return {"error": err}
    payload = _strip_none(
        {
            "memory_type": "experiment",
            "proposal_context": proposal_context,
            "data_strategy": data_strategy,
            "model_strategy": model_strategy,
            "environment": environment,
            "hardware_requirements": hardware_requirements,
            "software_dependencies": software_dependencies,
            "parent_ideation_id": parent_ideation_id,
        }
    )
    try:
        result = await asyncio.to_thread(upload_memory_record, payload)
        if result is None:
            return {"error": "upload skipped or empty payload"}
        return result
    except Exception as e:
        return {"error": f"Hub upload failed: {type(e).__name__}: {e}"}


async def share_recipe(
    trigger: str,
    problem: str,
    solution: str,
    env_snapshot: str = "(unspecified)",
    result: str = "(none)",
    tags: str = "",
    parent_ideation_id: str | None = None,
    parent_experiment_id: str | None = None,
) -> dict[str, Any]:
    """
    供 Agent 调用的工具：将一条经过验证的"原子经验卡"（Recipe）上传到 EvoMemory Hub。
    Recipe 包含 trigger（何时触发）、problem（遇到什么问题）、solution（解决方案）三要素。
    适合在成功解决一个具体 Bug 或完成一个可复用的技巧后调用。
    """
    headers, err = headers_or_error()
    if err:
        return {"error": err}
    payload: dict[str, Any] = _strip_none(
        {
            "memory_type": "recipe",
            "trigger": trigger,
            "problem": problem,
            "solution": solution,
            "env_snapshot": env_snapshot,
            "result": result,
            "tags": tags,
            "parent_ideation_id": parent_ideation_id,
            "parent_experiment_id": parent_experiment_id,
        }
    )
    try:
        out = await asyncio.to_thread(upload_memory_record, payload)
        if out is None:
            return {"error": "upload skipped or empty payload"}
        return out
    except Exception as e:
        return {"error": f"Hub upload failed: {type(e).__name__}: {e}"}


async def share_workflow(
    title: str,
    description: str,
    prompt_templates: str,
    tool_configuration: str,
    parent_ideation_id: Optional[str] = None,
    parent_experiment_id: Optional[str] = None,
) -> dict[str, Any]:
    """Archive a reusable workflow (prompts + tool configuration) to the Hub."""
    headers, err = headers_or_error()
    if err:
        return {"error": err}
    payload = _strip_none(
        {
            "memory_type": "workflow",
            "title": title,
            "description": description,
            "prompt_templates": prompt_templates,
            "tool_configuration": tool_configuration,
            "parent_ideation_id": parent_ideation_id,
            "parent_experiment_id": parent_experiment_id,
        }
    )
    try:
        out = await asyncio.to_thread(upload_memory_record, payload)
        if out is None:
            return {"error": "upload skipped or empty payload"}
        return out
    except Exception as e:
        return {"error": f"Hub upload failed: {type(e).__name__}: {e}"}


async def patch_experiment_parent_link(
    memory_id: str,
    parent_ideation_id: Any = _UNSET,
) -> dict[str, Any]:
    """PATCH /memory/experiment/{id}/parent — set or clear parent ideation (author only).

    Pass ``parent_ideation_id=None`` to clear. Omit by using the default to skip the call
    (you must pass a value to perform a PATCH).
    """
    if parent_ideation_id is _UNSET:
        raise ValueError("parent_ideation_id is required (use None to clear the link)")
    try:
        _validate_uuid(memory_id, "memory_id")
        if parent_ideation_id is not None:
            _validate_uuid(str(parent_ideation_id), "parent_ideation_id")
    except ValueError as e:
        return {"error": str(e)}
    headers, err = headers_or_error()
    if err:
        return {"error": err}
    base = _base_url()
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, verify=tls_verify()) as client:
            response = await client.patch(
                f"{base}/memory/experiment/{memory_id}/parent",
                json={"parent_ideation_id": parent_ideation_id},
                headers=headers,
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"Hub returned HTTP {e.response.status_code}: {e.response.text[:500]}"}
    except httpx.RequestError as e:
        return {"error": f"Hub request failed: {type(e).__name__}: {e}"}


async def patch_workflow_parent_links(
    memory_id: str,
    parent_ideation_id: Any = _UNSET,
    parent_experiment_id: Any = _UNSET,
) -> dict[str, Any]:
    """PATCH /memory/workflow/{id}/parents — update one or both parents (author only).

    Use ``None`` for a field to clear it. Omit a parameter (leave default) to keep the
    server-side merge behavior for that field.
    """
    body: dict[str, Any] = {}
    try:
        _validate_uuid(memory_id, "memory_id")
    except ValueError as e:
        return {"error": str(e)}
    if parent_ideation_id is not _UNSET:
        if parent_ideation_id is not None:
            try:
                _validate_uuid(str(parent_ideation_id), "parent_ideation_id")
            except ValueError as e:
                return {"error": str(e)}
        body["parent_ideation_id"] = parent_ideation_id
    if parent_experiment_id is not _UNSET:
        if parent_experiment_id is not None:
            try:
                _validate_uuid(str(parent_experiment_id), "parent_experiment_id")
            except ValueError as e:
                return {"error": str(e)}
        body["parent_experiment_id"] = parent_experiment_id
    if not body:
        raise ValueError("pass at least one of parent_ideation_id or parent_experiment_id")
    headers, err = headers_or_error()
    if err:
        return {"error": err}
    base = _base_url()
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, verify=tls_verify()) as client:
            response = await client.patch(
                f"{base}/memory/workflow/{memory_id}/parents",
                json=body,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"Hub returned HTTP {e.response.status_code}: {e.response.text[:500]}"}
    except httpx.RequestError as e:
        return {"error": f"Hub request failed: {type(e).__name__}: {e}"}


async def delete_my_memory(memory_kind: str, memory_id: str) -> dict[str, Any]:
    """Trash-then-delete: first call hides; second call permanently deletes."""
    headers, err = headers_or_error()
    if err:
        return {"error": err}
    try:
        from .memory_manage import trash_or_delete_memory

        return await asyncio.to_thread(trash_or_delete_memory, memory_kind, memory_id, headers=headers)
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


async def list_my_memories_tool(
    memory_kind: str,
    *,
    include_hidden: bool = True,
    limit: int = 50,
) -> dict[str, Any]:
    headers, err = headers_or_error()
    if err:
        return {"error": err}
    try:
        from .memory_manage import list_my_memories

        rows = await asyncio.to_thread(
            list_my_memories,
            memory_kind,
            headers=headers,
            include_hidden=include_hidden,
            limit=limit,
        )
        return {"status": "success", "results": rows}
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


async def restore_my_memory(memory_kind: str, memory_id: str) -> dict[str, Any]:
    headers, err = headers_or_error()
    if err:
        return {"error": err}
    try:
        from .memory_manage import restore_memory_from_trash

        return await asyncio.to_thread(restore_memory_from_trash, memory_kind, memory_id, headers=headers)
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


AGENT_SYSTEM_PROMPT_EXTENSION = """
【强制工作流：知识沉淀与归档】
在你完成用户分配的任何研发、代码编写或技术调研任务后，你必须执行以下反思与归档步骤：

1. 评估任务结果：
   - 如果任务尝试了多种方法但最终失败、走入死胡同或遇到无法解决的 Bug：你必须调用 `share_failed_ideation` 工具。在 `core_idea` 中详细记录失败的路径和报错信息，在 `requirements` 中提取“避坑指南”和检索标签。
   - 如果任务顺利完成，且具有一定的通用价值：你必须调用 `share_successful_experiment` 工具，提炼出 `hardware_requirements` (如显存要求)、`software_dependencies` (如核心库版本)、`data_strategy` 和 `model_strategy`。

2. 执行要求：
   - 在调用工具前，请先向用户输出一段简短的总结，例如：“任务已完成。该过程具有复现价值，我正在将其归档至 EvoMemory 知识库...”
   - 归档的内容必须结构化、客观且精炼。
   - 若归档函数返回 JSON 且含 `error` 字段，说明未配置 Hub token，请提示用户运行 skill 的 `setup.py share` 并完成登录，不要当作成功上传处理。

3. 管理已上传记忆（需用户明确要求删除时）：
   - 先用 `list_my_evomemory` 确认 id 与 visibility。
   - `delete_evomemory`：第一次删除移入垃圾桶（hidden）；对同一 id 再次删除才永久删除。
   - 误删可从垃圾桶用 `restore_evomemory` 恢复公开。
"""
