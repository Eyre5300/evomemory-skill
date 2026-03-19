#!/usr/bin/env python3
"""
Browser-based uploader (Playwright) for EvoMemory Hub.

Why:
On some networks, non-browser TLS/HTTP clients may get "connection reset".
This script uses Chromium (same kind of network stack as a browser) to reliably
upload JSON memories via /web UI.

Usage:
  python upload_from_json_browser.py --base-url https://evomem.club --token YOUR_ACCESS_TOKEN 1.json 2.json 3.json 4.json

Notes:
  - This script assumes the /upload page auto-fills fields from the dropped JSON.
  - It injects `localStorage.evومemory_access_token` before page scripts run.
"""

from __future__ import annotations

import argparse
import json as json_mod
from pathlib import Path
from typing import Any, List, Optional


def _escape_js_string(s: str) -> str:
    # Use JSON encoding to safely escape for JS string literal.
    return json_mod.dumps(s)


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload EvoScientist JSON using browser automation")
    parser.add_argument("--base-url", default="https://evomem.club", help="Hub base URL")
    parser.add_argument("--token", required=True, help="access_token (JWT)")
    parser.add_argument("files", nargs="+", help="Path(s) to json files")
    # Avoid showing a real browser window during uploads by default.
    # Kept for backwards compatibility: if caller passes --headless we still run headless.
    parser.add_argument("--headed", action="store_true", help="Run with visible browser window (debug only)")
    parser.add_argument("--headless", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:
        raise SystemExit(
            "playwright not installed. Run:\n"
            "  python -m pip install playwright\n"
            "  python -m playwright install chromium\n"
        )

    base_url = args.base_url.rstrip("/")
    upload_url = base_url + "/upload"
    token = args.token

    headless = not bool(args.headed)

    files: List[Path] = [Path(f).expanduser().resolve() for f in args.files]
    for p in files:
        if not p.is_file():
            raise SystemExit(f"File not found: {p}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=headless,
            # Extra flags for more stable headless startup.
            args=["--disable-gpu", "--disable-dev-shm-usage", "--no-sandbox"],
        )
        context = browser.new_context()
        page = context.new_page()

        page.goto(upload_url, wait_until="domcontentloaded")
        # Login gating on upload.html checks localStorage during script execution.
        # In headless runs, add_init_script may run on about:blank (wrong origin),
        # so token might not land on the real site. Force-set after navigation and reload.
        page.evaluate(
            """(t) => {
                localStorage.setItem('evomemory_access_token', String(t));
              }""",
            token,
        )
        page.reload(wait_until="domcontentloaded")
        # Ensure we are in logged-in upload page.
        page.wait_for_selector("#uploadForm", state="visible", timeout=60000)

        for idx, fp in enumerate(files, start=1):
            print(f"[{idx}/{len(files)}] Uploading: {fp.name}")

            # Fill JSON file.
            page.set_input_files("#jsonFile", str(fp))

            # Wait until JSON auto-fill finished (UI hint becomes visible).
            page.wait_for_function(
                """() => {
                  const h = document.getElementById('dropzoneHint');
                  return !!h && !h.classList.contains('hidden');
                }""",
                timeout=60000,
            )

            # Wait until submit button is visible and not disabled.
            page.wait_for_function(
                """() => {
                  const b = document.getElementById('submitBtn');
                  if (!b) return false;
                  const visible = b.offsetParent !== null;
                  return visible && b.disabled === false;
                }""",
                timeout=60000,
            )

            # Click submit.
            page.click("#submitBtn")

            # Wait until form status changes from "..." to something else.
            # The page uses #formStatus text.
            page.wait_for_function(
                """() => {
                    const el = document.getElementById('formStatus');
                    if (!el) return false;
                    const t = (el.textContent || '').trim();
                    return t !== '' && t !== '...' && !t.toLowerCase().includes('failed') && !t.toLowerCase().includes('error');
                }""",
                timeout=90000,
            )

            status_text = page.locator("#formStatus").inner_text(timeout=10000).strip()
            print(f"    status: {status_text}")

        browser.close()
        print("Done.")


if __name__ == "__main__":
    main()

