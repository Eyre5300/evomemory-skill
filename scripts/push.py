#!/usr/bin/env python3
"""Push memories to EvoMemory Hub.

Usage:
    python push.py ideation --goal "..." --title "..." --core-idea "..."
    python push.py experiment --proposal "..." --data-strategy "..." --model-strategy "..." --environment "..."
"""

from __future__ import annotations

import argparse
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
    if not token:
        print("Error: EVOMEMORY_API_TOKEN not set. Cannot upload.")
        print("Run: python setup.py share --base-url <url>")
        sys.exit(1)
    return {"Authorization": f"Bearer {token}"}


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


def push_ideation(args):
    base = get_base_url()
    url = f"{base}/memory/ideation/upload"
    
    payload: dict[str, Any] = {
        "goal": args.goal,
        "type": args.type,
        "title": args.title,
        "core_idea": args.core_idea,
        "requirements": args.requirements or "",
    }
    
    if embed_enabled():
        print(f"Generating embedding with {env('EVOMEMORY_EMBED_MODEL')}...")
        text = "\n".join([payload["goal"], payload["title"], payload["core_idea"], payload["requirements"]])
        payload["embedding"] = embed_text(text)
        payload["embedding_model_id"] = embed_model_id()
    
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
        result = r.json()
    
    print(f"[OK] Ideation memory uploaded: {result.get('id', '?')}")


def push_experiment(args):
    base = get_base_url()
    url = f"{base}/memory/experiment/upload"
    
    payload: dict[str, Any] = {
        "proposal_context": args.proposal,
        "data_strategy": args.data_strategy,
        "model_strategy": args.model_strategy,
        "environment": args.environment or "",
    }
    
    if embed_enabled():
        print(f"Generating embedding with {env('EVOMEMORY_EMBED_MODEL')}...")
        text = "\n".join([payload["proposal_context"], payload["data_strategy"], 
                          payload["model_strategy"], payload["environment"]])
        payload["embedding"] = embed_text(text)
        payload["embedding_model_id"] = embed_model_id()
    
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
        result = r.json()
    
    print(f"[OK] Experiment memory uploaded: {result.get('id', '?')}")


def main():
    parser = argparse.ArgumentParser(description="Push memories to EvoMemory Hub")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ideation command
    p_ideation = subparsers.add_parser("ideation", help="Push an ideation memory")
    p_ideation.add_argument("--goal", required=True, help="Research goal")
    p_ideation.add_argument("--title", required=True, help="Idea title")
    p_ideation.add_argument("--core-idea", required=True, help="Core idea description")
    p_ideation.add_argument("--requirements", help="Requirements/constraints")
    p_ideation.add_argument("--type", choices=["promising", "failed"], default="promising",
                            help="Memory type")
    p_ideation.set_defaults(func=push_ideation)

    # experiment command
    p_experiment = subparsers.add_parser("experiment", help="Push an experiment memory")
    p_experiment.add_argument("--proposal", required=True, help="Proposal context")
    p_experiment.add_argument("--data-strategy", required=True, help="Data strategy")
    p_experiment.add_argument("--model-strategy", required=True, help="Model strategy")
    p_experiment.add_argument("--environment", help="Environment/artifacts")
    p_experiment.set_defaults(func=push_experiment)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
