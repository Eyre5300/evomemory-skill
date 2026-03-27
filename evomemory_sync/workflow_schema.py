from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class LLMConfig(BaseModel):
    model_name: str = Field(default="gpt-4o", description="驱动工作流的模型名称")
    temperature: float = Field(default=0.0, description="采样温度")
    max_tokens: Optional[int] = Field(default=None, description="最大输出长度")


class WorkflowEnvironment(BaseModel):
    hardware_requirements: Optional[str] = None
    software_dependencies: Optional[str] = None


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
