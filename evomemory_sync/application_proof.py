"""Local proofs that an EvoMemory result was actually retrieved before use."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time

from .env_loader import adaptation_fingerprint_key

_UUID_RE = re.compile(
    r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
    re.IGNORECASE,
)
_RECEIPT_TTL_SECONDS = 30 * 60
_receipts: dict[str, tuple[str, float]] = {}


def _normalized_memory_id(memory_id: str) -> str:
    value = str(memory_id or "").strip().lower()
    if not _UUID_RE.fullmatch(value):
        raise ValueError("memory_id must be a UUID returned by search_evomemory")
    return value


def issue_application_proof(memory_id: str) -> str:
    """Issue a one-time, process-local receipt for one returned search result.

    It is not sent to the Hub. The receipt expires and is consumed on use, so an
    application event is bound to a result retrieved by this running client.
    """
    value = _normalized_memory_id(memory_id)
    nonce = secrets.token_urlsafe(24)
    proof = hmac.new(
        adaptation_fingerprint_key().encode("utf-8"),
        f"evomemory-apply-v1:{value}:{nonce}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    _receipts[proof] = (value, time.monotonic() + _RECEIPT_TTL_SECONDS)
    return proof


def consume_application_proof(memory_id: str, proof: str) -> bool:
    """Accept a current receipt exactly once; reject replayed or forged proofs."""
    try:
        value = _normalized_memory_id(memory_id)
    except ValueError:
        return False
    candidate = str(proof or "").strip().lower()
    receipt = _receipts.pop(candidate, None)
    if not receipt:
        return False
    receipt_memory_id, expires_at = receipt
    return hmac.compare_digest(receipt_memory_id, value) and time.monotonic() <= expires_at
