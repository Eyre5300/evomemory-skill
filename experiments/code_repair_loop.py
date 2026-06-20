"""Faithful closed loop (user's design): only loop on tasks the small model FAILS.

Per task:
  1. baseline — local small model alone (with persistence), N seeds.
       passes>0  -> the small model can already do it; SKIP (experience not needed).
       passes==0 -> a "needs-experience" task; continue.
  2. producer — the big model (here: Claude, in-session) solves it and produces an
       experience, which is UPLOADED to the Hub (recipe).
  3. retrieve — the skill-equipped small model FETCHES that experience back from the
       Hub (own uploads), and retries the task with it, N seeds.
  4. flip — baseline failed AND retry passes  =>  the closed loop works.

Run from repo root (temp 0 recommended):
    python -m experiments.code_repair_loop 2
"""

from __future__ import annotations

import json
import sys
import time

from .agent import run_consumer
from .code_env import (
    CODE_SYSTEM,
    TASK_PROMPT,
    CodeEnv,
    code_executor,
    code_tools_openai,
    make_workdir,
)
from .code_tasks import TASKS
from .config import RESULTS_DIR
from .hub_fetch import fetch_recipe_solution, upload_recipe

H = "A peer agent that fixed a similar bug shared this guidance. Use it:"
MAX_STEPS = 18


def run_n(task, exp_text: str | None, seeds: list[int]) -> tuple[int, list[int]]:
    passes, steps = 0, []
    for s in seeds:
        env = CodeEnv(make_workdir(task.id))
        try:
            res = run_consumer(
                TASK_PROMPT, system=CODE_SYSTEM,
                extra_context=(f"{H}\n{exp_text}" if exp_text else ""), seed=s,
                tools_openai=code_tools_openai(), execute_fn=code_executor(env),
                max_steps=MAX_STEPS, done_check=env.tests_pass,  # persistence on both sides
            )
            passes += int(env.tests_pass())
            steps.append(len(res.tool_calls))
        finally:
            env.cleanup()
    return passes, steps


def main(argv: list[str]) -> int:
    n = int(argv[0]) if argv else 2
    seeds = list(range(1, n + 1))
    print(f"Faithful closed loop | tasks={[t.id for t in TASKS]} | seeds={seeds}\n")

    records = []
    needs, flips = 0, 0
    for task in TASKS:
        base_pass, base_steps = run_n(task, None, seeds)
        if base_pass > 0:
            print(f"  {task.id:9s} baseline {base_pass}/{n} PASS  -> small model can do it; SKIP")
            records.append({"task": task.id, "baseline_pass": base_pass, "needs_experience": False})
            continue
        needs += 1
        # producer (Claude) -> upload experience to the Hub
        mid = upload_recipe(f"coderepair::{task.id}", TASK_PROMPT, task.good, tags=f"coderepair,{task.kind}")
        fetched = fetch_recipe_solution(mid) if mid else None
        used = fetched or task.good
        via = "Hub" if fetched else "local-fallback"
        retry_pass, retry_steps = run_n(task, used, seeds)
        flip = retry_pass > 0
        flips += int(flip)
        print(f"  {task.id:9s} baseline 0/{n} FAIL  -> upload({mid[:8] if mid else 'none'}) "
              f"-> skill fetch[{via}] -> retry {retry_pass}/{n} PASS  FLIP={flip}")
        records.append({"task": task.id, "baseline_pass": 0, "needs_experience": True,
                        "memory_id": mid, "fetched_via": via, "retry_pass": retry_pass,
                        "flip": flip, "base_steps": base_steps, "retry_steps": retry_steps})

    print(f"\n==== needs-experience tasks: {needs}/{len(TASKS)}  |  flips: {flips}/{needs} ====")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"code_repair_loop_{int(time.time())}.json"
    out.write_text(json.dumps({"seeds": seeds, "needs": needs, "flips": flips, "records": records},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
