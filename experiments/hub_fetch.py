"""Faithful skill-side experience sharing via the Hub.

The producer uploads an experience (recipe) to the Hub; the consumer's "skill"
fetches it back from the Hub before retrying — so the experience genuinely travels
through the shared store, not in-process. Fetch is scoped to our OWN uploads
(GET /memory/me/recipe) to keep the experiment controlled (no community noise).
"""

from __future__ import annotations

import os

import requests

from evomemory_sync.env_loader import load_env

load_env()


def _hub() -> tuple[str, str]:
    return ((os.getenv("EVOMEMORY_API_BASE_URL") or "").strip().rstrip("/"),
            (os.getenv("EVOMEMORY_API_TOKEN") or "").strip())


def upload_recipe(trigger: str, problem: str, solution: str, *,
                  tags: str = "experience-sharing,m4", env_snapshot: str = "(Claude producer)",
                  result: str = "produced by the big-model producer") -> str | None:
    base, tok = _hub()
    if not (base and tok):
        return None
    try:
        r = requests.post(base + "/memory/recipe/upload",
                          json={"trigger": trigger, "problem": problem, "solution": solution,
                                "env_snapshot": env_snapshot, "result": result, "tags": tags},
                          headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
                          timeout=30)
        return r.json().get("id") if r.status_code < 400 else None
    except Exception:
        return None


def fetch_recipe_solution(memory_id: str) -> str | None:
    """The skill fetching the shared experience back from the Hub by id (own uploads)."""
    base, tok = _hub()
    if not (base and tok and memory_id):
        return None
    try:
        r = requests.get(base + "/memory/me/recipe",
                         headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        if r.status_code >= 400:
            return None
        for row in r.json().get("results", []):
            if row.get("id") == memory_id:
                return row.get("solution")
    except Exception:
        return None
    return None
