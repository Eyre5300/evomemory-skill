#!/usr/bin/env python3
"""Search EvoMemory Hub for similar memories (vector similarity on server).

Usage:
    python search.py ideation "machine learning optimization"
    python search.py experiment "transformer training strategy"
    python search.py ideation "..." --top-k 20 --min-similarity 0.35

Env defaults (optional):
    EVOMEMORY_SEARCH_TOP_K, EVOMEMORY_SEARCH_MIN_SIMILARITY
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, List

try:
    import httpx
except ImportError:
    print("Error: httpx not installed. Run: pip install httpx")
    sys.exit(1)


def env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return v.strip() if isinstance(v, str) and v.strip() else default


def get_base_url() -> str:
    base = env("EVOMEMORY_API_BASE_URL")
    if not base:
        print("Error: EVOMEMORY_API_BASE_URL not set.")
        print("Run: python setup.py browse --base-url <url>")
        sys.exit(1)
    return base.rstrip("/")


def get_headers() -> dict[str, str]:
    token = env("EVOMEMORY_API_TOKEN")
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def embed_enabled() -> bool:
    return bool(env("EVOMEMORY_EMBED_BASE_URL") and env("EVOMEMORY_EMBED_API_KEY") and env("EVOMEMORY_EMBED_MODEL"))


def embed_model_id() -> str:
    return env("EVOMEMORY_EMBEDDING_MODEL_ID", env("EVOMEMORY_EMBED_MODEL"))


def embed_text(text: str) -> List[float]:
    base = env("EVOMEMORY_EMBED_BASE_URL").rstrip("/")
    key = env("EVOMEMORY_EMBED_API_KEY")
    model = env("EVOMEMORY_EMBED_MODEL")
    url = base + "/embeddings"
    payload = {"model": model, "input": text}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    timeout = float(env("EVOMEMORY_API_TIMEOUT_SECONDS", "30") or "30")
    with httpx.Client(timeout=timeout) as client:
        r = client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    vec = data["data"][0]["embedding"]
    return [float(x) for x in vec]


def default_top_k() -> int:
    raw = env("EVOMEMORY_SEARCH_TOP_K", "5")
    try:
        k = int(raw)
        return max(1, min(100, k))
    except ValueError:
        return 5


def default_min_similarity() -> float:
    raw = env("EVOMEMORY_SEARCH_MIN_SIMILARITY", "0")
    try:
        v = float(raw)
        return max(0.0, min(1.0, v))
    except ValueError:
        return 0.0


def search(kind: str, query: str, top_k: int, min_similarity: float) -> List[dict[str, Any]]:
    base = get_base_url()
    url = f"{base}/memory/{kind}/search"
    
    payload: dict[str, Any] = {
        "top_k": top_k,
        "min_similarity": min_similarity,
    }
    
    if embed_enabled():
        print(f"Generating embedding with {env('EVOMEMORY_EMBED_MODEL')}...")
        payload["query_embedding"] = embed_text(query)
        payload["embedding_model_id"] = embed_model_id()
    else:
        payload["query_text"] = query

    timeout = float(env("EVOMEMORY_API_TIMEOUT_SECONDS", "30") or "30")
    with httpx.Client(timeout=timeout) as client:
        r = client.post(url, json=payload, headers=get_headers())
        if r.status_code >= 400:
            try:
                detail = r.json()
            except Exception:
                detail = r.text
            print(f"Error: {r.status_code} {detail}")
            sys.exit(1)
        data = r.json()
        return data.get("results", [])


def format_ideation(item: dict[str, Any], idx: int) -> str:
    lines = [
        f"[{idx}] {item.get('title', '(untitled)')}",
        f"    Type: {item.get('type', item.get('memory_type', '?'))}",
        f"    Goal: {item.get('goal', '?')}",
        f"    Core Idea: {(item.get('core_idea') or '?')[:100]}...",
    ]
    sim = item.get("similarity_score") or item.get("similarity")
    if sim is not None:
        lines.append(f"    Similarity: {float(sim):.3f}")
    return "\n".join(lines)


def format_experiment(item: dict[str, Any], idx: int) -> str:
    lines = [
        f"[{idx}] {(item.get('proposal_context') or '(untitled)')[:60]}...",
        f"    Data Strategy: {(item.get('data_strategy') or '?')[:60]}...",
        f"    Model Strategy: {(item.get('model_strategy') or '?')[:60]}...",
    ]
    sim = item.get("similarity_score") or item.get("similarity")
    if sim is not None:
        lines.append(f"    Similarity: {float(sim):.3f}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Semantic search EvoMemory Hub (cosine similarity via pgvector; top results ordered by similarity)"
    )
    parser.add_argument("kind", choices=["ideation", "experiment"], help="Memory type")
    parser.add_argument("query", help="Search query text")
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        metavar="N",
        help="Return top N most similar (1–100). Default: env EVOMEMORY_SEARCH_TOP_K or 5",
    )
    parser.add_argument(
        "--min-similarity",
        type=float,
        default=None,
        metavar="S",
        help="Minimum similarity score 0.0–1.0 (filters weak matches). Default: env EVOMEMORY_SEARCH_MIN_SIMILARITY or 0",
    )
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    
    args = parser.parse_args()
    top_k = args.top_k if args.top_k is not None else default_top_k()
    top_k = max(1, min(100, top_k))
    min_sim = args.min_similarity if args.min_similarity is not None else default_min_similarity()
    min_sim = max(0.0, min(1.0, min_sim))
    
    print(f"Searching {args.kind} memories for: {args.query}")
    print(f"(top_k={top_k}, min_similarity={min_sim})")
    print()
    
    results = search(args.kind, args.query, top_k, min_sim)
    
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return
    
    if not results:
        print("No results found.")
        return
    
    print(f"Found {len(results)} results:\n")
    
    for i, item in enumerate(results, 1):
        if args.kind == "ideation":
            print(format_ideation(item, i))
        else:
            print(format_experiment(item, i))
        print()


if __name__ == "__main__":
    main()
