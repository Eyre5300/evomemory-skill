#!/usr/bin/env python3
"""Search EvoMemory Hub for similar memories (vector similarity on server).

Usage:
    python search.py ideation "machine learning optimization"
    python search.py experiment "transformer training strategy"
    python search.py ideation "..." --top-k 20 --min-similarity 0.35

Env defaults (optional):
    EVOMEMORY_API_BASE_URL (canonical default: https://evomem.club; runtime may probe HTTP / IP fallbacks)
    kind=workflow uses POST /memory/workflow/search (vector similarity, same as ideation/experiment).
    EVOMEMORY_SEARCH_TOP_K, EVOMEMORY_SEARCH_MIN_SIMILARITY
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, List

try:
    import httpx
except ImportError:
    print("Error: httpx not installed. Run: pip install httpx")
    sys.exit(1)


def _load_local_env_file() -> None:
    candidates = [
        Path(__file__).resolve().parent.parent / ".env",  # repo root (canonical)
        Path(__file__).resolve().parent / ".env",  # legacy scripts/.env
    ]
    for env_file in candidates:
        if not env_file.exists():
            continue
        try:
            for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                raw = line.strip()
                if not raw or raw.startswith("#") or "=" not in raw:
                    continue
                k, v = raw.split("=", 1)
                key = k.strip()
                val = v.strip().strip('"').strip("'")
                if key and os.getenv(key) is None:
                    os.environ[key] = val
        except Exception:
            pass


_load_local_env_file()

try:
    # Allow `python scripts/setup.py browse|share` to persist config in scripts/.env.
    from dotenv import load_dotenv

    root_env = Path(__file__).resolve().parent.parent / ".env"
    scripts_env = Path(__file__).resolve().parent / ".env"
    if root_env.exists():
        load_dotenv(dotenv_path=str(root_env), override=False)
    if scripts_env.exists():
        load_dotenv(dotenv_path=str(scripts_env), override=False)
except Exception:
    pass


def env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return v.strip() if isinstance(v, str) and v.strip() else default


def get_base_url() -> str:
    try:
        from evomemory_sync.hub_url import DEFAULT_PUBLIC_HUB, resolve_working_hub_base_url_cached

        raw = env("EVOMEMORY_API_BASE_URL", DEFAULT_PUBLIC_HUB)
        if not raw.strip():
            raw = DEFAULT_PUBLIC_HUB
        return resolve_working_hub_base_url_cached(raw, default=DEFAULT_PUBLIC_HUB)
    except Exception:
        raw = env("EVOMEMORY_API_BASE_URL", "https://evomem.club").strip() or "https://evomem.club"
        if not raw.startswith("http"):
            raw = "https://" + raw
        return raw.rstrip("/")


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
    raw = env("EVOMEMORY_SEARCH_TOP_K", "10")
    try:
        k = int(raw)
        return max(1, min(100, k))
    except ValueError:
        return 10


def default_min_similarity() -> float:
    raw = env("EVOMEMORY_SEARCH_MIN_SIMILARITY", "0")
    try:
        v = float(raw)
        return max(0.0, min(1.0, v))
    except ValueError:
        return 0.0


def search(kind: str, query: str, top_k: int, min_similarity: float, insecure: bool = False) -> List[dict[str, Any]]:
    base = get_base_url()
    timeout = float(env("EVOMEMORY_API_TIMEOUT_SECONDS", "30") or "30")

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

    with httpx.Client(timeout=timeout, verify=not insecure) as client:
        try:
            r = client.post(url, json=payload, headers=get_headers())
        except Exception as e:
            print(f"Error: request failed: {type(e).__name__}: {e}")
            if insecure:
                print("Tip: current request used --insecure; verify EVOMEMORY_API_BASE_URL is reachable.")
            else:
                print("Tip: if using HTTPS + raw IP, retry with --insecure.")
            sys.exit(1)
        if r.status_code >= 400:
            try:
                detail = r.json()
            except Exception:
                detail = r.text
            print(f"Error: {r.status_code} {detail}")
            sys.exit(1)
        data = r.json()
        return data.get("results", [])


def _preview(text: Any, max_len: int, full_text: bool) -> str:
    raw = str(text or "").strip().replace("\r", " ").replace("\n", " ")
    if full_text or len(raw) <= max_len:
        return raw
    return raw[:max_len].rstrip() + "..."


def _similarity_text(item: dict[str, Any]) -> str:
    sim = item.get("similarity_score")
    if sim is None:
        sim = item.get("similarity")
    if sim is None:
        return "?"
    try:
        return f"{float(sim):.3f}"
    except Exception:
        return str(sim)


def format_ideation(item: dict[str, Any], idx: int, full_text: bool = False) -> str:
    title = _preview(item.get("title") or "(untitled)", 180, full_text)
    ideation_type = item.get("type") or item.get("memory_type") or "?"
    goal = _preview(item.get("goal") or "?", 220, full_text)
    core = _preview(item.get("core_idea") or "?", 420, full_text)
    lines = [
        f"[{idx}] {title}",
        f"    Type: {ideation_type}",
        f"    Goal: {goal}",
        f"    Core Idea: {core}",
        f"    Similarity: {_similarity_text(item)}",
    ]
    return "\n".join(lines)


def format_experiment(item: dict[str, Any], idx: int, full_text: bool = False) -> str:
    proposal = _preview(item.get("proposal_context") or "(untitled)", 220, full_text)
    data_s = _preview(item.get("data_strategy") or "?", 260, full_text)
    model_s = _preview(item.get("model_strategy") or "?", 260, full_text)
    env_s = _preview(item.get("environment") or "?", 260, full_text)
    status = _preview(item.get("status") or "?", 40, full_text)
    pid = str(item.get("parent_ideation_id") or "").strip() or "—"
    lines = [
        f"[{idx}] {proposal}",
        f"    Status: {status}",
        f"    Parent ideation: {pid}",
        f"    Data Strategy: {data_s}",
        f"    Model Strategy: {model_s}",
        f"    Environment: {env_s}",
        f"    Similarity: {_similarity_text(item)}",
    ]
    return "\n".join(lines)


def format_workflow(item: dict[str, Any], idx: int, full_text: bool = False) -> str:
    title = _preview(item.get("title") or "(untitled)", 180, full_text)
    desc = _preview(item.get("description") or "?", 400, full_text)
    pid = str(item.get("parent_ideation_id") or "").strip() or "—"
    peid = str(item.get("parent_experiment_id") or "").strip() or "—"
    lines = [
        f"[{idx}] {title}",
        f"    parent_ideation_id: {pid}",
        f"    parent_experiment_id: {peid}",
        f"    Description: {desc}",
        f"    Match: {_similarity_text(item)}",
    ]
    return "\n".join(lines)


def _match_contains(item: dict[str, Any], keyword: str) -> bool:
    if not keyword:
        return True
    kw = keyword.lower()
    blob = json.dumps(item, ensure_ascii=False).lower()
    return kw in blob


def filter_results(
    kind: str,
    results: List[dict[str, Any]],
    ideation_type: str | None = None,
    experiment_status: str | None = None,
    contains: str | None = None,
) -> List[dict[str, Any]]:
    out: List[dict[str, Any]] = []
    for item in results:
        if contains and not _match_contains(item, contains):
            continue
        if kind == "ideation" and ideation_type:
            t = str(item.get("type") or item.get("memory_type") or "").strip().lower()
            if t != ideation_type:
                continue
        if kind == "experiment" and experiment_status:
            st = str(item.get("status") or "").strip().lower()
            if st != experiment_status:
                continue
        out.append(item)
    return out


def main():
    parser = argparse.ArgumentParser(
        description="Semantic search EvoMemory Hub (cosine similarity via pgvector; top results ordered by similarity)"
    )
    parser.add_argument(
        "kind",
        choices=["ideation", "experiment", "workflow"],
        help="Memory type (all use Hub vector search when query_text is used)",
    )
    parser.add_argument("query", help="Search query text")
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        metavar="N",
        help="Return top N most similar (1–100). Default: env EVOMEMORY_SEARCH_TOP_K or 10",
    )
    parser.add_argument(
        "--min-similarity",
        type=float,
        default=None,
        metavar="S",
        help="Minimum similarity score 0.0–1.0 (filters weak matches). Default: env EVOMEMORY_SEARCH_MIN_SIMILARITY or 0",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification (use for HTTPS+IP troubleshooting)",
    )
    parser.add_argument(
        "--ideation-type",
        choices=["promising", "failed"],
        help="Only for kind=ideation: filter by ideation type",
    )
    parser.add_argument(
        "--experiment-status",
        help="Only for kind=experiment: filter by status (e.g. completed, failed)",
    )
    parser.add_argument(
        "--contains",
        help="Filter results by keyword (matches any field in JSON)",
    )
    parser.add_argument(
        "--show-full-text",
        action="store_true",
        help="Do not truncate long text fields in output",
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
    
    results = search(args.kind, args.query, top_k, min_sim, insecure=args.insecure)
    filtered = filter_results(
        args.kind,
        results,
        ideation_type=args.ideation_type,
        experiment_status=(args.experiment_status or "").strip().lower() or None,
        contains=(args.contains or "").strip() or None,
    )
    
    if args.json:
        print(json.dumps(filtered, indent=2, ensure_ascii=False))
        return
    
    if not filtered:
        print("No results found.")
        return
    
    if len(filtered) != len(results):
        print(f"Found {len(filtered)} results (filtered from {len(results)}):\n")
    else:
        print(f"Found {len(filtered)} results:\n")
    
    for i, item in enumerate(filtered, 1):
        if args.kind == "ideation":
            print(format_ideation(item, i, full_text=args.show_full_text))
        elif args.kind == "workflow":
            print(format_workflow(item, i, full_text=args.show_full_text))
        else:
            print(format_experiment(item, i, full_text=args.show_full_text))
        print()


if __name__ == "__main__":
    main()
