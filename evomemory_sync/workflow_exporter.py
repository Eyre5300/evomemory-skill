"""
将标准化的 ``EvoWorkflow`` 映射后走 ``upload_memory_record``（含 Curator / 语义去重）。

环境变量与 ``evomemory_sync.agent_tools`` 一致：``EVOMEMORY_API_URL``（可选，覆盖 base）、
``EVOMEMORY_API_BASE_URL``、``EVOMEMORY_API_TOKEN`` / ``EVOMEMORY_AGENT_TOKEN``。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from .agent_tools import headers_or_error
from .uploader import upload_memory_record
from .workflow_schema import EvoWorkflow


def _strip_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


async def export_and_upload_workflow(
    workflow: EvoWorkflow,
    parent_experiment_id: Optional[str] = None,
    parent_ideation_id: Optional[str] = None,
) -> dict[str, Any]:
    """将 EvoWorkflow 转为 Hub workflow 草稿并上传。"""
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
    payload = _strip_none(
        {
            "memory_type": "workflow",
            "title": workflow.title,
            "description": workflow.description,
            "prompt_templates": prompt_templates_str,
            "tool_configuration": json.dumps(tool_config_payload, ensure_ascii=False),
            "parent_experiment_id": parent_experiment_id,
            "parent_ideation_id": parent_ideation_id,
        }
    )
    _, err = headers_or_error()
    if err:
        return {"error": err}
    try:
        out = await asyncio.to_thread(upload_memory_record, payload)
        if out is None:
            return {"error": "upload skipped or empty payload"}
        return out
    except Exception as e:
        return {"error": f"Hub upload failed: {type(e).__name__}: {e}"}
