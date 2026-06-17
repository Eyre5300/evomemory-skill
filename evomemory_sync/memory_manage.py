"""Owner memory management: list, trash (hide), permanent delete."""

from __future__ import annotations

import re
from typing import Any

import requests

from .constants import BROWSER_UA, DEFAULT_ACCEPT, DEFAULT_ACCEPT_LANGUAGE
from .env_loader import env as _env
from .hub_url import get_base_url
from .uploader import tls_verify

_MEMORY_KINDS = frozenset({"ideation", "experiment", "workflow", "recipe"})
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_MAX_OWNER_SCAN = 500


def validate_memory_kind(memory_kind: str) -> str:
    kind = (memory_kind or "").strip().lower()
    if kind not in _MEMORY_KINDS:
        raise ValueError(f"invalid memory_kind {memory_kind!r}")
    return kind


def validate_memory_id(memory_id: str) -> str:
    mid = (memory_id or "").strip()
    if not _UUID_RE.match(mid):
        raise ValueError(f"invalid memory_id {memory_id!r}")
    return mid


def _timeout() -> float:
    return float(_env("EVOMEMORY_API_TIMEOUT_SECONDS", "30") or "30")


def _auth_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        "User-Agent": BROWSER_UA,
        "Accept": DEFAULT_ACCEPT,
        "Accept-Language": DEFAULT_ACCEPT_LANGUAGE,
        "Content-Type": "application/json",
        **headers,
    }


def get_own_memory_row(
    memory_kind: str,
    memory_id: str,
    *,
    headers: dict[str, str],
) -> dict[str, Any] | None:
    """Return one row from GET /memory/me/{kind} or None if not owned."""
    kind = validate_memory_kind(memory_kind)
    mid = validate_memory_id(memory_id)
    base = get_base_url()
    offset = 0
    limit = 100
    while offset < _MAX_OWNER_SCAN:
        r = requests.get(
            f"{base}/memory/me/{kind}",
            params={"limit": limit, "offset": offset},
            headers=_auth_headers(headers),
            timeout=_timeout(),
            verify=tls_verify(),
        )
        if r.status_code >= 400:
            raise RuntimeError(f"Hub list failed HTTP {r.status_code}: {r.text[:300]}")
        results = (r.json() or {}).get("results") or []
        if not results:
            break
        for row in results:
            if str(row.get("id") or "").strip() == mid:
                return row
        if len(results) < limit:
            break
        offset += limit
    return None


def list_my_memories(
    memory_kind: str,
    *,
    headers: dict[str, str],
    include_hidden: bool = True,
    limit: int = 50,
) -> list[dict[str, Any]]:
    kind = validate_memory_kind(memory_kind)
    base = get_base_url()
    lim = max(1, min(100, int(limit)))
    r = requests.get(
        f"{base}/memory/me/{kind}",
        params={"limit": lim, "offset": 0},
        headers=_auth_headers(headers),
        timeout=_timeout(),
        verify=tls_verify(),
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Hub list failed HTTP {r.status_code}: {r.text[:300]}")
    rows = list((r.json() or {}).get("results") or [])
    if include_hidden:
        return rows
    return [x for x in rows if (x.get("visibility") or "public") == "public"]


def trash_or_delete_memory(
    memory_kind: str,
    memory_id: str,
    *,
    headers: dict[str, str],
) -> dict[str, Any]:
    """First delete → hidden (trash). Second delete on hidden → permanent DELETE."""
    kind = validate_memory_kind(memory_kind)
    mid = validate_memory_id(memory_id)
    row = get_own_memory_row(kind, mid, headers=headers)
    if not row:
        return {
            "status": "error",
            "error": "memory not found or you are not the owner",
            "memory_kind": kind,
            "memory_id": mid,
        }

    visibility = str(row.get("visibility") or "public").strip().lower()
    base = get_base_url()

    if visibility == "hidden":
        r = requests.delete(
            f"{base}/memory/{kind}/{mid}",
            headers=_auth_headers(headers),
            timeout=_timeout(),
            verify=tls_verify(),
        )
        if r.status_code >= 400:
            return {
                "status": "error",
                "error": f"permanent delete failed HTTP {r.status_code}",
                "detail": r.text[:500],
            }
        return {
            "status": "success",
            "action": "permanently_deleted",
            "memory_kind": kind,
            "memory_id": mid,
            "message": "已从垃圾桶永久删除，不可恢复。",
        }

    r = requests.patch(
        f"{base}/memory/{kind}/{mid}/visibility",
        json={"visibility": "hidden"},
        headers=_auth_headers(headers),
        timeout=_timeout(),
        verify=tls_verify(),
    )
    if r.status_code >= 400:
        return {
            "status": "error",
            "error": f"move to trash failed HTTP {r.status_code}",
            "detail": r.text[:500],
        }
    return {
        "status": "success",
        "action": "moved_to_trash",
        "memory_kind": kind,
        "memory_id": mid,
        "visibility": "hidden",
        "message": "已移入垃圾桶（hidden）。再次删除同一 ID 将永久删除。",
    }


def restore_memory_from_trash(
    memory_kind: str,
    memory_id: str,
    *,
    headers: dict[str, str],
) -> dict[str, Any]:
    """Restore a hidden memory to public."""
    kind = validate_memory_kind(memory_kind)
    mid = validate_memory_id(memory_id)
    row = get_own_memory_row(kind, mid, headers=headers)
    if not row:
        return {"status": "error", "error": "memory not found or you are not the owner"}
    if str(row.get("visibility") or "public") != "hidden":
        return {
            "status": "success",
            "action": "already_public",
            "memory_kind": kind,
            "memory_id": mid,
            "message": "该记忆本来就是公开状态。",
        }
    base = get_base_url()
    r = requests.patch(
        f"{base}/memory/{kind}/{mid}/visibility",
        json={"visibility": "public"},
        headers=_auth_headers(headers),
        timeout=_timeout(),
        verify=tls_verify(),
    )
    if r.status_code >= 400:
        return {"status": "error", "error": f"restore failed HTTP {r.status_code}", "detail": r.text[:500]}
    return {
        "status": "success",
        "action": "restored",
        "memory_kind": kind,
        "memory_id": mid,
        "visibility": "public",
        "message": "已从垃圾桶恢复为公开。",
    }
