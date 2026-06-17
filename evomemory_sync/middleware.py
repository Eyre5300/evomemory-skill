"""LangChain AgentMiddleware: after each agent run, extract + upload to EvoMemory Hub."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from .env_loader import env_bool as _env_bool, env as _env, load_env
from .run_outcome import assess_run_outcome
from .sanitize import sanitize_context

logger = logging.getLogger(__name__)


def _maybe_load_dotenv() -> None:
    """Lazy-load .env via env_loader (which handles its own idempotency)."""
    try:
        load_env()
    except Exception:
        pass


def _worker_subprocess_env() -> dict[str, str]:
    """Subset of parent env for the offline worker (avoid leaking unrelated host secrets)."""
    prefixes = ("EVOMEMORY_", "LC_")
    extra = frozenset(
        {
            "LANG",
            "PATH",
            "PATHEXT",
            "SYSTEMROOT",
            "WINDIR",
            "HOME",
            "USERPROFILE",
            "HOMEDRIVE",
            "HOMEPATH",
            "TMP",
            "TEMP",
            "TMPDIR",
            "PYTHONPATH",
            "PYTHONHOME",
            "PYTHONNOUSERSITE",
            "PYTHONUTF8",
            "PYTHONIOENCODING",
            "VIRTUAL_ENV",
            "SILICONFLOW_API_KEY",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
            "ALL_PROXY",
        }
    )
    out: dict[str, str] = {}
    for k, v in os.environ.items():
        if isinstance(v, str) and (k in extra or k.startswith(prefixes)):
            out[k] = v
    return out


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


def _extract_hub_references(messages: list[BaseMessage]) -> set[str]:
    """Extract Hub experience IDs cited in the conversation via [HUB_REF:uuid] markers."""
    refs: set[str] = set()
    pattern = re.compile(r"\[HUB_REF:([a-f0-9\-]+)\]", re.IGNORECASE)
    for msg in messages:
        text = _text_content(msg)
        for match in pattern.finditer(text):
            refs.add(match.group(1))
        # Also check tool call arguments for search results
        if isinstance(msg, AIMessage):
            calls = getattr(msg, "tool_calls", None) or []
            for tc in calls:
                args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
                if isinstance(args, dict):
                    for v in args.values():
                        if isinstance(v, str):
                            for m in pattern.finditer(v):
                                refs.add(m.group(1))
    return refs


def _build_context(state: AgentState) -> dict[str, Any]:
    messages = list(state.get("messages") or [])
    task = _first_human_task(messages)
    code, errors, has_err = _collect_tool_code_and_errors(messages)
    hub_refs = _extract_hub_references(messages)
    outcome = assess_run_outcome(messages, task=task)
    raw: dict[str, Any] = {
        "task_description": task,
        "executed_code_and_commands": code,
        "error_logs": errors,
        "has_tool_error_flag": outcome["has_tool_error_flag"],
        "has_code_runtime_error_flag": outcome["has_code_runtime_error_flag"],
        "validation_status": outcome["validation_status"],
        "validation_reason": outcome["validation_reason"],
        "run_success_flag": outcome["run_success_flag"],
        "last_tool_messages": _last_tool_messages(messages),
        "_hub_references": list(hub_refs) if hub_refs else [],
        "_agent_metadata": {
            "model": _env("EVOMEMORY_AGENT_MODEL") or _env("EVOMEMORY_EXTRACTOR_MODEL"),
            "instance_id": _env("EVOMEMORY_AGENT_INSTANCE_ID"),
        },
    }
    # Hard redact before any temp file / worker / LLM sees the trace (do not rely on model self-sanitization).
    if _env_bool("EVOMEMORY_SYNC_SEND_RAW_CONTEXT", False):
        return raw
    return sanitize_context(raw)


def _resolve_post_run_actions(ctx: dict[str, Any]) -> dict[str, Any]:
    """Decide record-download, verify, and upload after an agent run.

    Policy (success = tool OK + code OK + validation OK when applicable):
    - Cited Hub experience → always record-download (success or failure).
    - Cited + success → verify only, no upload.
    - Cited + failure → record-download, no verify, upload correction (curator may update own card).
    - No citation + success → upload (must pass duplicate check upstream).
    - No citation + failure → no upload.
    """
    hub_refs = [str(x).strip() for x in (ctx.get("_hub_references") or []) if str(x).strip()]
    run_success = bool(ctx.get("run_success_flag", False))

    record_download_ids = list(hub_refs)
    verify_ids = list(hub_refs) if hub_refs and run_success else []

    should_upload = False
    if hub_refs and not run_success:
        should_upload = True
        ctx["_correcting_after_hub_failure"] = True
    elif not hub_refs and run_success:
        should_upload = True

    return {
        "hub_refs": hub_refs,
        "record_download_ids": record_download_ids,
        "verify_ids": verify_ids,
        "should_upload": should_upload,
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

    def _hub_headers_or_none(self) -> dict[str, str] | None:
        from .uploader import hub_headers

        try:
            return hub_headers()
        except RuntimeError:
            logger.debug("evomemory_sync: no token, skip hub post-run actions")
            return None

    def _record_hub_ref_downloads(self, hub_ref_ids: list[str]) -> None:
        """Count Hub experience use whenever the agent cited it (success or failure)."""
        from .hub_usage import record_download_by_id

        headers = self._hub_headers_or_none()
        if not headers:
            return
        for ref_id in hub_ref_ids:
            if not re.match(r"^[0-9a-f\-]{36}$", ref_id, re.IGNORECASE):
                logger.warning("skipping invalid hub ref_id: %s", ref_id)
                continue
            try:
                record_download_by_id(ref_id, headers=headers)
            except Exception as e:
                logger.debug("evomemory_sync: record-download %s failed: %s", ref_id, e)

    def _send_verify(self, hub_ref_ids: list[str]) -> None:
        """POST verification after a successful run that used cited Hub experience."""
        import requests
        from .hub_url import get_base_url
        from .uploader import tls_verify

        headers = self._hub_headers_or_none()
        if not headers:
            return
        base = get_base_url()
        timeout = float(os.getenv("EVOMEMORY_API_TIMEOUT_SECONDS", "30") or "30")
        for ref_id in hub_ref_ids:
            if not re.match(r"^[0-9a-f\-]{36}$", ref_id, re.IGNORECASE):
                logger.warning("skipping invalid hub ref_id: %s", ref_id)
                continue
            try:
                r = requests.post(
                    f"{base}/memory/{ref_id}/verify",
                    json={},
                    headers=headers,
                    timeout=timeout,
                    verify=tls_verify(),
                )
                if r.status_code < 300:
                    logger.info("evomemory_sync: verified %s", ref_id)
                else:
                    logger.debug("evomemory_sync: verify %s returned %s", ref_id, r.status_code)
            except Exception as e:
                logger.debug("evomemory_sync: verify %s failed: %s", ref_id, e)

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

        actions = _resolve_post_run_actions(ctx)
        hub_refs = actions["hub_refs"]

        if actions["record_download_ids"]:
            try:
                self._record_hub_ref_downloads(actions["record_download_ids"])
            except Exception:
                logger.warning("evomemory_sync: record-download failed", exc_info=True)

        if actions["verify_ids"]:
            logger.info(
                "evomemory_sync: task succeeded using Hub refs %s → verify (no upload)",
                actions["verify_ids"],
            )
            try:
                self._send_verify(actions["verify_ids"])
            except Exception:
                logger.warning("evomemory_sync: verify request failed", exc_info=True)

        if not actions["should_upload"]:
            if not hub_refs and not ctx.get("run_success_flag"):
                logger.info(
                    "evomemory_sync: run not successful without Hub refs → skip upload (%s)",
                    ctx.get("validation_reason") or "tool/code/validation failure",
                )
            return

        if hub_refs:
            ctx.setdefault("_hub_references", hub_refs)
            logger.info(
                "evomemory_sync: task failed despite Hub refs %s → upload correction (duplicate check)",
                hub_refs,
            )
        else:
            logger.info("evomemory_sync: run succeeded without Hub refs → upload (duplicate check)")

        tmp_path: str | None = None
        try:
            # Restrict temp file to owner-only (600) to prevent other users from
            # reading potentially unsanitized context when SYNC_SEND_RAW_CONTEXT=true.
            fd, tmp_path = tempfile.mkstemp(suffix=".json", text=False)
            os.chmod(tmp_path, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(ctx, f, ensure_ascii=False)
            tmp_path = str(Path(tmp_path).resolve())

            cmd = [sys.executable, "-m", "evomemory_sync.worker", tmp_path]

            def _worker_log_path() -> Path:
                custom = os.getenv("EVOMEMORY_WORKER_LOG_FILE", "").strip()
                if custom:
                    return Path(custom).expanduser()
                return Path.home() / ".evomemory" / "worker.log"

            log_path = _worker_log_path()
            log_fd: int | None = None
            stdout_arg: Any = subprocess.DEVNULL
            stderr_arg: Any = subprocess.DEVNULL
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_fd = os.open(str(log_path), os.O_APPEND | os.O_CREAT | os.O_WRONLY)
                stdout_arg = log_fd
                stderr_arg = log_fd
            except OSError as e:
                logger.warning("evomemory_sync: worker log %s unavailable (%s); child stdio discarded", log_path, e)

            popen_kwargs: dict[str, Any] = {
                "stdin": subprocess.DEVNULL,
                "stdout": stdout_arg,
                "stderr": stderr_arg,
                "env": _worker_subprocess_env(),
            }

            if os.name == "nt":
                popen_kwargs["creationflags"] = (
                    subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                )
            else:
                popen_kwargs["start_new_session"] = True

            logger.info("evomemory_sync: launching offline worker tmp=%s worker_log=%s", tmp_path, str(log_path))
            subprocess.Popen(cmd, **popen_kwargs)
            if log_fd is not None:
                try:
                    os.close(log_fd)
                except OSError:
                    pass
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
