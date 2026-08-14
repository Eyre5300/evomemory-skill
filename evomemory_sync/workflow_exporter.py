"""
将标准化的 ``EvoWorkflow`` 映射到 Hub ``/memory/workflow/upload`` 的请求体并上传。

环境变量与 ``evomemory_sync.agent_tools`` 一致：``EVOMEMORY_API_URL``（可选，覆盖 base）、
``EVOMEMORY_API_BASE_URL``、``EVOMEMORY_API_TOKEN`` / ``EVOMEMORY_AGENT_TOKEN``。
Hub 端负责向量化，无需客户端 embedding 配置。
"""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx

from .agent_tools import _base_url, headers_or_error
from .uploader import tls_verify
from .workflow_schema import EvoWorkflow

_DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


def _strip_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


async def export_and_upload_workflow(
    workflow: EvoWorkflow,
    parent_experiment_id: Optional[str] = None,
    parent_ideation_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    将标准化的 EvoWorkflow 拆分并映射到后端 API 格式，然后上传到 ``/memory/workflow/upload``。
    """
    prompt_templates_str = json.dumps(workflow.prompts, ensure_ascii=False)

    tool_config_payload: dict[str, Any] = {
        "version": workflow.version,
        "llm_config": workflow.llm_config.model_dump(),
        "environment": workflow.environment.model_dump(),
        "tools": workflow.tools,
        "permissions": workflow.permissions.model_dump(),
        "execution_policy": workflow.execution_policy.model_dump(),
        "metadata": workflow.metadata,
    }
    tool_configuration_str = json.dumps(tool_config_payload, ensure_ascii=False)

    payload = _strip_none(
        {
            "title": workflow.title,
            "description": workflow.description,
            "prompt_templates": prompt_templates_str,
            "tool_configuration": tool_configuration_str,
            "parent_experiment_id": parent_experiment_id,
            "parent_ideation_id": parent_ideation_id,
        }
    )

    headers, err = headers_or_error()
    if err:
        return {"error": err}

    base = _base_url()

    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, verify=tls_verify()) as client:
            response = await client.post(
                f"{base}/memory/workflow/upload",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"Hub returned HTTP {e.response.status_code}: {e.response.text[:500]}"}
    except httpx.RequestError as e:
        return {"error": f"Hub request failed: {type(e).__name__}: {e}"}
