"""Auto-grade one raw experience into L1/L2/L3 abstraction levels (proposal §2.3).

Uses a local OpenAI-compatible chat model (Ollama / qwen by default) so a whole
library of experiences can be levelled in batch for free. The agent only writes a
raw experience; the system produces the three abstraction variants:

  L1 (specific)  — exact file/function/change; for near-identical tasks.
  L2 (pattern)   — problem class + where to look + pitfall; for similar tasks.
  L3 (principle) — one general strategy sentence; for cross-domain transfer.

By construction L1 carries the most concrete constraints (low G_structural, high
ContextDensity) and L3 the fewest (high G_structural) — the §2.3 ordering.
"""

from __future__ import annotations

import json
import re

import requests

from .env_loader import env as _env

_SYSTEM = """You rewrite one debugging experience at three abstraction levels.
Reply with ONLY a JSON object (no prose, no code fences) with string keys "l1","l2","l3":
- "l1" (specific): name the exact file path and function and the concrete fix. 1-2 sentences.
- "l2" (pattern): the problem category, the place to look, and the common pitfall — but NO specific file paths or function names. 1 sentence.
- "l3" (principle): ONE short general debugging-strategy sentence — NO file names, NO code, NO domain specifics.
Each level must be progressively more general: l1 most concrete, l3 most abstract."""


def _base_url() -> str:
    return _env("EVOMEMORY_CONSUMER_BASE_URL", _env("EVOMEMORY_EXTRACTOR_BASE_URL", "http://localhost:11434/v1")).rstrip("/")


def _model() -> str:
    return _env("EVOMEMORY_ABSTRACTION_MODEL", _env("EVOMEMORY_CONSUMER_MODEL", "qwen3-nothink"))


def _api_key() -> str:
    return _env("EVOMEMORY_CONSUMER_API_KEY", "ollama")


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        text = m.group(0)
    return json.loads(text)


def generate_levels(raw: str, *, seed: int | None = 0, timeout: float = 300.0) -> dict[str, str]:
    """Return {'l1','l2','l3'} for one raw experience. Falls back to the raw text on error."""
    url = _base_url() + "/chat/completions"
    payload = {
        "model": _model(),
        "messages": [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": raw.strip()}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    if seed is not None:
        payload["seed"] = seed
    try:
        r = requests.post(url, json=payload,
                          headers={"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"},
                          timeout=timeout)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        data = _parse_json(content)
        out = {k: str(data.get(k, "")).strip() for k in ("l1", "l2", "l3")}
        # never return empty levels — fall back to the raw text for any missing one
        for k in ("l1", "l2", "l3"):
            if not out[k]:
                out[k] = raw.strip()
        return out
    except Exception as e:  # robust: degrade to the raw experience at all levels
        return {"l1": raw.strip(), "l2": raw.strip(), "l3": raw.strip(), "_error": str(e)}


def batch_generate(raws: list[str], *, seed: int | None = 0) -> list[dict[str, str]]:
    """Level a whole list of raw experiences (run locally; free)."""
    return [generate_levels(r, seed=seed) for r in raws]
