"""
Hub base URL normalization for clients (skill / CLI).

``EVOMEMORY_API_BASE_URL`` is stored as the **canonical** origin (HTTPS for public hosts;
``localhost`` / loopback may keep ``http`` for local dev — see :func:`normalize_hub_base_url`).

Production uses that URL only (no HTTP downgrade or alternate-IP probing). Optional
``ENABLE_HUB_URL_TESTING_FALLBACKS`` remains for rare self-hosted debugging but defaults off.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlparse, urlunparse

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Set True only for legacy self-hosted debugging (HTTPS→HTTP→IP probing).
# ---------------------------------------------------------------------------
ENABLE_HUB_URL_TESTING_FALLBACKS = False

DEFAULT_PUBLIC_HUB = "https://evomem.club"
TESTING_FALLBACK_IP = "8.130.132.246"


def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def normalize_hub_base_url(raw: str, *, default: str = DEFAULT_PUBLIC_HUB) -> str:
    """
    Canonical Hub base URL for storage and display: prefer HTTPS, no trailing slash.

    ``localhost`` / loopback keeps ``http`` if that was implied, for local dev.
    """
    base = (raw or "").strip()
    if not base:
        base = default
    if not base.startswith("http"):
        base = "https://" + base
    parsed = urlparse(base)
    host = (parsed.hostname or "").lower()

    if host in ("localhost", "127.0.0.1", "::1"):
        scheme = parsed.scheme if parsed.scheme in ("http", "https") else "http"
    else:
        scheme = "https"

    netloc = parsed.netloc
    path = parsed.path.rstrip("/")
    out = urlunparse((scheme, netloc, path, "", "", "")).rstrip("/")
    return out


def canonicalize_hub_base_url(raw: str, *, default: str = DEFAULT_PUBLIC_HUB) -> str:
    """Deprecated alias for :func:`normalize_hub_base_url`."""
    return normalize_hub_base_url(raw, default=default)


def _should_use_ip_fallback(hostname: str) -> bool:
    if not ENABLE_HUB_URL_TESTING_FALLBACKS:
        return False
    h = (hostname or "").lower().strip()
    if not h or h == TESTING_FALLBACK_IP.lower():
        return False
    if h == "evomem.club":
        return True
    return os.getenv("EVOMEMORY_HUB_IP_FALLBACK", "").strip() in ("1", "true", "yes")


def build_hub_candidate_urls(normalized_base: str) -> list[str]:
    """
    Ordered URLs to try for the same logical Hub (HTTPS first, then HTTP, then IP fallbacks).
    ``normalized_base`` should be the output of :func:`normalize_hub_base_url`.
    """
    base = (normalized_base or "").strip().rstrip("/")
    if not ENABLE_HUB_URL_TESTING_FALLBACKS:
        return [base] if base else []

    parsed = urlparse(normalized_base)
    host = (parsed.hostname or "").lower()
    netloc = parsed.netloc
    suffix = (parsed.path or "").rstrip("/")

    out: list[str] = []
    seen: set[str] = set()

    def add_url(scheme: str, nl: str) -> None:
        path_part = (suffix + "/") if suffix else "/"
        u = urlunparse((scheme, nl, path_part.rstrip("/") or "/", "", "", "")).rstrip("/")
        if u not in seen:
            seen.add(u)
            out.append(u)

    add_url("https", netloc)
    add_url("http", netloc)

    if _should_use_ip_fallback(host):
        ip = (os.getenv("EVOMEMORY_HUB_FALLBACK_IP") or TESTING_FALLBACK_IP).strip()
        port = parsed.port
        ip_netloc = f"{ip}:{port}" if port else ip
        add_url("https", ip_netloc)
        add_url("http", ip_netloc)

    return out


def _probe_reachable(url: str, *, timeout: float, verify: bool) -> bool:
    root = url.rstrip("/") + "/"
    try:
        r = requests.head(root, timeout=timeout, allow_redirects=True, verify=verify)
        return r.status_code < 600
    except requests.exceptions.SSLError:
        return False
    except requests.exceptions.RequestException:
        pass
    try:
        r = requests.get(root, timeout=timeout, allow_redirects=True, verify=verify)
        return r.status_code < 600
    except requests.exceptions.RequestException:
        return False


def resolve_working_hub_base_url(
    raw: str,
    *,
    default: str = DEFAULT_PUBLIC_HUB,
    verify: bool = False,
) -> str:
    """
    Return a base URL that responds to HTTP probing, or the canonical HTTPS URL if none respond.

    When testing fallbacks are disabled, returns :func:`normalize_hub_base_url` only.
    """
    normalized = normalize_hub_base_url(raw, default=default)
    if not ENABLE_HUB_URL_TESTING_FALLBACKS:
        return normalized

    timeout = _env_float("EVOMEMORY_HUB_PROBE_TIMEOUT_SECONDS", 5.0)
    candidates = build_hub_candidate_urls(normalized)
    for cand in candidates:
        if _probe_reachable(cand, timeout=timeout, verify=verify):
            if cand != normalized:
                logger.info("Hub reachable via fallback origin %s (configured %s)", cand, normalized)
            return cand

    logger.warning(
        "Hub probe failed for all candidates; using canonical URL %s (last resort)",
        normalized,
    )
    return normalized


# Process-local cache: canonical configured URL -> resolved origin
_resolved_cache: dict[str, str] = {}


def resolve_working_hub_base_url_cached(
    raw: str,
    *,
    default: str = DEFAULT_PUBLIC_HUB,
    verify: bool = False,
) -> str:
    key = normalize_hub_base_url(raw, default=default)
    if key in _resolved_cache:
        return _resolved_cache[key]
    resolved = resolve_working_hub_base_url(key, default=default, verify=verify)
    _resolved_cache[key] = resolved
    return resolved


def _env_hub(name: str, default: str = "") -> str:
    """Read env without importing ``uploader`` (avoids circular import with ``get_base_url``)."""
    v = os.getenv(name)
    return v.strip() if isinstance(v, str) and v.strip() else default


def get_base_url() -> str:
    """Resolve Hub base URL from ``EVOMEMORY_API_BASE_URL`` (same contract as legacy ``uploader.get_base_url``)."""
    base = _env_hub("EVOMEMORY_API_BASE_URL", DEFAULT_PUBLIC_HUB).strip()
    if not base:
        base = DEFAULT_PUBLIC_HUB
    return resolve_working_hub_base_url_cached(base, default=DEFAULT_PUBLIC_HUB)
