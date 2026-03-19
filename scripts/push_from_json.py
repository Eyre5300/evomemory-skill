#!/usr/bin/env python3
"""Push EvoScientist-style memory JSON files to EvoMemory Hub (same mapping as web/upload.html).

Examples:
    python push_from_json.py ../1.json ../2.json
    python push_from_json.py --base-url https://evomem.club C:/path/to/1.json

Loads .env from current working directory, then from EvoMemory repo root (parent of evomemory-skill/).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import requests
    import urllib3
except ImportError:
    print("Error: requests not installed. Run: python -m pip install requests")
    sys.exit(1)

# Temporary workaround for SSL issues while testing.
# NOTE: This disables certificate verification (verify=False) only for requests-based uploader.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

#
# Some networks / WAFs are picky about non-browser clients.
# We use a browser-like User-Agent and disable proxy auto-detection (trust_env=False)
# to make requests more reliable from typical desktop environments.
#
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


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def discover_env_files() -> None:
    load_env_file(Path.cwd() / ".env")
    # .../evomemory-skill/scripts/this.py -> repo root is parents[2] when skill lives under EvoMemory/
    here = Path(__file__).resolve()
    load_env_file(here.parents[2] / ".env")
    load_env_file(here.parents[1] / ".env")


def get_base_url(cli_base: Optional[str]) -> str:
    if cli_base:
        u = cli_base.strip()
        if not u.startswith("http"):
            u = "https://" + u
        return u.rstrip("/")
    # Default to official domain.
    base = env("EVOMEMORY_API_BASE_URL", "https://evomem.club") or "https://evomem.club"
    return base.rstrip("/")


def get_headers() -> dict[str, str]:
    token = env("EVOMEMORY_API_TOKEN")
    if not token:
        print("Error: EVOMEMORY_API_TOKEN not set. Run: python setup.py share --base-url https://evomem.club")
        sys.exit(1)
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
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
    timeout = float(env("EVOMEMORY_API_TIMEOUT_SECONDS", "120") or "120")
    r = requests.post(url, json=payload, headers=headers, timeout=timeout, verify=False)
    r.raise_for_status()
    data = r.json()
    vec = data["data"][0]["embedding"]
    return [float(x) for x in vec]


def json_to_ideation_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    mem_type = str(data.get("memory_type") or "").strip().lower()
    status = str(data.get("status") or "").strip().lower()
    if mem_type != "ideation":
        raise ValueError("not an ideation JSON")

    if status == "failed":
        proposal = str(data.get("proposal_summary") or "").strip()
        trigger = str(data.get("trigger_conditions") or data.get("trigger") or "").strip()
        do_not = str(
            data.get("do_not_repeat_notes") or data.get("do_not_repeat") or data.get("countermeasures") or ""
        ).strip()
        tags = str(data.get("retrieval_tags") or data.get("tags") or "").strip()
        first_line = (proposal.split("\n")[0] or "Failed proposal").strip()
        core_parts = [proposal]
        if trigger:
            core_parts.append("\n\nTrigger: " + trigger)
        if do_not:
            core_parts.append("\n\nDo-not-repeat: " + do_not)
        return {
            "goal": "Failed ideation",
            "type": "failed",
            "title": first_line[:200],
            "core_idea": "".join(core_parts).strip(),
            "requirements": tags or "(none)",
        }

    # promising (default)
    goal = str(data.get("goal") or "").strip()
    title = str(data.get("title") or "").strip()
    core = str(data.get("core_idea") or "").strip()
    why = str(data.get("why_promising") or "").strip()
    req = str(data.get("requirements") or "").strip()
    validation = str(data.get("validation_plan") or data.get("minimal_validation_plan") or "").strip()
    core_idea = (core + ("\n\nWhy promising: " + why if why else "")).strip()
    requirements = (req + ("\n\nValidation plan: " + validation if validation else "")).strip()
    return {
        "goal": goal or "(unknown goal)",
        "type": "promising",
        "title": title or "(untitled)",
        "core_idea": core_idea or "(empty)",
        "requirements": requirements or "(empty)",
    }


def json_to_experiment_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    mem_type = str(data.get("memory_type") or "").strip().lower()
    if mem_type != "experiment":
        raise ValueError("not an experiment JSON")
    proposal = str(
        data.get("task_description")
        or data.get("proposal_context")
        or data.get("research_task")
        or ""
    ).strip()
    data_s = str(data.get("data_summary") or data.get("data_strategy") or "").strip()
    model_s = str(data.get("model_summary") or data.get("model_strategy") or "").strip()
    env_s = str(data.get("environment_constraints") or data.get("environment") or "").strip()
    status = str(data.get("status") or "").strip()
    if status:
        env_s = (env_s + "\n\nStatus: " + status).strip()
    return {
        "proposal_context": proposal or "(untitled experiment)",
        "data_strategy": data_s or "(unknown)",
        "model_strategy": model_s or "(unknown)",
        "environment": env_s or "(none)",
    }


def post_json(url: str, payload: Dict[str, Any], headers: dict[str, str]) -> Dict[str, Any]:
    """
    Strict JSON POST:
      - Must use requests.post(url, json=payload)
      - Never use multipart/files=
    """
    timeout = float(env("EVOMEMORY_API_TIMEOUT_SECONDS", "120") or "120")
    max_retries = 2
    last_exc: Exception | None = None

    for attempt in range(max_retries):
        try:
            req_headers = dict(headers or {})
            req_headers.setdefault("User-Agent", BROWSER_UA)
            req_headers.setdefault("Accept", DEFAULT_ACCEPT)
            req_headers.setdefault("Accept-Language", DEFAULT_ACCEPT_LANGUAGE)
            req_headers.setdefault("Content-Type", "application/json")

            r = requests.post(url, json=payload, headers=req_headers, timeout=timeout, verify=False)
            if 200 <= r.status_code < 300:
                return r.json()

            # Print full response details for debugging.
            print("---- HTTP ERROR ----")
            print(f"URL: {url}")
            print(f"status_code: {r.status_code}")
            print("response.text:")
            try:
                print(r.text)
            except Exception:
                print("<no response text>")
            print("---------------------")

            # Special handling for FastAPI validation errors.
            if r.status_code == 422:
                try:
                    print("response.json:")
                    print(r.json())
                except Exception:
                    pass

            # Try to raise with json detail if available.
            try:
                detail = r.json()
            except Exception:
                detail = r.text
            raise RuntimeError(f"HTTP {r.status_code}: {detail}")
        except Exception as e:
            last_exc = e
            if attempt < max_retries - 1:
                sleep_s = 2 ** attempt
                print(
                    f"  [retry] request failed: {type(e).__name__}: {e} (sleep {sleep_s}s, attempt {attempt+2}/{max_retries})"
                )
                time.sleep(sleep_s)
                continue
            raise

    if last_exc:
        raise last_exc
    raise RuntimeError("post_json failed")


def push_one(base: str, data: Dict[str, Any], headers: dict[str, str]) -> str:
    mem_type = str(data.get("memory_type") or "").strip().lower()
    if mem_type == "ideation":
        body = json_to_ideation_payload(data)
        url = f"{base}/memory/ideation/upload"
    elif mem_type == "experiment":
        body = json_to_experiment_payload(data)
        url = f"{base}/memory/experiment/upload"
    else:
        raise ValueError(f"unknown memory_type: {data.get('memory_type')!r}")

    if embed_enabled():
        print(f"  (client embedding: {env('EVOMEMORY_EMBED_MODEL')})")
        if mem_type == "ideation":
            text = "\n".join([body["goal"], body["title"], body["core_idea"], body["requirements"]])
        else:
            text = "\n".join(
                [body["proposal_context"], body["data_strategy"], body["model_strategy"], body["environment"]]
            )
        body["embedding"] = embed_text(text)
        body["embedding_model_id"] = embed_model_id()

    result = post_json(url, body, headers)
    return str(result.get("id", "?"))


def browser_fallback_upload(files: List[Path], base_url: str, token: str) -> None:
    """
    Headless fallback upload via /upload page (Chromium network stack).
    This avoids non-browser TLS issues seen by requests/httpx on some networks.
    """
    uploader = Path(__file__).resolve().parent / "upload_from_json_browser.py"
    if not uploader.exists():
        raise RuntimeError(f"browser uploader not found: {uploader}")

    # UI typically works on https even if API was attempted via http.
    ui_base = base_url
    if ui_base.startswith("http://"):
        ui_base = ui_base.replace("http://", "https://", 1)

    cmd = [
        sys.executable,
        str(uploader),
        "--headless",
        "--base-url",
        ui_base,
        "--token",
        token,
    ]
    cmd.extend([str(p) for p in files])
    print("  [fallback] Using headless browser upload (/upload)...")
    subprocess.run(cmd, check=True)


def main() -> None:
    discover_env_files()
    parser = argparse.ArgumentParser(description="Push EvoScientist-style memory JSON to EvoMemory Hub")
    parser.add_argument("files", nargs="+", help="Path(s) to JSON file(s)")
    parser.add_argument("--base-url", default="https://evomem.club", help="Hub base URL (default: https://evomem.club)")
    parser.add_argument(
        "--no-browser-fallback",
        action="store_true",
        help="Disable headless browser fallback upload when API TLS/connection errors happen.",
    )
    args = parser.parse_args()

    browser_fallback_enabled = not bool(args.no_browser_fallback)

    base = get_base_url(args.base_url)
    # Temporary fallbacks:
    # - try http first
    # - if user passed https or http blocked, also try https with verify=False
    base_candidates: list[str] = []
    if base.startswith("http://"):
        # Prefer https first; http may be blocked by ICP compliance page.
        base_candidates = [base.replace("http://", "https://", 1), base]
    elif base.startswith("https://"):
        base_candidates = [base, base.replace("https://", "http://", 1)]
    else:
        base_candidates = [base]
    # de-dup while preserving order
    seen_bases: set[str] = set()
    base_candidates = [b for b in base_candidates if not (b in seen_bases or seen_bases.add(b))]

    token = env("EVOMEMORY_API_TOKEN")
    if not token:
        print("Error: EVOMEMORY_API_TOKEN not set. Run: python setup.py share --base-url https://evomem.club")
        sys.exit(1)
    headers = get_headers()

    for fp in args.files:
        path = Path(fp).expanduser().resolve()
        print(f"Uploading: {path.name} ...")
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"  [SKIP] invalid JSON: {e}")
            continue
        if not isinstance(data, dict):
            print("  [SKIP] root must be a JSON object")
            continue
        try:
            mid: str | None = None
            last_err: Exception | None = None
            for base_try in base_candidates:
                try:
                    mid = push_one(base_try, data, headers)
                    print(f"  [OK] id={mid} (base={base_try})")
                    last_err = None
                    break
                except requests.exceptions.SSLError as e:
                    last_err = e
                    continue
                except requests.exceptions.RequestException as e:
                    last_err = e
                    continue
                except RuntimeError as e:
                    # post_json raises RuntimeError("HTTP <code>: ...")
                    last_err = e
                    msg = str(e)
                    if "HTTP 422" in msg:
                        # Validation errors are payload issues; do not fallback silently.
                        raise
                    continue
                except Exception as e:
                    last_err = e
                    continue
            if mid is None:
                # If both 80/443 variants fail, hint user to try backend port explicitly.
                hint = ""
                try:
                    if any(b.endswith(":80") or b.startswith("http://") for b in base_candidates) and any(
                        b.startswith("https://") for b in base_candidates
                    ):
                        hint = "\nTip: both http(80) and https(443) attempts failed. If you know the backend real port (e.g. :8000), try --base-url http://evomem.club:8000"
                except Exception:
                    pass
                if last_err:
                    if browser_fallback_enabled:
                        print(f"  [fallback] API failed ({type(last_err).__name__}); switching to browser upload for {path.name} ...")
                        browser_fallback_upload([path], base_url=get_base_url(args.base_url), token=token)
                    else:
                        print(f"  [FAIL] {type(last_err).__name__}: {last_err!s}{hint}")
                else:
                    if browser_fallback_enabled:
                        print(f"  [fallback] API failed (unknown); switching to browser upload for {path.name} ...")
                        browser_fallback_upload([path], base_url=get_base_url(args.base_url), token=token)
                    else:
                        print(f"  [FAIL] unknown error{hint}")
        except Exception as e:
            # If we have a TLS/connection style error, optionally fallback.
            if browser_fallback_enabled:
                try:
                    msg = str(e)
                    if "HTTP 422" not in msg and (
                        isinstance(e, requests.exceptions.RequestException)
                        or ("SSL" in msg) or ("EOF" in msg) or ("WinError 10054" in msg) or ("HTTP 403" in msg)
                    ):
                        print(f"  [fallback] Exception {type(e).__name__}; switching to browser upload for {path.name} ...")
                        browser_fallback_upload([path], base_url=get_base_url(args.base_url), token=token)
                        continue
                except Exception:
                    pass
            print(f"  [FAIL] {type(e).__name__}: {e!s}")

    print("Done.")


if __name__ == "__main__":
    main()
