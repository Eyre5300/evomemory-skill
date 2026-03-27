"""
下载并反序列化 Hub 工作流，提供与具体框架解耦的执行器入口。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Optional

import httpx
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

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
    """基于 LangGraph 的动态工作流执行器。"""

    def __init__(self, workflow: EvoWorkflow, tool_registry: dict[str, Callable[..., Any]]):
        self.workflow = workflow
        self.tool_registry = tool_registry
        self.loaded_tools = self._load_tools()

    def _load_tools(self) -> list[BaseTool | Callable[..., Any]]:
        """加载工具。注册表中的工具建议是 BaseTool 或 @tool 装饰函数。"""
        loaded: list[BaseTool | Callable[..., Any]] = []
        for tool_name in self.workflow.tools:
            fn = self.tool_registry.get(tool_name)
            if fn is None:
                print(f"[警告] 工作流需要的工具 '{tool_name}' 在本地注册表中未找到。")
                continue
            loaded.append(fn)
        return loaded

    def run(self, input_variables: Optional[dict[str, Any]] = None) -> str:
        """组装并运行 LangGraph ReAct 执行图。"""
        vars_safe = input_variables or {}
        llm = ChatOpenAI(
            model=self.workflow.llm_config.model_name,
            temperature=self.workflow.llm_config.temperature,
            max_tokens=self.workflow.llm_config.max_tokens,
        )

        system_prompt = self.workflow.prompts.get("system", "")
        user_template = self.workflow.prompts.get("user_template", "{input}")
        try:
            user_input = user_template.format(**vars_safe)
        except KeyError as e:
            raise ValueError(f"缺少填充用户提示词所需的变量: {e}") from e

        print(f"--- 正在执行工作流: {self.workflow.title} ---")
        print(
            f"模型: {self.workflow.llm_config.model_name} | 工具: "
            f"{[getattr(t, 'name', getattr(t, '__name__', str(t))) for t in self.loaded_tools]}"
        )
        print("---------------------------------------")

        agent_executor = create_react_agent(
            llm,
            self.loaded_tools,
            state_modifier=system_prompt,
        )
        result_state = agent_executor.invoke({"messages": [("user", user_input)]})
        final_message = result_state["messages"][-1].content
        print("--- 执行结束 ---")
        return str(final_message)
