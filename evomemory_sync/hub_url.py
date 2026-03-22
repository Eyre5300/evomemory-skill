"""
Canonical Hub base URL for evomemory_sync clients.

Must stay aligned with what the EvoMemory Hub (vps_bundle) actually serves. The public deployment
historically exposed HTTP more reliably than HTTPS for the same host; callers therefore normalize
https:// → http:// for the default public Hub pattern (see uploader.get_base_url).
"""

from __future__ import annotations

DEFAULT_PUBLIC_HUB = "http://evomem.club"


def canonicalize_hub_base_url(raw: str, *, default: str = DEFAULT_PUBLIC_HUB) -> str:
    """
    Normalize a Hub base URL for REST calls from this skill.

    - Empty → default (public Hub).
    - No scheme → prefix https:// then apply rule below (same as setup.py normalize).
    - https:// → http:// (matches legacy uploader behavior so uploads/search use one scheme).
    """
    base = (raw or "").strip()
    if not base:
        base = default
    if not base.startswith("http"):
        base = "https://" + base
    if base.startswith("https://"):
        base = "http://" + base[len("https://") :]
    return base.rstrip("/")
