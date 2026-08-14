from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class LLMConfig(BaseModel):
    model_name: str = Field(default="gpt-4o", description="驱动工作流的模型名称")
    temperature: float = Field(default=0.0, description="采样温度")
    max_tokens: Optional[int] = Field(default=None, description="最大输出长度")


class WorkflowEnvironment(BaseModel):
    hardware_requirements: Optional[str] = None
    software_dependencies: Optional[str] = None


class WorkflowPermissions(BaseModel):
    """Untrusted workflow permission request; it never grants local access by itself."""

    tools: List[str] = Field(default_factory=list)
    network_domains: List[str] = Field(default_factory=list)
    read_paths: List[str] = Field(default_factory=list)
    write_paths: List[str] = Field(default_factory=list)
    allow_shell: bool = False

    @field_validator("tools", "network_domains", "read_paths", "write_paths")
    @classmethod
    def unique_nonempty_values(cls, value: List[str]) -> List[str]:
        clean: list[str] = []
        for raw in value:
            item = str(raw).strip()
            if item and item not in clean:
                clean.append(item)
        return clean


class WorkflowExecutionPolicy(BaseModel):
    max_steps: int = Field(default=25, ge=1, le=100)
    max_output_chars: int = Field(default=20_000, ge=100, le=200_000)


class EvoWorkflow(BaseModel):
    """标准的 EvoMemory 工作流序列化格式。"""

    version: str = "1.0"
    title: str
    description: str
    environment: WorkflowEnvironment = Field(default_factory=WorkflowEnvironment)
    llm_config: LLMConfig = Field(default_factory=LLMConfig)
    prompts: Dict[str, str] = Field(
        ..., description="必须包含 'system' 和 'user_template' 键"
    )
    tools: List[str] = Field(
        default_factory=list,
        description="需要调用的核心工具名称列表，如 ['web_search', 'python_repl']",
    )
    permissions: WorkflowPermissions = Field(default_factory=WorkflowPermissions)
    execution_policy: WorkflowExecutionPolicy = Field(default_factory=WorkflowExecutionPolicy)
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="可选扩展元数据，供后续版本平滑扩展",
    )

    @field_validator("prompts")
    @classmethod
    def validate_prompts(cls, value: Dict[str, str]) -> Dict[str, str]:
        required = {"system", "user_template"}
        missing = [k for k in required if k not in value or not str(value[k]).strip()]
        if missing:
            raise ValueError(
                "prompts 缺少必填键或值为空: " + ", ".join(sorted(missing))
            )
        return value

    @field_validator("tools")
    @classmethod
    def validate_tools(cls, value: List[str]) -> List[str]:
        clean: list[str] = []
        for raw in value:
            name = str(raw).strip()
            if not name:
                raise ValueError("tools contains an empty tool name")
            if name not in clean:
                clean.append(name)
        return clean
