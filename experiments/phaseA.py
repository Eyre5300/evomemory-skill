"""M4 Phase A: multi-task experiments, fully local (free).

Runs the closed loop across several mini code-repair tasks under three conditions
— no experience / good (pruning) experience / misleading experience — over fixed
seeds, then reports:

  exp3 (quality filtering): success rate & avg cost(steps) per condition, showing
       the good experience lifts success across diverse tasks while a misleading
       one does not (proposal exp3).
  exp4 data (cost vs success): the per-condition (avg_steps, success) points — the
       token/success trade-off the Pareto frontier is built from (plotted in M5).

Run from repo root (temp 0 recommended):
    python -m experiments.phaseA 2          # 2 seeds
"""

from __future__ import annotations

import json
import statistics
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

H = "A peer agent that fixed a similar bug shared this guidance. Use it:"
MAX_STEPS = 16
CONDITIONS = ["none", "good", "misleading"]


def run_one(task, exp_text: str | None, seed: int) -> tuple[bool, int]:
    env = CodeEnv(make_workdir(task.id))
    try:
        res = run_consumer(
            TASK_PROMPT, system=CODE_SYSTEM,
            extra_context=(f"{H}\n{exp_text}" if exp_text else ""), seed=seed,
            tools_openai=code_tools_openai(), execute_fn=code_executor(env), max_steps=MAX_STEPS,
        )
        return env.tests_pass(), len(res.tool_calls)
    finally:
        env.cleanup()


def main(argv: list[str]) -> int:
    seeds = list(range(1, (int(argv[0]) if argv else 2) + 1))
    print(f"Phase A | tasks={[t.id for t in TASKS]} | conditions={CONDITIONS} | seeds={seeds}\n")
    grid = []
    for task in TASKS:
        exps = {"none": None, "good": task.good, "misleading": task.misleading}
        for cond in CONDITIONS:
            for s in seeds:
                ok, steps = run_one(task, exps[cond], s)
                grid.append({"task": task.id, "kind": task.kind, "cond": cond,
                             "seed": s, "passed": ok, "steps": steps})
                print(f"  {task.id:9s} {cond:11s} seed={s}  pass={ok!s:5s} steps={steps}", flush=True)

    # exp3: condition comparison across all tasks
    print("\n== exp3: success rate & avg cost by condition (across all tasks) ==")
    cond_summary = {}
    for cond in CONDITIONS:
        rows = [g for g in grid if g["cond"] == cond]
        pr = sum(g["passed"] for g in rows) / len(rows)
        steps = statistics.mean(g["steps"] for g in rows)
        cond_summary[cond] = {"pass_rate": pr, "avg_steps": steps, "n": len(rows)}
        print(f"  {cond:11s} success={pr*100:5.0f}%   avg_steps={steps:4.1f}   (n={len(rows)})")

    # per-task flip: none -> good
    print("\n== per-task: did the good experience flip failure to success? ==")
    flips = 0
    for task in TASKS:
        nrows = [g for g in grid if g["task"] == task.id and g["cond"] == "none"]
        grows = [g for g in grid if g["task"] == task.id and g["cond"] == "good"]
        nb = sum(g["passed"] for g in nrows)
        gb = sum(g["passed"] for g in grows)
        flip = nb == 0 and gb == len(grows)
        flips += int(flip)
        print(f"  {task.id:9s} none={nb}/{len(nrows)}  good={gb}/{len(grows)}  flip={flip}")
    print(f"\n  clean flips: {flips}/{len(TASKS)} tasks")

    print("\n== exp4 data: (cost, success) points for the Pareto view (plotted in M5) ==")
    for cond in CONDITIONS:
        c = cond_summary[cond]
        print(f"  {cond:11s} -> (avg_steps={c['avg_steps']:.1f}, success={c['pass_rate']*100:.0f}%)")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"phaseA_{int(time.time())}.json"
    out.write_text(json.dumps({"seeds": seeds, "conditions": CONDITIONS,
                               "condition_summary": cond_summary, "flips": flips, "grid": grid},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
