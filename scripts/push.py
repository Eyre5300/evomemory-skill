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
import time
from typing import Any, List

try:
    import requests
    import urllib3
except ImportError:
    print("Error: requests not installed. Run: python -m pip install requests")
    sys.exit(1)

# Temporary workaround for SSL issues while testing.
# NOTE: Disables certificate verification (verify=False) for requests-based uploader.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Try to mimic browser-like requests for networks/WAFs that are sensitive to non-browser clients.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
DEFAULT_ACCEPT = "application/json"
DEFAULT_ACCEPT_LANGUAGE = "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7"

def env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return v.strip() if isinstance(v, str) and v.strip() else default


def get_base_url() -> str:
    base = env("EVOMEMORY_API_BASE_URL", "https://evomem.club")
    return base.rstrip("/")


def get_headers() -> dict[str, str]:
    token = env("EVOMEMORY_API_TOKEN")
    if not token:
        print("Error: EVOMEMORY_API_TOKEN not set. Cannot upload.")
        print("Run: python setup.py share --base-url <url>")
        sys.exit(1)
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": BROWSER_UA,
        "Accept": DEFAULT_ACCEPT,
        "Accept-Language": DEFAULT_ACCEPT_LANGUAGE,
    }


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
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": BROWSER_UA,
        "Accept": DEFAULT_ACCEPT,
        "Accept-Language": DEFAULT_ACCEPT_LANGUAGE,
    }
    timeout = float(env("EVOMEMORY_API_TIMEOUT_SECONDS", "30") or "30")
    r = requests.post(url, json=payload, headers=headers, timeout=timeout, verify=False)
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
    max_retries = 2
    for attempt in range(max_retries):
        try:
            r = requests.post(url, json=payload, headers=get_headers(), timeout=timeout, verify=False)
            if 200 <= r.status_code < 300:
                result = r.json()
                print(f"[OK] Ideation memory uploaded: {result.get('id', '?')}")
                return

            print("---- HTTP ERROR ----")
            print(f"URL: {url}")
            print(f"status_code: {r.status_code}")
            print("response.text:")
            print(r.text)
            print("---------------------")

            if r.status_code == 422:
                try:
                    print("response.json:")
                    print(r.json())
                except Exception:
                    pass
            try:
                detail = r.json()
            except Exception:
                detail = r.text
            raise RuntimeError(f"HTTP {r.status_code}: {detail}")
        except Exception as e:
            if attempt < max_retries - 1:
                sleep_s = 2 ** attempt
                print(f"  [retry] request failed: {type(e).__name__}: {e} (sleep {sleep_s}s, attempt {attempt+2}/{max_retries})")
                time.sleep(sleep_s)
                continue
            raise


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
    max_retries = 2
    for attempt in range(max_retries):
        try:
            r = requests.post(url, json=payload, headers=get_headers(), timeout=timeout, verify=False)
            if 200 <= r.status_code < 300:
                result = r.json()
                print(f"[OK] Experiment memory uploaded: {result.get('id', '?')}")
                return

            print("---- HTTP ERROR ----")
            print(f"URL: {url}")
            print(f"status_code: {r.status_code}")
            print("response.text:")
            print(r.text)
            print("---------------------")

            if r.status_code == 422:
                try:
                    print("response.json:")
                    print(r.json())
                except Exception:
                    pass
            try:
                detail = r.json()
            except Exception:
                detail = r.text
            raise RuntimeError(f"HTTP {r.status_code}: {detail}")
        except Exception as e:
            if attempt < max_retries - 1:
                sleep_s = 2 ** attempt
                print(f"  [retry] request failed: {type(e).__name__}: {e} (sleep {sleep_s}s, attempt {attempt+2}/{max_retries})")
                time.sleep(sleep_s)
                continue
            raise


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
