"""Recipe (经验卡) Hub text fields — pass through LLM-written prose; no template stitching."""

from __future__ import annotations

from typing import Any

from .env_loader import env as _env

# Semantic dimensions the Extractor/Curator must cover in prose (prompt guidance only).
PROBLEM_DIMENSIONS = ("task_type", "domain", "constraints", "state")
SOLUTION_DIMENSIONS = ("method", "parameters", "rationale")
ENV_SNAPSHOT_DIMENSIONS = ("creator", "software_dependencies", "tool_dependencies", "environment")

# Legacy nested keys (deprecated — do not stitch in code).
PROBLEM_KEYS = PROBLEM_DIMENSIONS
SOLUTION_KEYS = SOLUTION_DIMENSIONS
ENV_SNAPSHOT_KEYS = ENV_SNAPSHOT_DIMENSIONS


def default_agent_creator(metadata: dict[str, Any] | None = None) -> str:
    """Build creator identifier: model name + instance id."""
    meta = metadata or {}
    model = str(
        meta.get("model")
        or _env("EVOMEMORY_AGENT_MODEL")
        or _env("EVOMEMORY_EXTRACTOR_MODEL")
        or ""
    ).strip()
    instance = str(meta.get("instance_id") or _env("EVOMEMORY_AGENT_INSTANCE_ID") or "").strip()
    if model and instance:
        return f"{model} + {instance}"
    if model:
        return model
    if instance:
        return f"agent + {instance}"
    return ""


def _passthrough_section(data: dict[str, Any], key: str) -> str:
    """Return LLM-authored paragraph text; never template-stitch nested dicts."""
    raw = data.get(key)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if isinstance(raw, dict):
        # Deprecated shape from older prompts — do not fill-in-the-blank in code.
        return ""
    return ""


def format_problem_section(data: dict[str, Any]) -> str:
    return _passthrough_section(data, "problem")


def format_solution_section(data: dict[str, Any]) -> str:
    return _passthrough_section(data, "solution")


def format_env_snapshot_section(data: dict[str, Any]) -> str:
    raw = data.get("env_snapshot")
    if isinstance(raw, dict):
        return ""

    text = _passthrough_section(data, "env_snapshot")
    if text:
        return text

    # Only when the model omitted env_snapshot entirely: minimal creator fallback.
    meta = data.get("_agent_metadata")
    creator = default_agent_creator(meta if isinstance(meta, dict) else None)
    if creator:
        return f"本经验由 {creator} 在运行过程中总结并归档。"
    legacy = data.get("env_snapshot")
    if isinstance(legacy, str) and legacy.strip():
        return legacy.strip()
    return ""


def prepare_recipe_hub_fields(data: dict[str, Any]) -> dict[str, str]:
    """Map extractor/curator recipe JSON to Hub POST body text fields."""
    trigger = str(data.get("trigger") or "").strip()
    problem = format_problem_section(data)
    solution = format_solution_section(data)
    env_snap = format_env_snapshot_section(data)
    result = str(data.get("result") or "").strip()
    tags_val = data.get("tags")
    if isinstance(tags_val, list):
        tags = ",".join(str(t) for t in tags_val)
    else:
        tags = str(tags_val or "").strip()
    return {
        "trigger": trigger,
        "problem": problem,
        "solution": solution,
        "env_snapshot": env_snap,
        "result": result,
        "tags": tags,
    }
