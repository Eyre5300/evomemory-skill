"""LangChain AgentMiddleware: after each agent run, extract + upload to EvoMemory Hub."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import platform
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from .env_loader import (
    adaptation_fingerprint_key as _adaptation_fingerprint_key,
    env_bool as _env_bool,
    env as _env,
    load_env,
)
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
    # Never pass setup credentials / force-apply flags into the extractor worker.
    deny = frozenset(
        {
            "EVOMEMORY_SETUP_EMAIL",
            "EVOMEMORY_SETUP_PASSWORD",
            "EVOMEMORY_ALLOW_FORCE_APPLY",
            "EVOMEMORY_INSECURE",
            "EVOMEMORY_SYNC_SEND_RAW_CONTEXT",
        }
    )
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
        if not isinstance(v, str):
            continue
        if k in deny:
            continue
        if k in extra or k.startswith(prefixes):
            out[k] = v
    # Ensure `python -m evomemory_sync.worker` can import the package even when
    # the parent process relied on sys.path inserts rather than a site install.
    pkg_root = str(Path(__file__).resolve().parent.parent)
    existing = out.get("PYTHONPATH", "")
    parts = [p for p in existing.split(os.pathsep) if p] if existing else []
    if pkg_root not in parts:
        parts.insert(0, pkg_root)
    out["PYTHONPATH"] = os.pathsep.join(parts)
    return out


def _sync_enabled() -> bool:
    if _env_bool("EVOMEMORY_SYNC_ENABLED", True) is False:
        return False
    from .uploader import hub_bearer_token

    token = hub_bearer_token()
    if not token:
        logger.debug(
            "evomemory_sync: EVOMEMORY_API_TOKEN/EVOMEMORY_AGENT_TOKEN missing, middleware idle"
        )
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
    """Extract Hub experience IDs retrieved into the conversation."""
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


def _extract_applied_hub_applications(messages: list[BaseMessage]) -> dict[str, str]:
    """Return results explicitly applied through the local tool capability.

    Free-form ``[HUB_APPLIED:...]`` text is ignored because it can be
    hallucinated. ``apply_evomemory`` consumes a process-local receipt, so the
    middleware trusts its tool result marker rather than the model's arguments.
    """
    applications: dict[str, str] = {}
    for msg in messages:
        if not isinstance(msg, AIMessage):
            continue
        for tc in getattr(msg, "tool_calls", None) or []:
            name = str(tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "") or "")
            if name != "apply_evomemory":
                continue
            call_id = str(tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", "") or "")
            if not call_id:
                continue
            for result in messages:
                if not isinstance(result, ToolMessage) or str(getattr(result, "tool_call_id", "")) != call_id:
                    continue
                text = _text_content(result)
                match = re.search(
                    r"\[HUB_APPLIED:(?:(?:ideation|experiment|workflow|recipe):)?([a-f0-9\-]{36}):([a-f0-9\-]{36})\]",
                    text,
                    re.IGNORECASE,
                )
                if match:
                    applications[match.group(1).lower()] = match.group(2).lower()
                break
    return applications


def _extract_applied_hub_kinds(messages: list[BaseMessage]) -> dict[str, str]:
    """Return memory kind by id from trusted ``apply_evomemory`` results only."""
    kinds: dict[str, str] = {}
    pattern = re.compile(
        r"\[HUB_APPLIED:(ideation|experiment|workflow|recipe):([a-f0-9\-]{36}):[a-f0-9\-]{36}\]",
        re.IGNORECASE,
    )
    for msg in messages:
        if not isinstance(msg, AIMessage):
            continue
        for tc in getattr(msg, "tool_calls", None) or []:
            name = str(tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "") or "")
            if name != "apply_evomemory":
                continue
            call_id = str(tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", "") or "")
            if not call_id:
                continue
            for result in messages:
                if not isinstance(result, ToolMessage) or str(getattr(result, "tool_call_id", "")) != call_id:
                    continue
                match = pattern.search(_text_content(result))
                if match:
                    kinds[match.group(2).lower()] = match.group(1).lower()
                break
    return kinds


def _extract_applied_hub_references(messages: list[BaseMessage]) -> set[str]:
    """Compatibility helper returning only IDs from trusted application markers."""
    return set(_extract_applied_hub_applications(messages))


# Tools that are EvoMemory bookkeeping / archive — not orchestration steps.
_EVOMEMORY_META_TOOLS = frozenset(
    {
        "search_evomemory",
        "apply_evomemory",
        "delete_evomemory",
        "list_my_evomemory",
        "restore_evomemory",
        "share_ideation",
        "share_experiment",
        "share_recipe",
        "share_workflow",
        "share_successful_experiment",
        "share_failed_ideation",
    }
)


def _collect_tool_names(messages: list[BaseMessage]) -> list[str]:
    """Ordered unique tool names seen in AI tool_calls and ToolMessage.name."""
    names: list[str] = []
    seen: set[str] = set()
    for msg in messages:
        if isinstance(msg, AIMessage):
            for tc in getattr(msg, "tool_calls", None) or []:
                name = str(tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "") or "").strip()
                if name and name not in seen:
                    seen.add(name)
                    names.append(name)
        elif isinstance(msg, ToolMessage):
            name = str(getattr(msg, "name", "") or "").strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
    return names


def _workflow_eligible(*, run_success: bool, tool_names: list[str], tool_call_count: int) -> bool:
    """Heuristic hint for the extractor: multi-tool successful orchestration."""
    if not run_success:
        return False
    non_meta = [n for n in tool_names if n not in _EVOMEMORY_META_TOOLS]
    return len(non_meta) >= 2 and tool_call_count >= 3


def _provider_reported_token_cost(messages: list[BaseMessage]) -> int | None:
    """Sum primary-agent tokens without estimating from private message text."""
    total = 0
    observed = False
    for msg in messages:
        if not isinstance(msg, AIMessage):
            continue
        usage = getattr(msg, "usage_metadata", None)
        if not isinstance(usage, dict):
            response = getattr(msg, "response_metadata", None) or {}
            usage = response.get("token_usage") or response.get("usage") or {}
        if not isinstance(usage, dict):
            continue
        raw_total = usage.get("total_tokens")
        if raw_total is None:
            raw_total = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0) + int(
                usage.get("output_tokens") or usage.get("completion_tokens") or 0
            )
        try:
            value = max(0, int(raw_total or 0))
        except (TypeError, ValueError):
            continue
        total += value
        observed = True
    return total if observed else None


def _build_context(state: AgentState) -> dict[str, Any]:
    messages = list(state.get("messages") or [])
    task = _first_human_task(messages)
    code, errors, has_err = _collect_tool_code_and_errors(messages)
    retrieved_hub_refs = _extract_hub_references(messages)
    applied_hub_applications = _extract_applied_hub_applications(messages)
    applied_hub_kinds = _extract_applied_hub_kinds(messages)
    applied_hub_refs = set(applied_hub_applications)
    outcome = assess_run_outcome(messages, task=task)
    tool_call_count = sum(
        len(getattr(msg, "tool_calls", None) or []) for msg in messages if isinstance(msg, AIMessage)
    )
    tool_names = _collect_tool_names(messages)
    run_ok = bool(outcome["run_success_flag"])
    raw: dict[str, Any] = {
        "task_description": task,
        "executed_code_and_commands": code,
        "error_logs": errors,
        "has_tool_error_flag": outcome["has_tool_error_flag"],
        "has_code_runtime_error_flag": outcome["has_code_runtime_error_flag"],
        "validation_status": outcome["validation_status"],
        "validation_reason": outcome["validation_reason"],
        "run_success_flag": run_ok,
        "last_tool_messages": _last_tool_messages(messages),
        # This legacy worker/curator key now means "applied", not merely
        # "present in a search result". Keep retrievals separately for metrics.
        "_hub_references": sorted(applied_hub_refs) if applied_hub_refs else [],
        "_hub_applications": applied_hub_applications,
        "_hub_application_kinds": applied_hub_kinds,
        "_parent_ideation_id": next(
            (mid for mid, kind in applied_hub_kinds.items() if kind == "ideation"), None
        ),
        "_retrieved_hub_references": sorted(retrieved_hub_refs) if retrieved_hub_refs else [],
        "_tool_call_count": tool_call_count,
        "_tool_names_used": tool_names,
        "_workflow_eligible": _workflow_eligible(
            run_success=run_ok, tool_names=tool_names, tool_call_count=tool_call_count
        ),
        "_token_cost": _provider_reported_token_cost(messages),
        "_agent_metadata": {
            "model": _env("EVOMEMORY_AGENT_MODEL") or _env("EVOMEMORY_EXTRACTOR_MODEL"),
            "instance_id": _env("EVOMEMORY_AGENT_INSTANCE_ID"),
        },
    }
    # Hard redact before any temp file / worker / LLM sees the trace (do not rely on model self-sanitization).
    if _env_bool("EVOMEMORY_SYNC_SEND_RAW_CONTEXT", False):
        return raw
    return sanitize_context(raw)


def _adaptation_payload(ctx: dict[str, Any]) -> dict[str, Any]:
    """Build the exact, privacy-minimized Hub adaptation payload.

    A stable, local-keyed HMAC groups repeat attempts on the same task without
    exposing an enumerable raw task hash. Do not add trace or task text here: the
    Hub only needs an outcome signal to estimate experience quality.
    """
    task = str(ctx.get("task_description") or "").replace("\r\n", "\n").strip()
    fingerprint = hmac.new(
        _adaptation_fingerprint_key().encode("utf-8"),
        task.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    success = bool(ctx.get("run_success_flag", False))
    metadata = ctx.get("_agent_metadata") or {}
    profile = {
        "model": str(metadata.get("model") or "unknown")[:300],
        "harness": _env("EVOMEMORY_AGENT_HARNESS") or "unknown",
        "python": platform.python_version(),
        "os": platform.system().lower(),
    }
    failure_type = None
    validation_status = str(ctx.get("validation_status") or "not_applicable")
    validation_reason = str(ctx.get("validation_reason") or "")[:500]
    if not success:
        if ctx.get("has_tool_error_flag"):
            failure_type = "tool_error"
        elif ctx.get("has_code_runtime_error_flag"):
            failure_type = "runtime_error"
        elif validation_status == "failed":
            failure_type = "validation_failed"
        else:
            failure_type = "unsuccessful_run"
        # Credible failure evidence for Hub negative-transfer counting.
        if validation_status == "not_applicable":
            validation_status = "failed"
        if not validation_reason.strip():
            validation_reason = {
                "tool_error": "tool invocation failed after applying Hub memory",
                "runtime_error": "runtime or non-zero exit after applying Hub memory",
                "validation_failed": "validation or ground-truth mismatch after applying Hub memory",
                "unsuccessful_run": "run ended unsuccessfully after applying Hub memory",
            }.get(failure_type or "", "run ended unsuccessfully after applying Hub memory")
    return {
        "task_fingerprint": fingerprint,
        # Only this middleware path is reachable after a valid local
        # apply_evomemory capability was observed in the agent tool calls.
        "attribution": "explicit_application",
        "outcome": "success" if success else "failure",
        "validation_status": validation_status,
        "evidence_type": (
            "agent_self_check"
            if (not success) or validation_status in {"passed", "failed"}
            else "not_applicable"
        ),
        "validation_reason": validation_reason[:500],
        "agent_profile": profile,
        "tool_calls": max(0, int(ctx.get("_tool_call_count") or 0)),
        "token_cost": (
            max(0, int(ctx["_token_cost"]))
            if ctx.get("_token_cost") is not None
            else None
        ),
        "wall_time_ms": (
            max(0, int(ctx["_wall_time_ms"]))
            if ctx.get("_wall_time_ms") is not None
            else None
        ),
        "failure_type": failure_type,
    }


def _resolve_post_run_actions(ctx: dict[str, Any]) -> dict[str, Any]:
    """Decide record-download, adaptation, and upload after an agent run.

    Policy (success = tool OK + code OK + validation OK when applicable):
    - Applied Hub experience → record adaptation (post-apply trail). Do not upload a new card.
    - Applied ideation → may upload an Experiment linked via parent_ideation_id.
    - No apply → run extractor. Failed runs may only publish failure/inconclusive Experiment.
    Search impressions do not count as downloads; apply records retrieval on the Hub.
    """
    hub_refs = [str(x).strip() for x in (ctx.get("_hub_references") or []) if str(x).strip()]

    # Downloads are recorded by Hub when apply_evomemory exchanges a proof.
    record_download_ids: list[str] = []
    adaptation_ids = list(hub_refs)

    kinds = ctx.get("_hub_application_kinds") or {}
    applied_ideation = any(str(kinds.get(mid) or "") == "ideation" for mid in hub_refs)
    should_upload = (not hub_refs) or applied_ideation

    return {
        "hub_refs": hub_refs,
        "record_download_ids": record_download_ids,
        "adaptation_ids": adaptation_ids,
        "should_upload": should_upload,
    }


class EvoMemorySyncMiddleware(AgentMiddleware):
    """After an agent run completes, summarize the trace with an LLM and POST to EvoMemory Hub."""

    name = "evomemory_sync"

    def __init__(self, *, enabled: bool | None = None) -> None:
        super().__init__()
        self._enabled_override = enabled
        self._run_t0: float | None = None

    def _is_enabled(self) -> bool:
        if self._enabled_override is False:
            return False
        return _sync_enabled()

    def _mark_run_start(self) -> None:
        self._run_t0 = time.perf_counter()

    def _attach_wall_time(self, ctx: dict[str, Any]) -> None:
        if self._run_t0 is None:
            return
        ctx["_wall_time_ms"] = max(0, int((time.perf_counter() - self._run_t0) * 1000))

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

    def _send_adaptations(self, hub_ref_ids: list[str], ctx: dict[str, Any]) -> None:
        """Persist outcomes first, then make a best-effort delivery pass."""
        from .hub_usage import adaptation_tracking_enabled
        from .outcome_queue import enqueue_outcome, flush_pending_outcomes

        if not adaptation_tracking_enabled():
            return
        base_payload = _adaptation_payload(ctx)
        applications = ctx.get("_hub_applications") or {}
        for ref_id in hub_ref_ids:
            if not re.match(r"^[0-9a-f\-]{36}$", ref_id, re.IGNORECASE):
                logger.warning("skipping invalid hub ref_id: %s", ref_id)
                continue
            application_id = str(applications.get(ref_id) or "").strip()
            if not re.match(r"^[0-9a-f\-]{36}$", application_id, re.IGNORECASE):
                logger.warning("skipping adaptation without Hub application id: %s", ref_id)
                continue
            try:
                payload = {**base_payload, "application_id": application_id}
                if not enqueue_outcome(ref_id, payload):
                    logger.error("evomemory_sync: outcome queue full for %s", ref_id)
            except Exception as e:
                logger.warning("evomemory_sync: could not queue adaptation %s: %s", ref_id, e)
        headers = self._hub_headers_or_none()
        if headers:
            flush_pending_outcomes(headers)

    def _flush_pending_adaptations(self) -> None:
        """Retry durable outcomes even when the current run applies no memory."""
        from .hub_usage import adaptation_tracking_enabled
        from .outcome_queue import flush_pending_outcomes

        if not adaptation_tracking_enabled():
            return
        headers = self._hub_headers_or_none()
        if headers:
            flush_pending_outcomes(headers)

    def report_outcomes_on_error(self, state: AgentState) -> dict[str, Any] | None:
        """Report application-bound outcomes when the host agent aborts.

        LangGraph does not call ``after_agent`` for terminal graph errors such
        as a recursion-limit exception. Runners that preserve the latest state
        can call this method from their exception handler. It never launches an
        extractor worker or uploads a memory.
        """
        _maybe_load_dotenv()
        if not self._is_enabled():
            return None
        self._flush_pending_adaptations()
        messages = list(state.get("messages") or [])
        if len(messages) < 2:
            return None
        ctx = _build_context(state)
        self._attach_wall_time(ctx)
        if not ctx.get("task_description"):
            return None
        actions = _resolve_post_run_actions(ctx)
        if actions["adaptation_ids"]:
            self._send_adaptations(actions["adaptation_ids"], ctx)
        return ctx

    def _finalize(self, state: AgentState, runtime: Runtime) -> None:
        _maybe_load_dotenv()
        if not self._is_enabled():
            return
        try:
            self._flush_pending_adaptations()
        except Exception:
            logger.debug("evomemory_sync: pending outcome flush failed", exc_info=True)
        messages = list(state.get("messages") or [])
        if len(messages) < 2:
            return
        ctx = _build_context(state)
        self._attach_wall_time(ctx)
        if not ctx.get("task_description"):
            return

        actions = _resolve_post_run_actions(ctx)
        hub_refs = actions["hub_refs"]

        if actions["record_download_ids"]:
            try:
                self._record_hub_ref_downloads(actions["record_download_ids"])
            except Exception:
                logger.warning("evomemory_sync: record-download failed", exc_info=True)

        if actions["adaptation_ids"]:
            logger.info(
                "evomemory_sync: cited Hub refs %s → record adaptation evidence",
                actions["adaptation_ids"],
            )
            try:
                self._send_adaptations(actions["adaptation_ids"], ctx)
            except Exception:
                logger.warning("evomemory_sync: adaptation request failed", exc_info=True)

        if not actions["should_upload"]:
            return

        logger.info(
            "evomemory_sync: independent run completed (success=%s) → extract eligible memory",
            bool(ctx.get("run_success_flag")),
        )

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
                # Avoid DETACHED_PROCESS: it breaks inherited stdio handles under
                # Job Objects (Cursor/CI) and can silently kill the worker.
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                popen_kwargs["close_fds"] = False
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
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def before_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        self._mark_run_start()
        return None

    async def abefore_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        self._mark_run_start()
        return None

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
