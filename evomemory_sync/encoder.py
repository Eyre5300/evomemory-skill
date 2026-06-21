"""Sentence encoder for task / experience embeddings.

Used for two things in the experiment harness:

* the similarity weight ``s_i`` in the v2 precision P(e)
  (:func:`evomemory_sync.experience_quality.p_weighted`), and
* vector recall (relevance) before P/G re-ranking.

Backend order (first available wins):

1. **sentence-transformers** with ``BAAI/bge-small-zh-v1.5`` — the canonical
   paper encoder (zh+en, runs fine on CPU; the same model is used on the GPU box).
2. **Ollama embeddings** (``/api/embeddings``) — a local fallback that needs no
   torch, for the constrained dev machine.

Embeddings are L2-normalized, so cosine == dot product. Deterministic given a
fixed model — this is a fixed-weight encoder, NOT an LLM judgement.
"""

from __future__ import annotations

import functools
import importlib.util
import os
from typing import Iterable, Sequence

import numpy as np

_MODEL_NAME = os.environ.get("EXP_ENCODER", "BAAI/bge-small-zh-v1.5")
_OLLAMA_EMBED = os.environ.get("EXP_OLLAMA_EMBED", "bge-m3")
_OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")


@functools.lru_cache(maxsize=1)
def _st_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(_MODEL_NAME)


def _embed_st(texts: Sequence[str]) -> np.ndarray:
    v = _st_model().encode(list(texts), normalize_embeddings=True, convert_to_numpy=True)
    return np.asarray(v, dtype=np.float32)


def _embed_ollama(texts: Sequence[str]) -> np.ndarray:
    import requests

    out = []
    for t in texts:
        r = requests.post(
            f"{_OLLAMA_URL}/api/embeddings",
            json={"model": _OLLAMA_EMBED, "prompt": t},
            timeout=120,
        )
        r.raise_for_status()
        out.append(r.json()["embedding"])
    v = np.asarray(out, dtype=np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True) + 1e-12
    return v


@functools.lru_cache(maxsize=1)
def _backend():
    if importlib.util.find_spec("sentence_transformers") is not None:
        return ("sentence-transformers:" + _MODEL_NAME, _embed_st)
    return ("ollama:" + _OLLAMA_EMBED, _embed_ollama)


def backend_name() -> str:
    """Which embedding backend is active (for logging / reproducibility)."""
    return _backend()[0]


def embed(texts: str | Iterable[str]) -> np.ndarray:
    """Return L2-normalized embeddings; shape (n, d). Accepts a str or iterable."""
    if isinstance(texts, str):
        texts = [texts]
    return _backend()[1](list(texts))


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / ((np.linalg.norm(a) * np.linalg.norm(b)) + 1e-12))


def similarity(text_a: str, text_b: str) -> float:
    """Cosine similarity of two texts, clamped to [0, 1] (negatives → 0)."""
    v = embed([text_a, text_b])
    return max(0.0, _cosine(v[0], v[1]))


def sim_to(query: str, candidates: Sequence[str]) -> list[float]:
    """Cosine of ``query`` against each candidate text, each clamped to [0, 1].

    One embedding call for the whole batch. Use for both the s_i weights (query =
    experience context, candidates = verification tasks) and vector recall.
    """
    if not candidates:
        return []
    v = embed([query, *candidates])
    q = v[0]
    return [max(0.0, _cosine(q, v[i + 1])) for i in range(len(candidates))]
