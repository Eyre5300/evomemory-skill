"""EvoMemory Sync: LangChain middleware + optional CLI scripts.

The LangChain middleware and workflow modules are *optional*: they require
``langchain`` and the full skill stack. The experiment harness (Pareto proposal)
only uses the lightweight, dependency-free metric modules — ``encoder``,
``experience_quality``, ``quality_sidecar``, ``context_density`` — so the heavy
imports below are guarded. This keeps ``from evomemory_sync import encoder`` working
on a minimal experiment-only environment (e.g. the GPU box) without langchain.
"""

try:
    from .agent_tools import (
        AGENT_SYSTEM_PROMPT_EXTENSION,
        headers_or_error,
        patch_experiment_parent_link,
        patch_workflow_parent_links,
        share_failed_ideation,
        share_successful_experiment,
        share_workflow,
    )
    from .middleware import EvoMemorySyncMiddleware
    from .workflow_executor import WorkflowRunner, download_workflow
    from .workflow_exporter import export_and_upload_workflow
    from .workflow_schema import EvoWorkflow, LLMConfig, WorkflowEnvironment

    __all__ = [
        "AGENT_SYSTEM_PROMPT_EXTENSION",
        "headers_or_error",
        "EvoWorkflow",
        "EvoMemorySyncMiddleware",
        "LLMConfig",
        "WorkflowEnvironment",
        "WorkflowRunner",
        "download_workflow",
        "export_and_upload_workflow",
        "patch_experiment_parent_link",
        "patch_workflow_parent_links",
        "share_failed_ideation",
        "share_successful_experiment",
        "share_workflow",
    ]
except ImportError:  # optional langchain stack absent (experiment-only env)
    __all__ = []
