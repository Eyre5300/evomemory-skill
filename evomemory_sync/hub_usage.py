"""Record Hub memory usage (download counts) when skill retrieves experiences."""

from __future__ import annotations

import logging
from typing import Any

import requests

from .constants import BROWSER_UA, DEFAULT_ACCEPT, DEFAULT_ACCEPT_LANGUAGE
from .env_loader import env_bool as _env_bool, env as _env
from .hub_url import get_base_url
from .uploader import tls_verify

logger = logging.getLogger(__name__)


def usage_tracking_enabled() -> bool:
    raw = _env("EVOMEMORY_RECORD_DOWNLOAD_ON_USE", "1").strip().lower()
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
    """Increment download count via generic Hub endpoint (kind auto-detected)."""
    if not usage_tracking_enabled():
        return
    mid = (memory_id or "").strip()
    if not mid:
        return
    base = get_base_url()
    _post_record(f"{base}/memory/{mid}/record-download", headers=headers)


def record_downloads_for_results(
    memory_kind: str,
    results: list[dict[str, Any]],
    *,
    headers: dict[str, str] | None = None,
) -> None:
    """After semantic search returns memories to an agent, count each as one download/use."""
    if not usage_tracking_enabled():
        return
    kind = (memory_kind or "").strip().lower()
    if kind not in {"ideation", "experiment", "workflow", "recipe"}:
        return
    base = get_base_url()
    seen: set[str] = set()
    for item in results:
        mid = str(item.get("id") or item.get("memory_id") or "").strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        _post_record(f"{base}/memory/{kind}/{mid}/record-download", headers=headers)
