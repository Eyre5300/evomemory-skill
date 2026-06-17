"""Recipe (经验卡) structured field formatting for Hub text columns."""

from __future__ import annotations

from typing import Any

from .env_loader import env as _env

PROBLEM_KEYS = ("task_type", "domain", "constraints", "state")
SOLUTION_KEYS = ("method", "parameters", "rationale")
ENV_SNAPSHOT_KEYS = ("creator", "software_dependencies", "tool_dependencies", "environment")

_PROBLEM_LABELS = {
    "task_type": "task_type",
    "domain": "domain",
    "constraints": "constraints",
    "state": "state",
}
_SOLUTION_LABELS = {
    "method": "method",
    "parameters": "parameters",
    "rationale": "rationale",
}
_ENV_LABELS = {
    "creator": "creator",
    "software_dependencies": "software_dependencies",
    "tool_dependencies": "tool_dependencies",
    "environment": "environment",
}


def default_agent_creator(metadata: dict[str, Any] | None = None) -> str:
    """Build creator line: model name + instance id."""
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


def _section_dict(
    data: dict[str, Any],
    section: str,
    keys: tuple[str, ...],
) -> dict[str, str]:
    """Read a recipe section from nested dict, flat section_* keys, or legacy string."""
    out: dict[str, str] = {}
    raw = data.get(section)
    if isinstance(raw, dict):
        for k in keys:
            v = raw.get(k)
            if v is not None and str(v).strip():
                out[k] = str(v).strip()
    elif isinstance(raw, str) and raw.strip():
        # Legacy free-text: keep as state/method/creator catch-all if no structured keys
        pass

    for k in keys:
        if out.get(k):
            continue
        flat = data.get(f"{section}_{k}")
        if flat is not None and str(flat).strip():
            out[k] = str(flat).strip()

    return out


def _format_labeled_block(parts: dict[str, str], labels: dict[str, str]) -> str:
    lines: list[str] = []
    for key, label in labels.items():
        val = parts.get(key, "").strip()
        if val:
            lines.append(f"{label}: {val}")
    return "\n".join(lines)


def format_problem_section(data: dict[str, Any]) -> str:
    parts = _section_dict(data, "problem", PROBLEM_KEYS)
    if not any(parts.values()):
        legacy = data.get("problem")
        if isinstance(legacy, str) and legacy.strip():
            return legacy.strip()
        return ""
    return _format_labeled_block(parts, _PROBLEM_LABELS)


def format_solution_section(data: dict[str, Any]) -> str:
    parts = _section_dict(data, "solution", SOLUTION_KEYS)
    if not any(parts.values()):
        legacy = data.get("solution")
        if isinstance(legacy, str) and legacy.strip():
            return legacy.strip()
        return ""
    return _format_labeled_block(parts, _SOLUTION_LABELS)


def format_env_snapshot_section(data: dict[str, Any]) -> str:
    parts = _section_dict(data, "env_snapshot", ENV_SNAPSHOT_KEYS)
    meta = data.get("_agent_metadata")
    if not parts.get("creator"):
        creator = default_agent_creator(meta if isinstance(meta, dict) else None)
        if creator:
            parts["creator"] = creator

    # Legacy aliases from extractor / share_recipe
    if not parts.get("software_dependencies"):
        for alt in ("software_dependencies", "env_snapshot", "environment_constraints"):
            v = data.get(alt)
            if isinstance(v, str) and v.strip() and alt != "env_snapshot":
                parts["software_dependencies"] = v.strip()
                break
    if isinstance(data.get("env_snapshot"), str) and data.get("env_snapshot") and not any(
        parts.values()
    ):
        return str(data["env_snapshot"]).strip()

    if not any(parts.values()):
        legacy = data.get("env_snapshot")
        if isinstance(legacy, str) and legacy.strip():
            return legacy.strip()
        creator = default_agent_creator(meta if isinstance(meta, dict) else None)
        return f"creator: {creator}" if creator else ""

    return _format_labeled_block(parts, _ENV_LABELS)


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
