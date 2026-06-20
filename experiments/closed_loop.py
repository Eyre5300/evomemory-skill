"""Closed-loop experience-sharing MVP orchestrator (Pareto proposal §2).

Per task:
  1. baseline   — consumer (qwen) solves alone.            -> expect FAIL
  2. produce    — producer (Claude) solves.                -> expect PASS
  3. distill    — producer writes transferable METHOD text (the 'experience').
  4. share      — upload the experience to the Hub (real skill path, best-effort).
  5. retry      — consumer solves again WITH the experience injected.
  6. flip       — baseline FAIL and retry PASS  => the closed loop works.

Run from repo root:
    python -m experiments.closed_loop            # all tasks
    python -m experiments.closed_loop boat_river # one task
"""

from __future__ import annotations

import json
import os
import sys
import time

import requests

from .agent import run_consumer, run_producer
from .config import PRODUCER, RESULTS_DIR
from .tasks import TASKS, Task, grade

EXP_HEADER = "A peer agent that solved a similar problem shared this method. Apply it:"


def distill_experience(task: Task, producer_answer: str) -> str:
    """One short producer call -> 2-4 sentences of transferable method advice."""
    prompt = (
        f"You solved this problem:\n{task.prompt}\n\nYour answer was: {producer_answer}\n\n"
        "Write 2-4 sentences of TRANSFERABLE method advice that would help a weaker model "
        "solve similar problems: state the setup/approach and the key pitfall to avoid. "
        "Do NOT include task-specific numbers or the answer. "
        "Output only the advice, after 'FINAL ANSWER:'."
    )
    res = run_producer(prompt)
    return res.answer or res.error


def share_experience(task: Task, experience: str, producer_answer: str) -> dict:
    """Direct recipe upload to the Hub (controlled: bypasses the curator's LLM rewrite)."""
    base = (os.getenv("EVOMEMORY_API_BASE_URL") or "").strip().rstrip("/")
    token = (os.getenv("EVOMEMORY_API_TOKEN") or "").strip()
    if not base or not token:
        return {"uploaded": False, "reason": "EVOMEMORY_API_BASE_URL / EVOMEMORY_API_TOKEN not set"}
    body = {
        "trigger": f"multi-step reasoning task: {task.id}",
        "problem": task.prompt,
        "solution": experience,
        "env_snapshot": f"Produced by {PRODUCER.model} acting as experience producer in the closed-loop MVP.",
        "result": f"producer solved it (answer={producer_answer}); shared as transferable method",
        "tags": "reasoning,experience-sharing,mvp,pareto",
    }
    try:
        r = requests.post(
            base + "/memory/recipe/upload", json=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=30,
        )
        if r.status_code >= 400:
            return {"uploaded": False, "reason": f"{r.status_code} {r.text[:200]}"}
        data = r.json()
        return {"uploaded": True, "memory_id": data.get("id") or data.get("memory_id"), "raw": data}
    except Exception as e:
        return {"uploaded": False, "reason": str(e)}


def run_task(task: Task) -> dict:
    print(f"\n=== {task.id} ===")
    baseline = run_consumer(task.prompt)
    base_ok = grade(task, baseline.answer)
    print(f"  1. baseline (qwen alone)      ok={base_ok}  answer={baseline.answer!r}")

    prod = run_producer(task.prompt)
    if prod.error:
        print(f"  2. producer ERROR: {prod.error}")
        return {"task": task.id, "baseline_ok": base_ok, "producer_error": prod.error}
    prod_ok = grade(task, prod.answer)
    print(f"  2. producer (Claude)          ok={prod_ok}  answer={prod.answer!r}")

    experience = distill_experience(task, prod.answer)
    print(f"  3. experience                 {experience!r}")

    share = share_experience(task, experience, prod.answer)
    print(f"  4. shared to Hub              {share.get('uploaded')}  {share.get('memory_id') or share.get('reason','')}")

    inject = f"{EXP_HEADER}\n{experience}"
    retried = run_consumer(task.prompt, extra_context=inject)
    retry_ok = grade(task, retried.answer)
    print(f"  5. retry (qwen + experience)  ok={retry_ok}  answer={retried.answer!r}")

    flip = (not base_ok) and retry_ok
    print(f"  6. FLIP (fail -> success)     {flip}")
    return {
        "task": task.id,
        "baseline_ok": base_ok, "producer_ok": prod_ok, "retry_ok": retry_ok,
        "flip": flip, "experience": experience,
        "answers": {"baseline": baseline.answer, "producer": prod.answer, "retry": retried.answer},
        "share": {k: share.get(k) for k in ("uploaded", "memory_id", "reason")},
    }


def run_external(task: Task, experience: str) -> dict:
    """Closed loop where the producer is external (Claude, in-session): the experience
    text is supplied directly instead of calling an API producer."""
    print(f"\n=== {task.id} (external producer) ===")
    baseline = run_consumer(task.prompt)
    base_ok = grade(task, baseline.answer)
    print(f"  1. baseline (qwen alone)      ok={base_ok}  answer={baseline.answer[-40:]!r}")
    print(f"  2-3. experience (Claude)      {experience!r}")
    share = share_experience(task, experience, "(Claude, in-session producer)")
    print(f"  4. shared to Hub              {share.get('uploaded')}  {share.get('memory_id') or share.get('reason','')}")
    retried = run_consumer(task.prompt, extra_context=f"{EXP_HEADER}\n{experience}")
    retry_ok = grade(task, retried.answer)
    print(f"  5. retry (qwen + experience)  ok={retry_ok}  answer={retried.answer[-40:]!r}")
    flip = (not base_ok) and retry_ok
    print(f"  6. FLIP (fail -> success)     {flip}")
    return {
        "task": task.id, "producer": "claude-in-session",
        "baseline_ok": base_ok, "retry_ok": retry_ok, "flip": flip, "experience": experience,
        "answers": {"baseline": baseline.answer, "retry": retried.answer},
        "share": {k: share.get(k) for k in ("uploaded", "memory_id", "reason")},
    }


def main_external(path: str) -> int:
    experiences = json.loads(open(path, encoding="utf-8").read())
    by_id = {t.id: t for t in TASKS}
    records = []
    for tid, exp in experiences.items():
        if tid not in by_id:
            print(f"  (skip unknown task {tid})")
            continue
        records.append(run_external(by_id[tid], exp))
    flips = sum(1 for r in records if r.get("flip"))
    print(f"\n==== {flips}/{len(records)} tasks showed fail->success flip ====")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"closed_loop_external_{int(time.time())}.json"
    out.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out}")
    return 0


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--external":
        return main_external(argv[1])
    if not PRODUCER.ready:
        print("ANTHROPIC_API_KEY not set — add it to the repo .env before running the producer.")
        return 2
    tasks = TASKS if not argv else [t for t in TASKS if t.id in set(argv)]
    if not tasks:
        print(f"no matching task; available: {[t.id for t in TASKS]}")
        return 2
    records = [run_task(t) for t in tasks]
    flips = sum(1 for r in records if r.get("flip"))
    print(f"\n==== {flips}/{len(records)} tasks showed fail->success flip ====")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"closed_loop_{int(time.time())}.json"
    out.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
