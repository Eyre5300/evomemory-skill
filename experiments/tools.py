"""Shared tool registry for the closed-loop agents.

One definition per tool, rendered into both Anthropic and OpenAI tool-call schemas
so the producer (Claude) and consumer (qwen) expose an identical tool surface — the
fair-comparison requirement from the proposal. Start minimal (a calculator); add
web-search / file tools here when wiring real GAIA tasks.
"""

from __future__ import annotations

import ast
import operator
from dataclasses import dataclass
from typing import Any, Callable

# --- a safe arithmetic evaluator (no eval) --------------------------------

_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARYOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOPS:
        return _UNARYOPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("unsupported expression")


def calculate(expression: str) -> str:
    """Evaluate a basic arithmetic expression (+ - * / // % ** and parentheses)."""
    try:
        tree = ast.parse(str(expression), mode="eval")
        return str(_safe_eval(tree.body))
    except Exception as e:
        return f"ERROR: {e}"


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema object
    fn: Callable[..., str]


REGISTRY: dict[str, Tool] = {
    "calculate": Tool(
        name="calculate",
        description="Evaluate a basic arithmetic expression and return the numeric result.",
        parameters={
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "e.g. (3+4)*2 ** 5"}
            },
            "required": ["expression"],
        },
        fn=calculate,
    ),
}


def anthropic_tools() -> list[dict[str, Any]]:
    return [
        {"name": t.name, "description": t.description, "input_schema": t.parameters}
        for t in REGISTRY.values()
    ]


def openai_tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
        }
        for t in REGISTRY.values()
    ]


def execute(name: str, args: dict[str, Any]) -> str:
    tool = REGISTRY.get(name)
    if tool is None:
        return f"ERROR: unknown tool {name!r}"
    try:
        return tool.fn(**(args or {}))
    except Exception as e:
        return f"ERROR: {e}"
