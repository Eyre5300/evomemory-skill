"""Multi-task faithful closed loop on the real Flask repo (M4: exp3-style).

For each task in the Flask suite: baseline (qwen alone) -> if it fails -> producer
(Claude) uploads an experience to the Hub -> the skill fetches it back -> qwen retries.
Reports the flip rate over the needs-experience set, plus cost (steps) per condition
for the exp4 (token/success) view.

Run from repo root (temp 0):
    python -m experiments.swe_multi 1
"""

from __future__ import annotations

import json
import statistics
import sys
import time

from .agent import run_consumer
from .config import RESULTS_DIR
from .hub_fetch import fetch_recipe_solution, upload_recipe
from .swe_flask import (
    CODE_SYSTEM,
    FLASK_TASKS,
    FlaskEnv,
    flask_executor,
    flask_tools_openai,
    make_flask_workdir,
)

H = "A peer agent that fixed a similar bug shared this guidance. Use it:"
MAX_STEPS = 22


def run_n(task, exp_text, seeds):
    passes, steps = 0, []
    for s in seeds:
        env = FlaskEnv(make_flask_workdir(task), task.check)
        try:
            res = run_consumer(
                task.issue, system=CODE_SYSTEM,
                extra_context=(f"{H}\n{exp_text}" if exp_text else ""), seed=s,
                tools_openai=flask_tools_openai(), execute_fn=flask_executor(env),
                max_steps=MAX_STEPS, done_check=env.tests_pass,
            )
            passes += int(env.tests_pass())
            steps.append(len(res.tool_calls))
        finally:
            env.cleanup()
    return passes, steps


def main(argv):
    n = int(argv[0]) if argv else 1
    seeds = list(range(1, n + 1))
    print(f"Multi-task Flask closed loop | tasks={[t.id for t in FLASK_TASKS]} | seeds={seeds}\n")
    records, needs, flips = [], 0, 0
    base_steps_all, retry_steps_all = [], []

    for task in FLASK_TASKS:
        base, bsteps = run_n(task, None, seeds)
        base_steps_all += bsteps
        if base > 0:
            print(f"  {task.id:26s} baseline {base}/{n} PASS  -> small model can do it; SKIP")
            records.append({"task": task.id, "baseline_pass": base, "needs_experience": False})
            continue
        needs += 1
        mid = upload_recipe(f"coderepair::{task.id}", task.issue, task.experience,
                            tags=f"coderepair,swe-bench,{task.kind}")
        fetched = fetch_recipe_solution(mid) if mid else None
        used = fetched or task.experience
        via = "Hub" if fetched else "local-fallback"
        retry, rsteps = run_n(task, used, seeds)
        retry_steps_all += rsteps
        flip = retry > base
        flips += int(flip)
        print(f"  {task.id:26s} baseline 0/{n} FAIL -> upload({mid[:8] if mid else 'none'}) "
              f"-> fetch[{via}] -> retry {retry}/{n}  FLIP={flip}")
        records.append({"task": task.id, "baseline_pass": 0, "needs_experience": True,
                        "memory_id": mid, "fetched_via": via, "retry_pass": retry,
                        "baseline_steps": bsteps, "retry_steps": rsteps, "flip": flip})

    print(f"\n==== needs-experience: {needs}/{len(FLASK_TASKS)}  |  flips: {flips}/{needs} ====")
    if base_steps_all:
        print(f"  exp4 cost view: baseline avg_steps={statistics.mean(base_steps_all):.1f}"
              + (f"  retry avg_steps={statistics.mean(retry_steps_all):.1f}" if retry_steps_all else ""))
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"swe_multi_{int(time.time())}.json"
    out.write_text(json.dumps({"seeds": seeds, "needs": needs, "flips": flips, "records": records},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
