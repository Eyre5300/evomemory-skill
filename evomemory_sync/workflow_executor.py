"""
下载并反序列化 Hub 工作流，提供与具体框架解耦的执行器入口。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Optional

import httpx

from .agent_tools import _base_url
from .uploader import (
    BROWSER_UA,
    DEFAULT_ACCEPT,
    DEFAULT_ACCEPT_LANGUAGE,
    env,
    tls_verify,
)
from .workflow_schema import EvoWorkflow, LLMConfig, WorkflowEnvironment

_DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


def _optional_auth_headers() -> dict[str, str]:
    """下载公开工作流时通常无需鉴权；若本地有 token 则自动附带。"""
    token = env("EVOMEMORY_API_TOKEN") or env("EVOMEMORY_AGENT_TOKEN")
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": DEFAULT_ACCEPT,
        "Accept-Language": DEFAULT_ACCEPT_LANGUAGE,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _parse_json_dict(raw: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return dict(fallback)
    text = raw.strip()
    if not text:
        return dict(fallback)
    try:
        parsed = json.loads(text)
    except Exception:
        return dict(fallback)
    return parsed if isinstance(parsed, dict) else dict(fallback)


async def download_workflow(memory_id: str) -> EvoWorkflow:
    """从 EvoMemory 获取工作流详情并反序列化为 EvoWorkflow 对象。"""
    base = _base_url()
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, verify=tls_verify()) as client:
        response = await client.get(
            f"{base}/memory/workflow/{memory_id}",
            headers=_optional_auth_headers(),
        )
        response.raise_for_status()
        raw = response.json()

    data = raw.get("result", raw) if isinstance(raw, dict) else {}
    if not isinstance(data, dict):
        data = {}

    prompts = _parse_json_dict(
        data.get("prompt_templates"),
        {"system": str(data.get("prompt_templates") or ""), "user_template": "{input}"},
    )
    prompts.setdefault("system", "")
    prompts.setdefault("user_template", "{input}")

    tool_config = _parse_json_dict(data.get("tool_configuration"), {})
    llm_cfg = tool_config.get("llm_config") if isinstance(tool_config.get("llm_config"), dict) else {}
    env_cfg = tool_config.get("environment") if isinstance(tool_config.get("environment"), dict) else {}
    tools = tool_config.get("tools") if isinstance(tool_config.get("tools"), list) else []
    metadata = tool_config.get("metadata") if isinstance(tool_config.get("metadata"), dict) else {}
    version = str(tool_config.get("version") or "1.0")

    return EvoWorkflow(
        version=version,
        title=str(data.get("title") or "Downloaded Workflow"),
        description=str(data.get("description") or ""),
        prompts={k: str(v) for k, v in prompts.items()},
        llm_config=LLMConfig(**llm_cfg),
        environment=WorkflowEnvironment(**env_cfg),
        tools=[str(t) for t in tools],
        metadata=metadata,
    )


class WorkflowRunner:
    """
    通用工作流执行器底座。

    你可以在子类中实现 ``_execute``，将标准化 workflow 对接 LangChain、AutoGen 或其他框架。
    """

    def __init__(self, workflow: EvoWorkflow, tool_registry: dict[str, Callable[..., Any]]):
        self.workflow = workflow
        self.tool_registry = tool_registry
        self.loaded_tools = self._load_tools()

    def _load_tools(self) -> list[Callable[..., Any]]:
        """根据 workflow.tools 从本地注册表加载 Python 工具函数。"""
        loaded: list[Callable[..., Any]] = []
        for tool_name in self.workflow.tools:
            fn = self.tool_registry.get(tool_name)
            if fn is None:
                print(
                    f"Warning: Tool '{tool_name}' required by workflow "
                    "is not registered locally."
                )
                continue
            loaded.append(fn)
        return loaded

    def _build_prompts(self, input_variables: dict[str, Any]) -> tuple[str, str]:
        system_prompt = self.workflow.prompts.get("system", "")
        template = self.workflow.prompts.get("user_template", "")
        try:
            user_prompt = template.format(**input_variables)
        except Exception:
            # 避免模板占位符缺失导致整个执行崩溃，退化为原模板
            user_prompt = template
        return system_prompt, user_prompt

    def _execute(
        self,
        system_prompt: str,
        user_prompt: str,
        loaded_tools: list[Callable[..., Any]],
    ) -> str:
        """
        框架无关的占位执行入口。建议在子类中覆盖该方法。
        """
        return (
            "Workflow execution is framework-specific. "
            "Subclass WorkflowRunner and implement _execute()."
        )

    def run(self, input_variables: Optional[dict[str, Any]] = None) -> str:
        """
        组装 prompt + tools 并调用底层执行逻辑。
        """
        vars_safe = input_variables or {}
        system_prompt, user_prompt = self._build_prompts(vars_safe)

        print(f"--- 正在执行工作流: {self.workflow.title} ---")
        print(f"使用模型: {self.workflow.llm_config.model_name}")
        print(f"加载工具: {[t.__name__ for t in self.loaded_tools]}")
        print("---------------------------------------")

        return self._execute(system_prompt, user_prompt, self.loaded_tools)
