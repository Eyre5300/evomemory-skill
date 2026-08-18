"""Record trustworthy Hub usage after an Agent explicitly applies an experience."""

from __future__ import annotations

import logging
from typing import Any, Literal

import requests

from .constants import BROWSER_UA, DEFAULT_ACCEPT, DEFAULT_ACCEPT_LANGUAGE
from .env_loader import env_bool as _env_bool, env as _env
from .hub_url import get_base_url
from .uploader import tls_verify

logger = logging.getLogger(__name__)


def usage_tracking_enabled() -> bool:
    raw = _env("EVOMEMORY_RECORD_DOWNLOAD_ON_USE", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def adaptation_tracking_enabled() -> bool:
    """Whether post-run outcome evidence is sent to the Hub.

    This is separate from download tracking so installations can keep the latter
    while opting out of quality telemetry. Payloads never contain raw traces.
    """
    raw = _env("EVOMEMORY_RECORD_ADAPTATION_ON_USE", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _post_record(url: str, headers: dict[str, str] | None = None) -> None:
    req_headers = {
        "User-Agent": BROWSER_UA,
        "Accept": DEFAULT_ACCEPT,
        "Accept-Language": DEFAULT_ACCEPT_LANGUAGE,
    }
    if headers:
        req_headers.update(headers)
    timeout = float(_env("EVOMEMORY_API_TIMEOUT_SECONDS", "15") or "15")
    try:
        r = requests.post(url, json={}, headers=req_headers, timeout=timeout, verify=tls_verify())
        if r.status_code >= 400:
            logger.debug("record-download %s -> HTTP %s", url, r.status_code)
    except Exception as e:
        logger.debug("record-download failed %s: %s", url, e)


def record_download_by_id(memory_id: str, headers: dict[str, str] | None = None) -> None:
    """Record one authenticated, idempotent retrieval via the generic Hub endpoint."""
    if not usage_tracking_enabled():
        return
    mid = (memory_id or "").strip()
    if not mid:
        return
    base = get_base_url()
    _post_record(f"{base}/memory/{mid}/record-download", headers=headers)


def create_application_by_id(
    memory_id: str,
    retrieval_proof: str,
    headers: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Exchange a Hub-signed search proof for one server application id.

    The same proof is idempotent on the Hub. Creating the application also
    records the account's revision-scoped retrieval, so callers must not send a
    separate record-download request.
    """
    mid = (memory_id or "").strip()
    proof = (retrieval_proof or "").strip()
    if not mid or not proof:
        return None
    req_headers = {
        "User-Agent": BROWSER_UA,
        "Accept": DEFAULT_ACCEPT,
        "Accept-Language": DEFAULT_ACCEPT_LANGUAGE,
        "Content-Type": "application/json",
    }
    if headers:
        req_headers.update(headers)
    timeout = float(_env("EVOMEMORY_API_TIMEOUT_SECONDS", "15") or "15")
    try:
        r = requests.post(
            f"{get_base_url()}/memory/{mid}/applications",
            json={"retrieval_proof": proof},
            headers=req_headers,
            timeout=timeout,
            verify=tls_verify(),
        )
        if r.status_code >= 400:
            snippet = (r.text or "")[:200]
            logger.debug("create-application %s -> HTTP %s", mid, r.status_code)
            return {"error": f"HTTP {r.status_code}", "detail": snippet}
        data = r.json()
        return data if data.get("application_id") else {"error": "missing application_id"}
    except Exception as e:
        logger.debug("create-application failed %s: %s", mid, e)
        return {"error": f"{type(e).__name__}: {e}"}


def record_adaptation_by_id(
    memory_id: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> Literal["sent", "retry", "discard"]:
    """Record a privacy-minimized outcome for a referenced Hub memory.

    ``payload`` is deliberately constructed by middleware from a task hash and
    outcome flags only. It must not be extended with prompts, trace text, or tool
    output without a separate privacy review.
    """
    if not adaptation_tracking_enabled():
        return "discard"
    mid = (memory_id or "").strip()
    if not mid:
        return "discard"
    req_headers = {
        "User-Agent": BROWSER_UA,
        "Accept": DEFAULT_ACCEPT,
        "Accept-Language": DEFAULT_ACCEPT_LANGUAGE,
        "Content-Type": "application/json",
    }
    if headers:
        req_headers.update(headers)
    timeout = float(_env("EVOMEMORY_API_TIMEOUT_SECONDS", "15") or "15")
    try:
        r = requests.post(
            f"{get_base_url()}/memory/{mid}/adaptations",
            json=payload,
            headers=req_headers,
            timeout=timeout,
            verify=tls_verify(),
        )
        if 200 <= r.status_code < 300:
            return "sent"
        logger.debug("record-adaptation %s -> HTTP %s", mid, r.status_code)
        if r.status_code in {401, 403, 408, 425, 429} or r.status_code >= 500:
            return "retry"
        return "discard"
    except Exception as e:
        logger.debug("record-adaptation failed %s: %s", mid, e)
        return "retry"


def record_downloads_for_results(
    memory_kind: str,
    results: list[dict[str, Any]],
    *,
    headers: dict[str, str] | None = None,
) -> None:
    """Deprecated compatibility shim: seeing a search result is never a retrieval.

    New code must create a server-side application from the signed Hub proof;
    that endpoint records the trusted retrieval atomically with attribution.
    """
    return None
