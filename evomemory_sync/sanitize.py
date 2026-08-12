"""Hard redaction for traces before they leave the process (no LLM dependency)."""

from __future__ import annotations

import re
from typing import Any


def sanitize_text(text: str) -> str:
    s = text
    # Retrieval capabilities prove local search provenance. They are not needed
    # by the extractor, worker, or Hub and must not persist in redacted traces.
    s = re.sub(r"\[HUB_APPLY_PROOF:[a-f0-9]{64}\]", "[HUB_APPLY_PROOF:REDACTED]", s, flags=re.I)
    # (?<!\w) avoids matching `api` inside `myapi_key` while still matching `api_key=` at line start or after space.
    _kw = r"(sk|api[_-]?key|access[_-]?token|secret|password|passwd)"
    s = re.sub(
        rf"(?i)(?<![A-Za-z0-9_]){_kw}\s*[:=]\s*['\"]?[A-Za-z0-9_\-\.=+/]{{8,}}['\"]?",
        r"\1=[REDACTED]",
        s,
    )
    s = re.sub(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9]{10,}(?![A-Za-z0-9_])", "[REDACTED]", s)
    s = re.sub(
        r"(?<![A-Za-z0-9_])(ghp|github_pat|xoxb|xoxp|AKIA)[A-Za-z0-9_\-]{8,}(?![A-Za-z0-9_])",
        "[REDACTED]",
        s,
    )
    # Windows path: use possessive-like non-backtracking pattern to avoid ReDoS
    s = re.sub(r"[A-Za-z]:(?:\\[^\\\s\"\']+)+", "[REDACTED]", s)
    s = re.sub(r"/(?:Users|home|root|var|tmp|private|opt|etc)/[^\s\"\']+", "[REDACTED]", s)
    # IP address: use negative lookbehind/lookahead to avoid matching version numbers (e.g. 4.40.0, 3.11.1)
    # Only match when preceded by a non-digit/dot and followed by a non-digit/dot
    s = re.sub(
        r"(?<![.\w])(?:\d{1,3}\.){3}\d{1,3}(?![.\w])",
        "[REDACTED]",
        s,
    )
    s = re.sub(r"\b(?:[0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}\b", "[REDACTED]", s)
    s = re.sub(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b", "[REDACTED]", s)
    return s


def sanitize_context(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: sanitize_context(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_context(v) for v in value]
    if isinstance(value, str):
        return sanitize_text(value)
    return value
