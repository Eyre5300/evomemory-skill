"""B1: consumer model registry + outer-loop helpers.

Abstracts the weak model under test so the harness can sweep several consumers.
Each :class:`ConsumerSpec` is an OpenAI-compatible chat endpoint — local Ollama
now, vLLM/Ollama on the GPU box later. It shares the field names of
:class:`evomemory_sync...config.ConsumerConfig`, so :func:`agent.run_consumer`
accepts either by duck typing.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import CONSUMER


@dataclass(frozen=True)
class ConsumerSpec:
    name: str                       # registry key / display label
    base_url: str                   # OpenAI-compatible base, e.g. http://host:11434/v1
    model: str                      # served model id
    family: str = ""                # llama / qwen / mistral / gemma (for cross-family analysis)
    params_b: float = 0.0           # parameter count in billions (capability gradient)
    api_key: str = "ollama"
    temperature: float = 0.2
    max_steps: int = 12
    timeout: float = 600.0


# The default local consumer, taken from .env (CONSUMER). qwen3-nothink is a thinking
# disabled Qwen3-8B Modelfile alias already present in this machine's Ollama.
QWEN3_8B = ConsumerSpec(
    name="qwen3-8b",
    base_url=CONSUMER.base_url,
    model=CONSUMER.model,
    family="qwen",
    params_b=8.0,
    api_key=CONSUMER.api_key,
    temperature=CONSUMER.temperature,
    max_steps=CONSUMER.max_steps,
    timeout=CONSUMER.timeout,
)

# Placeholders to fill in on the tate GPU box (same-weak band + capability gradient).
# Registered lazily by register(); kept here as documentation of the planned matrix.
_PLANNED = [
    ("llama-3.1-8b", "llama", 8.0),
    ("mistral-7b", "mistral", 7.0),
    ("gemma-2-9b", "gemma", 9.0),
]

REGISTRY: dict[str, ConsumerSpec] = {QWEN3_8B.name: QWEN3_8B}


def register(spec: ConsumerSpec) -> ConsumerSpec:
    REGISTRY[spec.name] = spec
    return spec


def get(name: str) -> ConsumerSpec:
    return REGISTRY[name]


def consumers(names: list[str] | None = None) -> list[ConsumerSpec]:
    """Resolve a list of consumer specs (all registered if names is None)."""
    if names is None:
        return list(REGISTRY.values())
    return [REGISTRY[n] for n in names]
