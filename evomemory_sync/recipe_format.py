"""Recipe (经验卡) Hub text fields — pass through LLM-written prose; no template stitching."""

from __future__ import annotations

import re
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

# Evaluation identifiers describe where a problem came from, not when an
# experience is useful.  They must never become a public recipe title: doing so
# turns a transferable card into a benchmark lookup key and can leak evaluation
# identity into retrieval.  This guard also protects manual uploads and curator
# fallbacks where prompt compliance alone is insufficient.
_BENCHMARK_NAME_RE = re.compile(
    r"(?i)\b(?:sanitized[\s_-]*)?(?:mbpp|humaneval|human[\s_-]*eval|"
    r"livecodebench|live[\s_-]*code[\s_-]*bench|apps|codecontests|"
    r"swe[\s_-]*bench|bigcodebench|ds[\s_-]*1000)\b"
)
_BENCHMARK_ID_RE = re.compile(
    r"(?ix)"
    r"(?:\b(?:benchmark|test|eval)?[\s_-]*"
    r"(?:task|problem|case|sample|item)[\s_-]*(?:id)?\s*[:=#/-]?\s*[a-z]*\d+[a-z0-9_.-]*\b)"
    r"|(?:\b(?:task|problem|case|sample|item)[\s_-]*id\s*[:=#/-]?\s*[a-z0-9_.-]+\b)"
    r"|(?:\b(?:题号|任务编号|问题编号|样例编号)\s*[:=#：-]?\s*[a-z0-9_.-]+\b)"
    r"|(?:第\s*\d+\s*题)"
)
_GENERIC_PROBLEM_LEAD_RE = re.compile(
    r"(?i)^(?:please\s+)?(?:write|implement|create|build)\s+"
    r"(?:a\s+)?(?:python\s+)?(?:function|method|program)\s+to\s+"
)


def _strip_evaluation_identity(text: str) -> str:
    """Remove benchmark names and case identifiers without rewriting semantics."""
    cleaned = _BENCHMARK_NAME_RE.sub(" ", str(text or ""))
    cleaned = _BENCHMARK_ID_RE.sub(" ", cleaned)
    cleaned = re.sub(r"(?i)\b(?:task|problem|case|benchmark|test)\b\s*[:=#/-]?\s*$", " ", cleaned)
    cleaned = re.sub(r"[\s:：#=/|_-]+", " ", cleaned).strip(" \t\r\n-–—:：,，;；|#")
    return cleaned


def transferable_recipe_title(trigger: str, problem: str, *, max_length: int = 160) -> str:
    """Return a semantic recipe title with evaluation identity removed.

    Prefer the model-authored trigger when it contains actual problem semantics.
    If it consisted only of a benchmark/case marker, recover a title from the
    problem paragraph rather than publishing an empty or benchmark-specific key.
    """
    title = _strip_evaluation_identity(trigger)
    if len(re.sub(r"\W", "", title, flags=re.UNICODE)) < 4:
        fallback = re.split(r"[\r\n。！？!?]", str(problem or ""), maxsplit=1)[0]
        fallback = _GENERIC_PROBLEM_LEAD_RE.sub("", fallback.strip())
        title = _strip_evaluation_identity(fallback)
    title = re.sub(r"\s+", " ", title).strip()
    return title[:max_length].rstrip() or "可复用问题解决经验"


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
    problem = format_problem_section(data)
    trigger = transferable_recipe_title(str(data.get("trigger") or ""), problem)
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
