#!/usr/bin/env python3
"""EvoMemory Hub connection setup.

Usage:
    python setup.py wizard
    python setup.py browse --base-url https://<your-hub>
    python setup.py share --base-url https://<your-hub>
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from ipaddress import ip_address
from urllib.parse import urlparse
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import httpx
except ImportError:
    print("Error: httpx not installed. Run: pip install httpx")
    sys.exit(1)

try:
    from evomemory_sync.hub_url import build_hub_candidate_urls, normalize_hub_base_url
except Exception:
    from urllib.parse import urlunparse

    _SETUP_DEFAULT_HUB = "https://evomem.club"
    _SETUP_FALLBACK_IP = "8.130.132.246"
    _SETUP_ENABLE_FALLBACKS = False

    def normalize_hub_base_url(raw: str, *, default: str = _SETUP_DEFAULT_HUB) -> str:
        """Fallback: keep in sync with evomemory_sync.hub_url.normalize_hub_base_url."""
        base = (raw or "").strip()
        if not base:
            base = default
        if not base.startswith("http"):
            base = "https://" + base
        parsed = urlparse(base)
        host = (parsed.hostname or "").lower()
        if host in ("localhost", "127.0.0.1", "::1"):
            scheme = parsed.scheme if parsed.scheme in ("http", "https") else "http"
        else:
            scheme = "https"
        netloc = parsed.netloc
        path = parsed.path.rstrip("/")
        return urlunparse((scheme, netloc, path, "", "", "")).rstrip("/")

    def build_hub_candidate_urls(normalized_base: str) -> list[str]:
        """Fallback: keep in sync with evomemory_sync.hub_url.build_hub_candidate_urls."""
        base = (normalized_base or "").strip().rstrip("/")
        if not _SETUP_ENABLE_FALLBACKS:
            return [base] if base else []
        parsed = urlparse(normalized_base)
        host = (parsed.hostname or "").lower()
        netloc = parsed.netloc
        suffix = (parsed.path or "").rstrip("/")
        out: list[str] = []
        seen: set[str] = set()

        def add_url(scheme: str, nl: str) -> None:
            path_part = (suffix + "/") if suffix else "/"
            u = urlunparse((scheme, nl, path_part.rstrip("/") or "/", "", "", "")).rstrip("/")
            if u not in seen:
                seen.add(u)
                out.append(u)

        add_url("https", netloc)
        add_url("http", netloc)
        if _SETUP_ENABLE_FALLBACKS and host == "evomem.club":
            port = parsed.port
            ip_netloc = f"{_SETUP_FALLBACK_IP}:{port}" if port else _SETUP_FALLBACK_IP
            add_url("https", ip_netloc)
            add_url("http", ip_netloc)
        return out


def normalize_base_url(url: str) -> str:
    url = url.strip()
    if not url:
        raise ValueError("base url required")
    if not url.startswith("http"):
        url = "https://" + url
    return url.rstrip("/")


def _urlsafe_b64decode(s: str) -> str:
    # Standard library only; accept urlsafe base64 without padding.
    import base64

    s = s.strip()
    pad = "=" * ((4 - (len(s) % 4)) % 4)
    raw = base64.urlsafe_b64decode((s + pad).encode("utf-8"))
    return raw.decode("utf-8", errors="strict")


def decode_invite_code(code: str) -> str:
    """Decode a public hub invite code into a base URL.

    Format:
      evomem1:<urlsafe_base64(utf8_url)>

    Maintainer can generate:
      code = "evomem1:" + base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    """
    code = code.strip()
    prefix = "evomem1:"
    if not code.startswith(prefix):
        raise ValueError("invalid invite code prefix")
    url = _urlsafe_b64decode(code[len(prefix) :])
    return normalize_base_url(url)


def prompt_base_url() -> str:
    while True:
        raw = input("EvoMemory Hub base URL (e.g. https://evomem.club): ").strip()
        try:
            return normalize_base_url(raw)
        except Exception as e:
            print(f"Invalid URL: {e}")


def env_path(target: Optional[str]) -> Path:
    if target:
        return Path(target).expanduser().resolve()
    # Keep a single default env source at repo root.
    return (Path(__file__).resolve().parent.parent / ".env").resolve()


def _credentials_from_env_or_prompt() -> tuple[str, str]:
    """Non-interactive: EVOMEMORY_SETUP_EMAIL + EVOMEMORY_SETUP_PASSWORD; else prompt."""
    email = (os.getenv("EVOMEMORY_SETUP_EMAIL") or "").strip().lower()
    password = (os.getenv("EVOMEMORY_SETUP_PASSWORD") or "").strip()
    if email and password:
        print("(Using EVOMEMORY_SETUP_EMAIL / EVOMEMORY_SETUP_PASSWORD from environment.)")
        return email, password
    email = input("Email: ").strip().lower()
    password = getpass.getpass("Password (not echoed): ").strip()
    return email, password


def write_env_kv(path: Path, updates: Dict[str, str]) -> None:
    existing = ""
    if path.exists():
        existing = path.read_text(encoding="utf-8", errors="ignore")

    lines = existing.splitlines()
    out: list[str] = []
    seen = set()

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            out.append(line)
            continue
        k, _v = line.split("=", 1)
        key = k.strip()
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)

    for k, v in updates.items():
        if k not in seen:
            if out and out[-1].strip():
                out.append("")
            out.append(f"{k}={v}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def _is_ip_https(base_url: str) -> bool:
    try:
        parsed = urlparse(base_url)
        if parsed.scheme.lower() != "https":
            return False
        host = (parsed.hostname or "").strip()
        if not host:
            return False
        ip_address(host)
        return True
    except Exception:
        return False


def post_json(url: str, payload: dict[str, Any], timeout: float = 15.0, *, verify: bool = True) -> dict[str, Any]:
    with httpx.Client(timeout=timeout, verify=verify) as client:
        r = client.post(url, json=payload)
        if r.status_code >= 400:
            try:
                detail = r.json()
            except Exception:
                detail = r.text
            raise RuntimeError(f"{r.status_code} {detail}")
        return r.json()


def cmd_browse(args):
    """Browse-only mode (no token needed)."""
    try:
        base = normalize_base_url(args.base_url) if args.base_url else prompt_base_url()
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(2)

    path = env_path(args.env_file)
    base = normalize_hub_base_url(base)
    write_env_kv(path, {"EVOMEMORY_API_BASE_URL": base})
    print(f"[OK] Saved EVOMEMORY_API_BASE_URL to {path}")
    print("Note: Without EVOMEMORY_API_TOKEN, you can only browse (not upload).")


def cmd_share(args):
    """Share mode: register/login to get access token."""
    base = normalize_base_url(args.base_url) if args.base_url else prompt_base_url()
    canonical = normalize_hub_base_url(base)
    candidates = build_hub_candidate_urls(canonical)
    path = env_path(args.env_file)
    verify_tls = not args.insecure

    if _is_ip_https(canonical):
        print("Notice: HTTPS + IP address may fail certificate hostname validation.")
        print("If you hit CERTIFICATE_VERIFY_FAILED, retry with: --insecure")

    print(f"EvoMemory Hub (canonical): {canonical}")
    if len(candidates) > 1:
        print("Testing fallbacks: try HTTPS → HTTP → fallback IP until auth succeeds.")
    email, password = _credentials_from_env_or_prompt()

    if len(password) < 8:
        print("Error: Password too short (min 8 characters).")
        sys.exit(2)

    token: Optional[str] = None
    last_err: Optional[Exception] = None
    working: Optional[str] = None

    if args.mode == "register":
        try_order = ["register"]
    elif args.mode == "login":
        try_order = ["login"]
    else:
        try_order = ["register", "login"]

    for hub_base in candidates:
        for m in try_order:
            try:
                if m == "register":
                    print(f"Trying to register via {hub_base} …")
                    data = post_json(
                        hub_base + "/auth/register",
                        {"email": email, "password": password},
                        verify=verify_tls,
                    )
                else:
                    print(f"Trying to login via {hub_base} …")
                    data = post_json(
                        hub_base + "/auth/login",
                        {"email": email, "password": password},
                        verify=verify_tls,
                    )
                token = str(data.get("access_token") or "")
                if token:
                    working = hub_base
                    break
            except Exception as e:
                last_err = e
                token = None
        if token:
            break

    if not token:
        print(f"Error: Failed to get access_token. {last_err}")
        sys.exit(1)

    if working and working != canonical:
        print(f"Note: Authenticated via {working} (saved canonical URL: {canonical}).")

    write_env_kv(path, {
        "EVOMEMORY_API_BASE_URL": canonical,
        "EVOMEMORY_API_TOKEN": token,
    })
    print(f"[OK] Saved EVOMEMORY_API_BASE_URL and EVOMEMORY_API_TOKEN to {path}")
    print("Now EvoScientist can upload (share) memories to this hub.")


def cmd_wizard(args):
    """Interactive setup wizard (recommended for beginners)."""
    path = env_path(args.env_file)
    print("EvoMemory setup wizard")
    print("1) Browse (read-only)")
    print("2) Share (upload enabled: register/login)")
    print("3) Public Hub (invite code)  [no domain shown]")
    choice = input("Choose 1, 2, or 3: ").strip()
    if choice not in {"1", "2", "3"}:
        print("Invalid choice.")
        sys.exit(2)

    if choice == "3":
        code = input("Invite code: ").strip()
        try:
            base = decode_invite_code(code)
        except Exception as e:
            print(f"Invalid invite code: {e}")
            sys.exit(2)
    else:
        base = prompt_base_url()
    canonical = normalize_hub_base_url(base)
    candidates = build_hub_candidate_urls(canonical)
    verify_tls = not args.insecure

    if choice == "1":
        write_env_kv(path, {"EVOMEMORY_API_BASE_URL": canonical})
        print(f"[OK] Saved EVOMEMORY_API_BASE_URL to {path}")
        print("You can switch to Share later by running: python setup.py share")
        return

    # Share
    if len(candidates) > 1:
        print("Testing fallbacks: try HTTPS → HTTP → fallback IP until auth succeeds.")
    email, password = _credentials_from_env_or_prompt()

    if len(password) < 8:
        print("Error: Password too short (min 8 characters).")
        sys.exit(2)

    token: Optional[str] = None
    last_err: Optional[Exception] = None
    working: Optional[str] = None

    for hub_base in candidates:
        for m in ["register", "login"]:
            try:
                if m == "register":
                    print(f"Trying to register via {hub_base} …")
                    data = post_json(
                        hub_base + "/auth/register",
                        {"email": email, "password": password},
                        verify=verify_tls,
                    )
                else:
                    print(f"Trying to login via {hub_base} …")
                    data = post_json(
                        hub_base + "/auth/login",
                        {"email": email, "password": password},
                        verify=verify_tls,
                    )
                token = str(data.get("access_token") or "")
                if token:
                    working = hub_base
                    break
            except Exception as e:
                last_err = e
                token = None
        if token:
            break

    if not token:
        print(f"Error: Failed to get access_token. {last_err}")
        sys.exit(1)

    if working and working != canonical:
        print(f"Note: Authenticated via {working} (saved canonical URL: {canonical}).")

    write_env_kv(
        path,
        {
            "EVOMEMORY_API_BASE_URL": canonical,
            "EVOMEMORY_API_TOKEN": token,
        },
    )
    print(f"[OK] Saved EVOMEMORY_API_BASE_URL and EVOMEMORY_API_TOKEN to {path}")
    print("Now EvoScientist can upload (share) memories to this hub.")


def main():
    parser = argparse.ArgumentParser(description="EvoMemory Hub connection setup")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # browse command
    p_browse = subparsers.add_parser("browse", help="Browse-only mode")
    p_browse.add_argument("--base-url", help="EvoMemory Hub URL (optional; will prompt if omitted)")
    p_browse.add_argument("--env-file", help="Path to .env file (default: <repo>/.env)")
    p_browse.set_defaults(func=cmd_browse)

    # share command
    p_share = subparsers.add_parser("share", help="Share mode (register/login)")
    p_share.add_argument("--base-url", help="EvoMemory Hub URL (optional; will prompt if omitted)")
    p_share.add_argument("--env-file", help="Path to .env file (default: <repo>/.env)")
    p_share.add_argument("--mode", choices=["auto", "register", "login"], default="auto",
                         help="auto=try register then login")
    p_share.add_argument("--insecure", action="store_true", help="Disable TLS certificate verification (use for HTTPS+IP troubleshooting)")
    p_share.set_defaults(func=cmd_share)

    # wizard command
    p_wizard = subparsers.add_parser("wizard", help="Interactive setup wizard (recommended)")
    p_wizard.add_argument("--env-file", help="Path to .env file (default: <repo>/.env)")
    p_wizard.add_argument("--insecure", action="store_true", help="Disable TLS certificate verification during share step")
    p_wizard.set_defaults(func=cmd_wizard)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
