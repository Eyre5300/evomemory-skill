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

When embedding env vars are configured (``EVOMEMORY_EMBED_*``), uploads include ``embedding`` + ``embedding_model_id``,
matching `evomemory_sync.uploader.upload_memory_record` behavior.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from .env_loader import load_env
from .uploader import (
    BROWSER_UA,
    DEFAULT_ACCEPT,
    DEFAULT_ACCEPT_LANGUAGE,
    embed_enabled,
    embed_model_id,
    embed_text,
    env,
    get_base_url,
)

try:
    load_env()
except Exception:
    pass

_DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_UNSET = object()


def _base_url() -> str:
    override = env("EVOMEMORY_API_URL")
    if override:
        return override.strip().rstrip("/")
    return get_base_url()


def get_headers() -> dict[str, str]:
    """Bearer + browser-like headers consistent with `hub_headers()` / search tools."""
    token = env("EVOMEMORY_API_TOKEN") or env("EVOMEMORY_AGENT_TOKEN")
    if not token:
        raise RuntimeError(
            "Set EVOMEMORY_API_TOKEN (or EVOMEMORY_AGENT_TOKEN) for agent archive tools."
        )
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": BROWSER_UA,
        "Accept": DEFAULT_ACCEPT,
        "Accept-Language": DEFAULT_ACCEPT_LANGUAGE,
    }


def _strip_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


async def _maybe_add_ideation_embedding(body: dict[str, Any]) -> dict[str, Any]:
    if not embed_enabled():
        return body
    text = "\n".join(
        [body["goal"], body["title"], body["core_idea"], body["requirements"]]
    )
    vec = await asyncio.to_thread(embed_text, text)
    out = dict(body)
    out["embedding"] = vec
    out["embedding_model_id"] = embed_model_id()
    return out


async def _maybe_add_experiment_embedding(body: dict[str, Any]) -> dict[str, Any]:
    if not embed_enabled():
        return body
    text = "\n".join(
        [
            body["proposal_context"],
            body["data_strategy"],
            body["model_strategy"],
            body["environment"],
        ]
    )
    vec = await asyncio.to_thread(embed_text, text)
    out = dict(body)
    out["embedding"] = vec
    out["embedding_model_id"] = embed_model_id()
    return out


async def _maybe_add_workflow_embedding(body: dict[str, Any]) -> dict[str, Any]:
    if not embed_enabled():
        return body
    text = "\n".join(
        [
            body["title"],
            body["description"],
            body["prompt_templates"],
            body["tool_configuration"],
        ]
    )
    vec = await asyncio.to_thread(embed_text, text)
    out = dict(body)
    out["embedding"] = vec
    out["embedding_model_id"] = embed_model_id()
    return out


async def share_failed_ideation(
    goal: str,
    title: str,
    core_idea: str,
    requirements: str,
) -> dict[str, Any]:
    """
    供 Agent 调用的工具：当任务彻底失败、走入死胡同或遇到无法解决的 Bug 时调用此函数，将失败经验归档。
    """
    payload: dict[str, Any] = {
        "type": "failed",
        "goal": goal,
        "title": title,
        "core_idea": core_idea,
        "requirements": requirements,
    }
    payload = await _maybe_add_ideation_embedding(payload)
    base = _base_url()
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, verify=False) as client:
        response = await client.post(
            f"{base}/memory/ideation/upload",
            json=payload,
            headers=get_headers(),
        )
        response.raise_for_status()
        return response.json()


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
    """
    payload = _strip_none(
        {
            "proposal_context": proposal_context,
            "data_strategy": data_strategy,
            "model_strategy": model_strategy,
            "environment": environment,
            "hardware_requirements": hardware_requirements,
            "software_dependencies": software_dependencies,
            "parent_ideation_id": parent_ideation_id,
        }
    )
    payload = await _maybe_add_experiment_embedding(payload)
    base = _base_url()
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, verify=False) as client:
        response = await client.post(
            f"{base}/memory/experiment/upload",
            json=payload,
            headers=get_headers(),
        )
        response.raise_for_status()
        return response.json()


async def share_workflow(
    title: str,
    description: str,
    prompt_templates: str,
    tool_configuration: str,
    parent_ideation_id: Optional[str] = None,
    parent_experiment_id: Optional[str] = None,
) -> dict[str, Any]:
    """Archive a reusable workflow (prompts + tool configuration) to the Hub."""
    payload = _strip_none(
        {
            "title": title,
            "description": description,
            "prompt_templates": prompt_templates,
            "tool_configuration": tool_configuration,
            "parent_ideation_id": parent_ideation_id,
            "parent_experiment_id": parent_experiment_id,
        }
    )
    payload = await _maybe_add_workflow_embedding(payload)
    base = _base_url()
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, verify=False) as client:
        response = await client.post(
            f"{base}/memory/workflow/upload",
            json=payload,
            headers=get_headers(),
        )
        response.raise_for_status()
        return response.json()


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
    base = _base_url()
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, verify=False) as client:
        response = await client.patch(
            f"{base}/memory/experiment/{memory_id}/parent",
            json={"parent_ideation_id": parent_ideation_id},
            headers=get_headers(),
        )
        response.raise_for_status()
        return response.json()


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
    if parent_ideation_id is not _UNSET:
        body["parent_ideation_id"] = parent_ideation_id
    if parent_experiment_id is not _UNSET:
        body["parent_experiment_id"] = parent_experiment_id
    if not body:
        raise ValueError("pass at least one of parent_ideation_id or parent_experiment_id")
    base = _base_url()
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, verify=False) as client:
        response = await client.patch(
            f"{base}/memory/workflow/{memory_id}/parents",
            json=body,
            headers=get_headers(),
        )
        response.raise_for_status()
        return response.json()


AGENT_SYSTEM_PROMPT_EXTENSION = """
【强制工作流：知识沉淀与归档】
在你完成用户分配的任何研发、代码编写或技术调研任务后，你必须执行以下反思与归档步骤：

1. 评估任务结果：
   - 如果任务尝试了多种方法但最终失败、走入死胡同或遇到无法解决的 Bug：你必须调用 `share_failed_ideation` 工具。在 `core_idea` 中详细记录失败的路径和报错信息，在 `requirements` 中提取“避坑指南”和检索标签。
   - 如果任务顺利完成，且具有一定的通用价值：你必须调用 `share_successful_experiment` 工具，提炼出 `hardware_requirements` (如显存要求)、`software_dependencies` (如核心库版本)、`data_strategy` 和 `model_strategy`。

2. 执行要求：
   - 在调用工具前，请先向用户输出一段简短的总结，例如：“任务已完成。该过程具有复现价值，我正在将其归档至 EvoMemory 知识库...”
   - 归档的内容必须结构化、客观且精炼。
"""
