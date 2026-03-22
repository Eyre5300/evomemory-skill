#!/usr/bin/env python3
"""Patch parent links on EvoMemory Hub (author-only; no body re-upload).

  python patch_links.py experiment <memory_id> --parent-ideation <uuid>
  python patch_links.py experiment <memory_id> --clear-parent

  python patch_links.py workflow <memory_id> --parent-ideation <uuid> --parent-experiment <uuid>
  python patch_links.py workflow <memory_id> --clear-parents

Requires EVOMEMORY_API_BASE_URL and EVOMEMORY_API_TOKEN in environment (see scripts/.env or repo .env).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    import httpx
except ImportError:
    print("Error: pip install httpx")
    sys.exit(1)


def _load_local_env_file() -> None:
    for env_file in (
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parent / ".env",
    ):
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
    from dotenv import load_dotenv

    root_env = Path(__file__).resolve().parent.parent / ".env"
    scripts_env = Path(__file__).resolve().parent / ".env"
    if root_env.exists():
        load_dotenv(dotenv_path=str(root_env), override=False)
    if scripts_env.exists():
        load_dotenv(dotenv_path=str(scripts_env), override=False)
except Exception:
    pass


def _token() -> str:
    t = (os.getenv("EVOMEMORY_API_TOKEN") or os.getenv("EVOMEMORY_AGENT_TOKEN") or "").strip()
    if not t:
        print("Error: set EVOMEMORY_API_TOKEN")
        sys.exit(1)
    return t


def _base() -> str:
    try:
        from evomemory_sync.uploader import get_base_url

        return get_base_url()
    except Exception:
        raw = (os.getenv("EVOMEMORY_API_BASE_URL") or "https://evomem.club").strip()
        return raw.rstrip("/")


def main() -> int:
    ap = argparse.ArgumentParser(description="PATCH Hub parent links")
    ap.add_argument("--insecure", action="store_true", help="Disable TLS verify")
    sub = ap.add_subparsers(dest="kind", required=True)

    pe = sub.add_parser("experiment", help="PATCH /memory/experiment/{id}/parent")
    pe.add_argument("memory_id")
    g = pe.add_mutually_exclusive_group()
    g.add_argument("--parent-ideation", dest="parent_ideation_id", default=None, metavar="UUID")
    g.add_argument("--clear-parent", action="store_true", help="Set parent_ideation_id to null")

    pw = sub.add_parser("workflow", help="PATCH /memory/workflow/{id}/parents")
    pw.add_argument("memory_id")
    pw.add_argument("--parent-ideation", dest="parent_ideation_id", default=None, metavar="UUID")
    pw.add_argument("--parent-experiment", dest="parent_experiment_id", default=None, metavar="UUID")
    pw.add_argument(
        "--clear-parents",
        action="store_true",
        help="Set both parent ideation and parent experiment to null",
    )

    args = ap.parse_args()
    verify = not args.insecure
    headers = {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}
    base = _base()
    timeout = httpx.Timeout(60.0, connect=10.0)

    with httpx.Client(timeout=timeout, verify=verify) as client:
        if args.kind == "experiment":
            if args.clear_parent:
                pid = None
            else:
                pid = (args.parent_ideation_id or "").strip() or None
                if not pid:
                    print("Error: pass --parent-ideation UUID or --clear-parent")
                    return 2
            r = client.patch(
                f"{base}/memory/experiment/{args.memory_id}/parent",
                json={"parent_ideation_id": pid},
                headers=headers,
            )
        else:
            if args.clear_parents:
                body = {"parent_ideation_id": None, "parent_experiment_id": None}
            else:
                body = {}
                if args.parent_ideation_id:
                    body["parent_ideation_id"] = args.parent_ideation_id.strip()
                if args.parent_experiment_id:
                    body["parent_experiment_id"] = args.parent_experiment_id.strip()
                if not body:
                    print("Error: pass --parent-ideation and/or --parent-experiment, or --clear-parents")
                    return 2
            r = client.patch(
                f"{base}/memory/workflow/{args.memory_id}/parents",
                json=body,
                headers=headers,
            )
        if r.status_code >= 400:
            try:
                detail = r.json()
            except Exception:
                detail = r.text
            print(f"Error {r.status_code}: {detail}")
            return 1
        print(r.json() if r.text else {"status": "ok"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
