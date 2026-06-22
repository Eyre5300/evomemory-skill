"""Experiment 1: experience value spectrum across the Flask suite (core result).

Phase 1 (failure-set, B2): baseline arm A0 on every task x seed; keep tasks 0/N.
Phase 2 (arms, B3): on the failure-set, run each arm x seed over the same scaffold.
Aggregate per-arm pass rate + avg steps, save JSON for analysis (Phase E).

A8 (Ours) injects whatever P/G re-rank selects; A9 (oracle)=good L1 — both reuse the
good-L1 injection, so by default we run the *distinct* injections A0,A1,A2,A3,A4,A5
and record A8's selection separately (verified deterministically in B3).

Run on tate:
    python -u -m experiments.experiment1 3 A0,A1,A2,A3,A4,A5
"""

from __future__ import annotations

import json
import sys
import time

from .agent import run_consumer
from .config import RESULTS_DIR
from .models import get as get_consumer
from .provider import ARM_LABEL, ExperienceProvider, build_flask_library
from .swe_flask import (
    CODE_SYSTEM,
    FLASK_TASKS,
    FlaskEnv,
    flask_executor,
    flask_tools_openai,
    make_flask_workdir,
)

H = "A peer agent that fixed a similar bug shared this guidance. Use it:"
MAX_STEPS = 20


def run_arm(consumer, task, exp_text, seed):
    env = FlaskEnv(make_flask_workdir(task), task.check)
    try:
        res = run_consumer(
            task.issue, system=CODE_SYSTEM,
            extra_context=(f"{H}\n{exp_text}" if exp_text else ""), seed=seed,
            tools_openai=flask_tools_openai(), execute_fn=flask_executor(env),
            max_steps=MAX_STEPS, done_check=env.tests_pass, consumer=consumer,
        )
        return bool(env.tests_pass()), len(res.tool_calls)
    finally:
        env.cleanup()


def main(argv):
    n = int(argv[0]) if argv else 3
    arms = argv[1].split(",") if len(argv) > 1 else ["A0", "A1", "A2", "A3", "A4", "A5"]
    seeds = list(range(1, n + 1))
    consumer = get_consumer("qwen3-8b")
    lib, sc = build_flask_library()
    prov = ExperienceProvider(lib, sc)
    t_start = time.time()
    print(f"EXP1 consumer={consumer.name} tasks={[t.id for t in FLASK_TASKS]} seeds={seeds} arms={arms}", flush=True)

    records = []  # {task, arm, label, seed, passed, steps, chosen}

    # --- Phase 1: baseline on every task (record rate; do NOT skip) ---
    base_rate = {}
    for task in FLASK_TASKS:
        bp = 0
        for s in seeds:
            passed, steps = run_arm(consumer, task, None, s)
            records.append({"task": task.id, "arm": "A0", "label": "none", "seed": s,
                            "passed": passed, "steps": steps})
            bp += int(passed)
        base_rate[task.id] = bp / n
        tag = "failure-set" if bp == 0 else ("hard" if bp < n else "solvable")
        print(f"[phase1] {task.id:26s} baseline {bp}/{n} ({tag})", flush=True)

    # --- Phase 2: arms on ALL tasks (lift over baseline; suite is borderline-easy) ---
    for task in FLASK_TASKS:
        for arm in arms:
            if arm == "A0":
                continue
            for s in seeds:
                txt, meta = prov.select(task, arm)
                passed, steps = run_arm(consumer, task, txt, s)
                records.append({"task": task.id, "arm": arm, "label": ARM_LABEL.get(arm, arm),
                                "seed": s, "passed": passed, "steps": steps,
                                "chosen": meta.get("chosen")})
                print(f"[phase2] {task.id:26s} {arm} {ARM_LABEL.get(arm, arm):16s} seed={s} "
                      f"-> {'PASS' if passed else 'FAIL'}  {steps}st", flush=True)

    # --- aggregate per-arm over ALL task x seed, with lift over A0 baseline ---
    agg = {}
    for r in records:
        a = agg.setdefault(r["arm"], {"label": r["label"], "pass": 0, "n": 0, "steps": []})
        a["pass"] += int(r["passed"]); a["n"] += 1; a["steps"].append(r["steps"])
    base = agg.get("A0", {"pass": 0, "n": 1})
    base_pr = base["pass"] / base["n"]
    summary = {a: {"label": v["label"], "pass_rate": round(v["pass"] / v["n"], 3),
                   "passes": v["pass"], "n": v["n"],
                   "avg_steps": round(sum(v["steps"]) / len(v["steps"]), 1),
                   "lift_vs_baseline": round(v["pass"] / v["n"] - base_pr, 3)}
               for a, v in sorted(agg.items())}

    print("\n==== value spectrum (all tasks; lift vs A0 baseline) ====", flush=True)
    for a, v in summary.items():
        print(f"  {a} {v['label']:16s} pass {v['passes']}/{v['n']} = {v['pass_rate']:.0%}  "
              f"lift={v['lift_vs_baseline']:+.0%}  avg_steps={v['avg_steps']}", flush=True)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"exp1_flask_{int(time.time())}.json"
    out.write_text(json.dumps({"consumer": consumer.name, "seeds": seeds, "arms": arms,
                               "baseline_rate_per_task": base_rate, "summary": summary, "records": records,
                               "minutes": round((time.time() - t_start) / 60, 1)},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved: {out}  ({round((time.time() - t_start) / 60, 1)} min)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
