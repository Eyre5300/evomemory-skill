"""B-integration pilot: experience value spectrum on one Flask task.

Wires B1 (consumer registry) + B2 (failure-set/baseline) + B3 (provider arms) on a
single real Flask task to verify the whole pipeline end-to-end:

    A0 none       -> baseline fails (failure-set)
    A2 misleading -> wrong-file guidance, should NOT fix
    A3 good-L1    -> correct guidance, should flip to PASS

Run from repo root:
    python -u -m experiments.pilot flask_blueprint_empty 1
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
    TASKS_BY_ID,
    FlaskEnv,
    flask_executor,
    flask_tools_openai,
    make_flask_workdir,
)

H = "A peer agent that fixed a similar bug shared this guidance. Use it:"
MAX_STEPS = 22


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
    task_id = argv[0] if argv else "flask_blueprint_empty"
    seed = int(argv[1]) if len(argv) > 1 else 1
    arms = argv[2].split(",") if len(argv) > 2 else ["A0", "A2", "A3"]

    consumer = get_consumer("qwen3-8b")
    task = TASKS_BY_ID[task_id]
    lib, sc = build_flask_library()
    prov = ExperienceProvider(lib, sc)

    print(f"PILOT consumer={consumer.name} task={task_id} seed={seed} arms={arms}", flush=True)
    rows = []
    for arm in arms:
        txt, meta = prov.select(task, arm)
        t0 = time.time()
        passed, steps = run_arm(consumer, task, txt, seed)
        dt = time.time() - t0
        rows.append({"arm": arm, "label": meta["label"], "chosen": meta.get("chosen"),
                     "passed": passed, "steps": steps, "secs": round(dt, 1)})
        print(f"  {arm} {ARM_LABEL.get(arm, arm):18s} -> {'PASS' if passed else 'FAIL'}  "
              f"steps={steps}  {dt:.0f}s", flush=True)

    base = next((r for r in rows if r["arm"] == "A0"), None)
    good = next((r for r in rows if r["arm"] == "A3"), None)
    mis = next((r for r in rows if r["arm"] == "A2"), None)
    spectrum_ok = (base and not base["passed"]) and (good and good["passed"])
    if mis is not None:
        spectrum_ok = spectrum_ok and (not mis["passed"])
    print(f"\nspectrum_ok={spectrum_ok}  (A0 fail & A3 pass" + (" & A2 fail" if mis else "") + ")", flush=True)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"pilot_{task_id}_{int(time.time())}.json"
    out.write_text(json.dumps({"task": task_id, "seed": seed, "consumer": consumer.name,
                               "rows": rows, "spectrum_ok": spectrum_ok}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"saved: {out}", flush=True)
    return 0 if spectrum_ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
