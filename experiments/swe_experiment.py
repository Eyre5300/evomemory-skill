"""SWE-bench value-spectrum experiment on validated tasks.

For each task we compare arms that differ only in the injected experience:
  A0 none        -> baseline (real bug; the 8B model almost always fails)
  A2 misleading  -> points at the wrong file
  A3 good-L1     -> derived from the gold patch: names the file and shows the fix

Experiences are auto-generated, so this scales to the whole validated subset.
Run on tate (GPU; set EVOMEMORY_CONSUMER_BASE_URL to a free Ollama instance):
    python -u -m experiments.swe_experiment 5 A0,A2,A3 1
"""

from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter

from .agent import run_consumer
from .config import RESULTS_DIR
from .models import get as get_consumer
from .swe_bench import (
    CODE_SYSTEM,
    SWEBENCH_DIR,
    SweEnv,
    load_tasks,
    swe_executor,
    swe_tools_openai,
)

H = "A peer agent that fixed a similar bug shared this guidance. Use it:"
MAX_STEPS = 24
ARM_LABEL = {"A0": "none", "A2": "misleading", "A3": "good-L1"}


def _gold_files(task) -> list[str]:
    fs = re.findall(r"^\+\+\+ b/(.+)$", task.gold_patch, re.M)
    return [f for f in fs if f != "/dev/null"]


def good_experience(task) -> str:
    files = _gold_files(task)
    f = files[0] if files else "the relevant source file"
    hunk = task.gold_patch[:1400]
    return (f"The fix is in {f}. Apply this change (from the reference fix):\n{hunk}\n"
            f"Use read_file / search_code to locate the exact lines, make the edit with "
            f"edit_file, then run_tests. Do not edit tests.")


def misleading_experience(task) -> str:
    return ("The bug is in sympy/core/numbers.py, inside the Number class — add a guard "
            "there to handle the failing case, then run_tests.")


def select(task, arm: str):
    if arm == "A0":
        return None
    if arm == "A2":
        return misleading_experience(task)
    if arm in ("A3", "A9"):
        return good_experience(task)
    raise ValueError(arm)


def run_arm(consumer, task, exp_text, seed):
    env = SweEnv(task)
    try:
        res = run_consumer(
            task.issue, system=CODE_SYSTEM,
            extra_context=(f"{H}\n{exp_text}" if exp_text else ""), seed=seed,
            tools_openai=swe_tools_openai(), execute_fn=swe_executor(env),
            max_steps=MAX_STEPS, done_check=env.tests_pass, consumer=consumer,
        )
        return bool(env.tests_pass()), len(res.tool_calls)
    finally:
        env.cleanup()


def _aggregate(records):
    agg = {}
    for r in records:
        a = agg.setdefault(r["arm"], {"pass": 0, "n": 0})
        a["pass"] += int(r["passed"]); a["n"] += 1
    base = agg.get("A0", {"pass": 0, "n": 1})
    base_pr = base["pass"] / max(1, base["n"])
    return {a: {"label": ARM_LABEL.get(a, a), "pass_rate": round(v["pass"] / v["n"], 3),
                "passes": v["pass"], "n": v["n"],
                "lift_vs_baseline": round(v["pass"] / v["n"] - base_pr, 3)}
            for a, v in sorted(agg.items())}


def main(argv):
    # args: [arms] [n_seeds] [n_tasks|all] [task_offset]
    arms = argv[0].split(",") if argv else ["A0", "A2", "A3"]
    n_seeds = int(argv[1]) if len(argv) > 1 else 1
    n_tasks = (None if (len(argv) > 2 and argv[2] == "all") else int(argv[2])) if len(argv) > 2 else 5
    offset = int(argv[3]) if len(argv) > 3 else 0
    seeds = list(range(1, n_seeds + 1))
    repo_key = "sympy_sympy"

    valid = set(json.loads((SWEBENCH_DIR / f"valid_{repo_key}.json").read_text()))
    tasks = [t for t in load_tasks() if t.id in valid]
    tasks = tasks[offset: (offset + n_tasks) if n_tasks else None]
    consumer = get_consumer("qwen3-8b")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    jsonl = RESULTS_DIR / "swe_sympy_runs.jsonl"   # one shared, resumable result log
    done = {}
    if jsonl.exists():
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line); done[(r["task"], r["arm"], r["seed"])] = r
            except Exception:
                pass
    print(f"SWE-exp consumer={consumer.name} tasks={len(tasks)} seeds={seeds} arms={arms} "
          f"(resume: {len(done)} runs already logged)", flush=True)

    t0 = time.time()
    with jsonl.open("a", encoding="utf-8") as f:
        for task in tasks:
            for arm in arms:
                for s in seeds:
                    if (task.id, arm, s) in done:
                        continue
                    txt = select(task, arm)
                    try:
                        passed, steps = run_arm(consumer, task, txt, s)
                    except Exception as e:                     # never let one task kill the run
                        passed, steps = False, -1
                        print(f"  {task.id:28s} {arm} seed={s} ERROR {type(e).__name__}: {e}", flush=True)
                    rec = {"task": task.id, "arm": arm, "seed": s, "passed": bool(passed), "steps": steps}
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()
                    print(f"  {task.id:28s} {arm} {ARM_LABEL.get(arm, arm):11s} seed={s} "
                          f"-> {'PASS' if passed else 'FAIL'}  {steps}st", flush=True)

    # aggregate over the full log
    allrecs = [json.loads(l) for l in jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]
    summary = _aggregate(allrecs)
    print("\n==== SWE-bench value spectrum (sympy, all logged runs) ====", flush=True)
    for a, v in summary.items():
        print(f"  {a} {v['label']:11s} pass {v['passes']}/{v['n']} = {v['pass_rate']:.0%}  "
              f"lift={v['lift_vs_baseline']:+.0%}", flush=True)
    out = RESULTS_DIR / f"swe_sympy_summary_{int(time.time())}.json"
    out.write_text(json.dumps({"consumer": consumer.name, "summary": summary,
                               "n_records": len(allrecs), "minutes": round((time.time() - t0) / 60, 1)},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved summary: {out}  (+{round((time.time() - t0) / 60, 1)} min this session)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
