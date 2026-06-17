"""Recipe (经验卡) structured field formatting for Hub text columns."""

from __future__ import annotations

import re
from typing import Any

from .env_loader import env as _env

PROBLEM_KEYS = ("task_type", "domain", "constraints", "state")
SOLUTION_KEYS = ("method", "parameters", "rationale")
ENV_SNAPSHOT_KEYS = ("creator", "software_dependencies", "tool_dependencies", "environment")


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


def _strip_trailing_period(text: str) -> str:
    return text.rstrip().rstrip("。.").strip()


def _normalize_phrase(text: str) -> str:
    """Turn LLM-style compound labels into natural Chinese prose fragments."""
    s = _strip_trailing_period(text)
    # e.g. "Python 开发 / Windows 环境" -> "Python 开发、Windows 环境"
    s = re.sub(r"\s*/\s*", "、", s)
    s = re.sub(r"\s*\\\s*", "、", s)
    # Single & only (preserve shell operators like &&)
    s = re.sub(r"(?<!&)&(?!&)", "与", s)
    s = re.sub(r"\s+与\s+", "与", s)
    return s.strip()


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
        pass

    for k in keys:
        if out.get(k):
            continue
        flat = data.get(f"{section}_{k}")
        if flat is not None and str(flat).strip():
            out[k] = str(flat).strip()

    return out


def _format_problem_prose(parts: dict[str, str]) -> str:
    task_type = _normalize_phrase(parts.get("task_type", ""))
    domain = _normalize_phrase(parts.get("domain", ""))
    constraints = _normalize_phrase(parts.get("constraints", ""))
    state = _normalize_phrase(parts.get("state", ""))

    sentences: list[str] = []
    if task_type and domain:
        sentences.append(f"在{domain}场景下进行{task_type}")
    elif task_type:
        sentences.append(f"这是一项{task_type}任务")
    elif domain:
        sentences.append(f"任务领域为{domain}")

    if constraints:
        sentences.append(f"约束条件包括{constraints}")
    if state:
        sentences.append(f"初始状态为{state}")

    if not sentences:
        return ""
    return "。".join(sentences) + "。"


def _format_solution_prose(parts: dict[str, str]) -> str:
    method = _normalize_phrase(parts.get("method", ""))
    parameters = _normalize_phrase(parts.get("parameters", ""))
    rationale = _normalize_phrase(parts.get("rationale", ""))

    sentences: list[str] = []
    if method and parameters:
        sentences.append(f"采取{method}，关键参数为{parameters}")
    elif method:
        sentences.append(method)
    elif parameters:
        sentences.append(f"关键参数为{parameters}")

    if rationale:
        if rationale.startswith("因为"):
            sentences.append(rationale)
        else:
            sentences.append(f"选择该方案是因为{rationale}")

    if not sentences:
        return ""
    return "。".join(sentences) + "。"


def _format_env_prose(parts: dict[str, str]) -> str:
    creator = _normalize_phrase(parts.get("creator", ""))
    software = _normalize_phrase(parts.get("software_dependencies", ""))
    tools = _normalize_phrase(parts.get("tool_dependencies", ""))
    environment = _normalize_phrase(parts.get("environment", ""))

    sentences: list[str] = []
    if creator:
        sentences.append(f"由 {creator} 产出")

    details: list[str] = []
    if software:
        details.append(f"软件方面依赖 {software}")
    if tools:
        details.append(f"使用 {tools} 相关工具")
    if environment:
        details.append(f"运行于 {environment} 环境")

    if details:
        sentences.append("；".join(details))

    if not sentences:
        return ""
    return "。".join(sentences) + "。"


def format_problem_section(data: dict[str, Any]) -> str:
    parts = _section_dict(data, "problem", PROBLEM_KEYS)
    if not any(parts.values()):
        legacy = data.get("problem")
        if isinstance(legacy, str) and legacy.strip():
            return legacy.strip()
        return ""
    return _format_problem_prose(parts)


def format_solution_section(data: dict[str, Any]) -> str:
    parts = _section_dict(data, "solution", SOLUTION_KEYS)
    if not any(parts.values()):
        legacy = data.get("solution")
        if isinstance(legacy, str) and legacy.strip():
            return legacy.strip()
        return ""
    return _format_solution_prose(parts)


def format_env_snapshot_section(data: dict[str, Any]) -> str:
    parts = _section_dict(data, "env_snapshot", ENV_SNAPSHOT_KEYS)
    meta = data.get("_agent_metadata")
    if not parts.get("creator"):
        creator = default_agent_creator(meta if isinstance(meta, dict) else None)
        if creator:
            parts["creator"] = creator

    if not parts.get("software_dependencies"):
        for alt in ("software_dependencies", "environment_constraints"):
            v = data.get(alt)
            if isinstance(v, str) and v.strip():
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
        return f"由 {creator} 产出。" if creator else ""

    return _format_env_prose(parts)


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
