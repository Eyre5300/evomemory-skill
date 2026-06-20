"""Closed-loop MVP config (Pareto proposal §2 — experience-sharing demo).

Two model roles:
- producer: Anthropic Claude (official `anthropic` SDK) — solves the task, produces experience.
- consumer: local qwen via Ollama's OpenAI-compatible endpoint — fails first, retries with experience.

Secrets come from the environment / the repo `.env` (loaded by evomemory_sync.env_loader),
never hardcoded. Set ANTHROPIC_API_KEY before running the producer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Load <repo>/.env so EVOMEMORY_* and ANTHROPIC_API_KEY are available.
try:
    from evomemory_sync.env_loader import load_env

    load_env()
except Exception:  # pragma: no cover - env_loader optional at import time
    pass


REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "experiments" / "results"


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


@dataclass(frozen=True)
class ProducerConfig:
    """Anthropic Claude — the strong model that produces experience."""

    model: str = _env("EVOMEMORY_PRODUCER_MODEL", "claude-opus-4-8")
    api_key: str = _env("ANTHROPIC_API_KEY")
    max_tokens: int = int(_env("EVOMEMORY_PRODUCER_MAX_TOKENS", "16000"))
    effort: str = _env("EVOMEMORY_PRODUCER_EFFORT", "high")  # low|medium|high|max
    max_steps: int = int(_env("EVOMEMORY_PRODUCER_MAX_STEPS", "12"))

    @property
    def ready(self) -> bool:
        return bool(self.api_key)


@dataclass(frozen=True)
class ConsumerConfig:
    """Local qwen via Ollama OpenAI-compatible endpoint — the weak model under test."""

    base_url: str = _env("EVOMEMORY_CONSUMER_BASE_URL", "http://localhost:11434/v1")
    model: str = _env("EVOMEMORY_CONSUMER_MODEL", "qwen3-nothink")
    api_key: str = _env("EVOMEMORY_CONSUMER_API_KEY", "ollama")  # Ollama ignores it
    temperature: float = float(_env("EVOMEMORY_CONSUMER_TEMPERATURE", "0.2"))
    max_steps: int = int(_env("EVOMEMORY_CONSUMER_MAX_STEPS", "12"))
    timeout: float = float(_env("EVOMEMORY_CONSUMER_TIMEOUT_SECONDS", "600"))


PRODUCER = ProducerConfig()
CONSUMER = ConsumerConfig()
