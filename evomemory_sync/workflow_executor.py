"""
下载并反序列化 Hub 工作流，提供与具体框架解耦的执行器入口。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any, Literal, Optional

import logging

import httpx
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

logger = logging.getLogger("evomemory_sync.workflow_executor")

from .agent_tools import _base_url
from .constants import BROWSER_UA, DEFAULT_ACCEPT, DEFAULT_ACCEPT_LANGUAGE
from .uploader import env, tls_verify
from .workflow_schema import (
    EvoWorkflow,
    LLMConfig,
    WorkflowEnvironment,
    WorkflowExecutionPolicy,
    WorkflowPermissions,
)

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
    # 与 EvoWorkflow 校验对齐：旧版 Hub 可能仅存纯文本或非标准 JSON，补全非空键
    prompts_str = {k: str(v) for k, v in prompts.items()}
    if not prompts_str.get("system", "").strip():
        prompts_str["system"] = "You are a helpful assistant."
    if not prompts_str.get("user_template", "").strip():
        prompts_str["user_template"] = "{input}"

    tool_config = _parse_json_dict(data.get("tool_configuration"), {})
    llm_cfg = tool_config.get("llm_config") if isinstance(tool_config.get("llm_config"), dict) else {}
    env_cfg = tool_config.get("environment") if isinstance(tool_config.get("environment"), dict) else {}
    tools = tool_config.get("tools") if isinstance(tool_config.get("tools"), list) else []
    metadata = tool_config.get("metadata") if isinstance(tool_config.get("metadata"), dict) else {}
    permissions = tool_config.get("permissions") if isinstance(tool_config.get("permissions"), dict) else {}
    execution_policy = (
        tool_config.get("execution_policy")
        if isinstance(tool_config.get("execution_policy"), dict)
        else {}
    )
    version = str(tool_config.get("version") or "1.0")

    return EvoWorkflow(
        version=version,
        title=str(data.get("title") or "Downloaded Workflow"),
        description=str(data.get("description") or ""),
        prompts=prompts_str,
        llm_config=LLMConfig(**llm_cfg),
        environment=WorkflowEnvironment(**env_cfg),
        tools=[str(t) for t in tools],
        permissions=WorkflowPermissions(**permissions),
        execution_policy=WorkflowExecutionPolicy(**execution_policy),
        metadata=metadata,
    )


ToolCapability = Literal["network", "filesystem_read", "filesystem_write", "shell"]


@dataclass(frozen=True)
class WorkflowToolSpec:
    """Locally trusted tool registration with explicit capability metadata."""

    handler: BaseTool | Callable[..., Any]
    capabilities: frozenset[ToolCapability] = frozenset()


class WorkflowRunner:
    """基于 LangGraph 的动态工作流执行器。"""
    _SUPPORTED_PROVIDERS = {
        "openai",
        "custom-openai",
        "anthropic",
        "custom-anthropic",
    }

    def __init__(
        self,
        workflow: EvoWorkflow,
        tool_registry: dict[str, Callable[..., Any] | WorkflowToolSpec],
        *,
        approved_tools: set[str] | frozenset[str] | None = None,
        allow_legacy_unclassified: bool = False,
    ):
        self.workflow = workflow
        self.tool_registry = tool_registry
        self.approved_tools = frozenset(approved_tools or ())
        self.allow_legacy_unclassified = bool(allow_legacy_unclassified)
        self.loaded_tools = self._load_tools()

    def _load_tools(self) -> list[BaseTool | Callable[..., Any]]:
        """加载工具。注册表中的工具建议是 BaseTool 或 @tool 装饰函数。"""
        loaded: list[BaseTool | Callable[..., Any]] = []
        declared = set(self.workflow.permissions.tools)
        for tool_name in self.workflow.tools:
            if tool_name not in declared:
                logger.warning("工作流工具 '%s' 未在 permissions.tools 声明，已拒绝。", tool_name)
                continue
            if tool_name not in self.approved_tools:
                logger.warning("工作流工具 '%s' 未获本地 approved_tools 授权，已拒绝。", tool_name)
                continue
            registered = self.tool_registry.get(tool_name)
            if registered is None:
                logger.warning("工作流需要的工具 '%s' 在本地注册表中未找到。", tool_name)
                continue
            if isinstance(registered, WorkflowToolSpec):
                denied = self._denied_capabilities(registered.capabilities)
                if denied:
                    logger.warning("工作流工具 '%s' 缺少 manifest 权限 %s，已拒绝。", tool_name, sorted(denied))
                    continue
                loaded.append(registered.handler)
            elif self.allow_legacy_unclassified:
                loaded.append(registered)
            else:
                logger.warning("工作流工具 '%s' 没有 capability 元数据，默认拒绝。", tool_name)
        return loaded

    def _denied_capabilities(self, capabilities: frozenset[ToolCapability]) -> set[str]:
        permissions = self.workflow.permissions
        denied: set[str] = set()
        if "network" in capabilities and not permissions.network_domains:
            denied.add("network_domains")
        if "filesystem_read" in capabilities and not permissions.read_paths:
            denied.add("read_paths")
        if "filesystem_write" in capabilities and not permissions.write_paths:
            denied.add("write_paths")
        if "shell" in capabilities and not permissions.allow_shell:
            denied.add("allow_shell")
        return denied

    def _infer_provider(self, model_name: str) -> str:
        """
        推断模型提供商。

        优先级：
        1) metadata.llm_provider
        2) 环境变量 EVOMEMORY_LLM_PROVIDER
        3) 按模型名前缀推断
        """
        md_provider = str(self.workflow.metadata.get("llm_provider", "")).strip().lower()
        if md_provider:
            return md_provider
        env_provider = env("EVOMEMORY_LLM_PROVIDER", "").strip().lower()
        if env_provider:
            return env_provider

        name = (model_name or "").strip().lower()
        if name.startswith(("claude", "anthropic/")):
            return "anthropic"
        return "openai"

    @staticmethod
    def _require_env(var_name: str, *, reason: str) -> str:
        value = env(var_name, "").strip()
        if not value:
            raise RuntimeError(f"缺少环境变量 {var_name}（{reason}）。")
        return value

    def _validate_provider(self, provider: str) -> None:
        if provider not in self._SUPPORTED_PROVIDERS:
            allowed = ", ".join(sorted(self._SUPPORTED_PROVIDERS))
            raise ValueError(
                f"不支持的 llm_provider: {provider!r}。仅支持: {allowed}。"
            )

    def _build_chat_model(self) -> Any:
        """
        多模型工厂：
        - openai / custom-openai：ChatOpenAI（支持 OPENAI_BASE_URL / CUSTOM_OPENAI_BASE_URL）
        - anthropic / custom-anthropic：ChatAnthropic（支持 ANTHROPIC_BASE_URL / CUSTOM_ANTHROPIC_BASE_URL）
        """
        model_name = self.workflow.llm_config.model_name
        provider = self._infer_provider(model_name)
        self._validate_provider(provider)
        common_kwargs: dict[str, Any] = {
            "model": model_name,
            "temperature": self.workflow.llm_config.temperature,
        }
        if self.workflow.llm_config.max_tokens is not None:
            common_kwargs["max_tokens"] = self.workflow.llm_config.max_tokens

        if provider in {"anthropic", "custom-anthropic"}:
            try:
                from langchain_anthropic import ChatAnthropic
            except Exception as e:
                raise RuntimeError(
                    "当前 workflow 需要 Anthropic 模型，请安装 langchain-anthropic。"
                ) from e

            if provider == "custom-anthropic":
                base_url = self._require_env(
                    "CUSTOM_ANTHROPIC_BASE_URL",
                    reason="custom-anthropic 需要 Anthropic 兼容端点地址",
                )
                api_key = self._require_env(
                    "CUSTOM_ANTHROPIC_API_KEY",
                    reason="custom-anthropic 需要 API Key",
                )
            else:
                base_url = env("ANTHROPIC_BASE_URL")
                api_key = self._require_env(
                    "ANTHROPIC_API_KEY",
                    reason="anthropic provider 需要 API Key",
                )
            kwargs = dict(common_kwargs)
            if base_url:
                kwargs["base_url"] = base_url
            kwargs["api_key"] = api_key
            return ChatAnthropic(**kwargs)

        # default: OpenAI + OpenAI-compatible
        if provider == "custom-openai":
            base_url = self._require_env(
                "CUSTOM_OPENAI_BASE_URL",
                reason="custom-openai 需要 OpenAI 兼容端点地址",
            )
            api_key = self._require_env(
                "CUSTOM_OPENAI_API_KEY",
                reason="custom-openai 需要 API Key",
            )
        else:
            base_url = env("OPENAI_BASE_URL")
            api_key = self._require_env(
                "OPENAI_API_KEY",
                reason="openai provider 需要 API Key",
            )
        kwargs = dict(common_kwargs)
        if base_url:
            kwargs["base_url"] = base_url
        kwargs["api_key"] = api_key
        return ChatOpenAI(**kwargs)

    def run(self, input_variables: Optional[dict[str, Any]] = None) -> str:
        """组装并运行 LangGraph ReAct 执行图。"""
        vars_safe = input_variables or {}
        llm = self._build_chat_model()

        system_prompt = self.workflow.prompts.get("system", "")
        user_template = self.workflow.prompts.get("user_template", "{input}")
        try:
            user_input = user_template.format(**vars_safe)
        except KeyError as e:
            raise ValueError(f"缺少填充用户提示词所需的变量: {e}") from e

        logger.info("正在执行工作流: %s", self.workflow.title)
        logger.info(
            "模型: %s | 工具: %s",
            self.workflow.llm_config.model_name,
            [getattr(t, 'name', getattr(t, '__name__', str(t))) for t in self.loaded_tools],
        )

        agent_executor = create_react_agent(
            llm,
            self.loaded_tools,
            state_modifier=system_prompt,
        )
        result_state = agent_executor.invoke(
            {"messages": [("user", user_input)]},
            config={"recursion_limit": self.workflow.execution_policy.max_steps},
        )
        final_message = result_state["messages"][-1].content
        logger.info("工作流执行结束: %s", self.workflow.title)
        return str(final_message)[: self.workflow.execution_policy.max_output_chars]
