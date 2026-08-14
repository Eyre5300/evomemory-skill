"""Heuristic assessment of whether an agent run truly succeeded."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from langchain_core.messages import BaseMessage, ToolMessage

ValidationStatus = Literal["not_applicable", "passed", "failed"]

_EXIT_CODE_RE = re.compile(
    r"(?:Exit code|exit_code)\s*[:=]\s*(\d+)",
    re.IGNORECASE,
)
_VALIDATION_HINT_RE = re.compile(
    r"(?:"
    r"ground\s*truth|真值|expected\s+(?:result|output|value)|"
    r"self[- ]?check|自检|validation|validate|verify\s+result|"
    r"pytest|unittest|assert(?:ion)?|benchmark|"
    r"accuracy|f1(?:\s*score)?|auc|metric|compare\s+with|与.+一致"
    r")",
    re.IGNORECASE,
)
_VALIDATION_PASS_RE = re.compile(
    r"(?:"
    r"\[OK\]|all tests passed|tests?\s+passed|\d+\s+passed|"
    r"validation passed|self[- ]?check passed|自检通过|"
    r"matches?\s+expected|match(?:es)?\s+ground\s*truth|与真值一致|结果一致|"
    r"verification passed|assertions?\s+passed"
    r")",
    re.IGNORECASE,
)
_VALIDATION_FAIL_RE = re.compile(
    r"(?:"
    r"\[FAILED\]|AssertionError|assertions?\s+failed|validation failed|"
    r"self[- ]?check failed|自检未通过|自检失败|"
    r"does not match|mismatch|不一致|未通过|"
    r"\d+\s+failed|tests?\s+failed|FAILED\b"
    r")",
    re.IGNORECASE,
)
_RUNTIME_FAIL_HEAD_RE = re.compile(
    r"(?:"
    r"Traceback \(most recent call last\)|"
    r"\[TOOL ERROR\]|Error invoking tool|Command failed|"
    r"SyntaxError:|NameError:|TypeError:|ValueError:|RuntimeError:"
    r")",
    re.IGNORECASE,
)
_EXECUTION_TOOL_NAMES = frozenset({"execute", "shell", "bash", "run_python", "python"})
_NON_EXECUTION_TOOL_NAMES = frozenset(
    {
        "search_evomemory",
        "apply_evomemory",
        "delete_evomemory",
        "list_my_evomemory",
        "share_recipe",
        "share_workflow",
        "share_successful_experiment",
        "share_failed_ideation",
    }
)


def _text_content(msg: BaseMessage) -> str:
    c = getattr(msg, "content", "")
    if isinstance(c, str):
        return c.strip()
    if isinstance(c, list):
        parts: list[str] = []
        for block in c:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts).strip()
    return str(c).strip()


def _tool_messages(messages: list[BaseMessage]) -> list[ToolMessage]:
    return [m for m in messages if isinstance(m, ToolMessage)]


def _nonzero_exit_codes(text: str) -> list[int]:
    codes: list[int] = []
    for m in _EXIT_CODE_RE.finditer(text):
        try:
            codes.append(int(m.group(1)))
        except ValueError:
            continue
    for m in re.finditer(r'"exit_code"\s*:\s*(\d+)', text):
        try:
            codes.append(int(m.group(1)))
        except ValueError:
            continue
    return codes


def _has_tool_invocation_error(msg: ToolMessage) -> bool:
    status = getattr(msg, "status", None)
    body = _text_content(msg)
    if status == "error":
        return True
    if "[TOOL ERROR]" in body:
        return True
    if body.startswith("[FAILED]"):
        return True
    return False


def _has_code_runtime_error(msg: ToolMessage) -> bool:
    if _has_tool_invocation_error(msg):
        return True
    body = _text_content(msg)
    if not body:
        return False
    for code in _nonzero_exit_codes(body):
        if code != 0:
            return True
    head = "\n".join(body.splitlines()[:5])
    if _RUNTIME_FAIL_HEAD_RE.search(head):
        return True
    if body.startswith("[FAILED]"):
        return True
    return False


def _is_execution_tool_message(msg: ToolMessage) -> bool:
    name = str(getattr(msg, "name", "") or "")
    if name in _EXECUTION_TOOL_NAMES:
        return True
    if name in _NON_EXECUTION_TOOL_NAMES:
        return False
    return bool(_EXIT_CODE_RE.search(_text_content(msg)))


def _execution_tool_bodies(messages: list[BaseMessage]) -> list[str]:
    bodies: list[str] = []
    for tm in _tool_messages(messages):
        if _is_execution_tool_message(tm):
            bodies.append(_text_content(tm))
    if not bodies:
        for tm in _tool_messages(messages):
            bodies.append(_text_content(tm))
    return bodies


def _assess_validation(task: str, messages: list[BaseMessage]) -> dict[str, Any]:
    bodies = _execution_tool_bodies(messages)
    combined = "\n".join([task, *bodies[-8:]])
    if not _VALIDATION_HINT_RE.search(combined):
        return {"status": "not_applicable", "reason": "no self-check or ground-truth signals"}

    tail = "\n".join(bodies[-3:]) if bodies else combined
    if _VALIDATION_FAIL_RE.search(tail):
        return {"status": "failed", "reason": "validation or ground-truth mismatch detected"}
    if _VALIDATION_PASS_RE.search(tail):
        return {"status": "passed", "reason": "validation or ground-truth match detected"}

    for body in reversed(bodies):
        codes = _nonzero_exit_codes(body)
        if codes:
            if any(c != 0 for c in codes):
                return {"status": "failed", "reason": f"non-zero exit code after validation run: {codes[-1]}"}
            if codes[-1] == 0:
                return {"status": "passed", "reason": "validation command exited 0"}

    # Validation was expected but outcome unclear → conservative failure.
    return {"status": "failed", "reason": "self-check/ground-truth expected but outcome unclear"}


def assess_run_outcome(messages: list[BaseMessage], *, task: str = "") -> dict[str, Any]:
    """Return success flags for middleware routing.

    Success means:
    - no tool invocation errors
    - no code/runtime errors in execute outputs (non-zero exit, tracebacks, [FAILED])
    - when self-check or ground truth is applicable: validation passed or matches
    """
    tool_msgs = _tool_messages(messages)
    has_tool_error = any(_has_tool_invocation_error(m) for m in tool_msgs)
    has_code_runtime_error = any(
        _has_code_runtime_error(m) for m in tool_msgs if _is_execution_tool_message(m)
    )
    validation = _assess_validation(task, messages)
    val_status: ValidationStatus = validation["status"]

    run_success = (
        not has_tool_error
        and not has_code_runtime_error
        and val_status in ("not_applicable", "passed")
    )

    return {
        "run_success_flag": run_success,
        "has_tool_error_flag": has_tool_error,
        "has_code_runtime_error_flag": has_code_runtime_error,
        "validation_status": val_status,
        "validation_reason": validation.get("reason", ""),
    }
