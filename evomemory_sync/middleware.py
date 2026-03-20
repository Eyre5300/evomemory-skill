"""LangChain AgentMiddleware: after each agent run, extract + upload to EvoMemory Hub."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)

_DOTENV_LOADED = False


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _maybe_load_dotenv() -> None:
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    try:
        from .env_loader import load_env

        load_env()
    except Exception:
        pass


def _sync_enabled() -> bool:
    if _env_bool("EVOMEMORY_SYNC_ENABLED", True) is False:
        return False
    token = os.getenv("EVOMEMORY_API_TOKEN", "").strip()
    if not token:
        logger.debug("evomemory_sync: EVOMEMORY_API_TOKEN missing, middleware idle")
        return False
    return True


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


def _collect_tool_code_and_errors(messages: list[BaseMessage]) -> tuple[str, str, bool]:
    """Return (aggregated_code, error_text, has_tool_error)."""
    code_chunks: list[str] = []
    error_chunks: list[str] = []
    has_tool_error = False

    for msg in messages:
        if isinstance(msg, AIMessage):
            calls = getattr(msg, "tool_calls", None) or []
            for tc in calls:
                if isinstance(tc, dict):
                    name = str(tc.get("name") or "")
                    args = tc.get("args") or {}
                else:
                    name = str(getattr(tc, "name", "") or "")
                    args = getattr(tc, "args", None) or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                if not isinstance(args, dict):
                    args = {}
                if name == "execute" and args.get("command"):
                    code_chunks.append(f"[execute]\n{args['command']}")
                elif args.get("code"):
                    code_chunks.append(f"[{name}]\n{args['code']}")
                elif args.get("command"):
                    code_chunks.append(f"[{name}]\n{args['command']}")

        if isinstance(msg, ToolMessage):
            status = getattr(msg, "status", None)
            if status == "error":
                has_tool_error = True
            body = _text_content(msg)
            if status == "error" or "[TOOL ERROR]" in body:
                error_chunks.append(body[:8000])

    return "\n\n---\n\n".join(code_chunks), "\n\n---\n\n".join(error_chunks), has_tool_error


def _first_human_task(messages: list[BaseMessage]) -> str:
    for msg in messages:
        if isinstance(msg, HumanMessage):
            t = _text_content(msg)
            if t:
                return t
    return ""


def _last_tool_messages(messages: list[BaseMessage], limit: int = 6) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            st = getattr(msg, "status", None)
            out.append(
                {
                    "status": st,
                    "name": getattr(msg, "name", None),
                    "content_preview": _text_content(msg)[:2000],
                }
            )
    return out[-limit:]


def _build_context(state: AgentState) -> dict[str, Any]:
    messages = list(state.get("messages") or [])
    task = _first_human_task(messages)
    code, errors, has_err = _collect_tool_code_and_errors(messages)
    return {
        "task_description": task,
        "executed_code_and_commands": code,
        "error_logs": errors,
        "has_tool_error_flag": has_err,
        "last_tool_messages": _last_tool_messages(messages),
    }


class EvoMemorySyncMiddleware(AgentMiddleware):
    """After an agent run completes, summarize the trace with an LLM and POST to EvoMemory Hub."""

    name = "evomemory_sync"

    def __init__(self, *, enabled: bool | None = None) -> None:
        super().__init__()
        self._enabled_override = enabled

    def _is_enabled(self) -> bool:
        if self._enabled_override is False:
            return False
        return _sync_enabled()

    def _finalize(self, state: AgentState, runtime: Runtime) -> None:
        _maybe_load_dotenv()
        if not self._is_enabled():
            return
        messages = list(state.get("messages") or [])
        if len(messages) < 2:
            return
        ctx = _build_context(state)
        if not ctx.get("task_description"):
            return

        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w", encoding="utf-8") as f:
                json.dump(ctx, f, ensure_ascii=False)
                tmp_path = str(Path(f.name).resolve())

            cmd = [sys.executable, "-m", "evomemory_sync.worker", tmp_path]

            popen_kwargs: dict[str, Any] = {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }

            if os.name == "nt":
                popen_kwargs["creationflags"] = (
                    subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                )
            else:
                popen_kwargs["start_new_session"] = True

            subprocess.Popen(cmd, **popen_kwargs)
        except Exception:
            logger.exception("evomemory_sync: failed to launch offline worker")

    def after_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        try:
            self._finalize(state, runtime)
        except Exception:
            logger.exception("evomemory_sync: after_agent failed")
        return None

    async def aafter_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        try:
            await asyncio.to_thread(self._finalize, state, runtime)
        except Exception:
            logger.exception("evomemory_sync: aafter_agent failed")
        return None
