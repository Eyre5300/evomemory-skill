"""Faithful closed loop on a REAL SWE-bench task (pallets/flask-5014).

baseline (qwen alone on the full Flask repo) -> if it fails -> producer (Claude)
uploads a pruning experience to the Hub -> the skill fetches it back -> qwen retries.
flip = baseline failed AND retry passes.

Run from repo root (temp 0):
    python -m experiments.swe_loop 1
"""

from __future__ import annotations

import json
import sys
import time

from .agent import run_consumer
from .config import RESULTS_DIR
from .hub_fetch import fetch_recipe_solution, upload_recipe
from .swe_flask import (
    CODE_SYSTEM,
    EXPERIENCE,
    ISSUE,
    FlaskEnv,
    flask_executor,
    flask_tools_openai,
    make_flask_workdir,
)

H = "A peer agent that fixed a similar bug shared this guidance. Use it:"
MAX_STEPS = 22


def run_n(exp_text: str | None, seeds: list[int]) -> tuple[int, list[int], list[list[str]]]:
    passes, steps, tools = 0, [], []
    for s in seeds:
        env = FlaskEnv(make_flask_workdir())
        try:
            res = run_consumer(
                ISSUE, system=CODE_SYSTEM,
                extra_context=(f"{H}\n{exp_text}" if exp_text else ""), seed=s,
                tools_openai=flask_tools_openai(), execute_fn=flask_executor(env),
                max_steps=MAX_STEPS, done_check=env.tests_pass,
            )
            passes += int(env.tests_pass())
            steps.append(len(res.tool_calls))
            tools.append([c["name"] for c in res.tool_calls])
        finally:
            env.cleanup()
    return passes, steps, tools


def main(argv: list[str]) -> int:
    n = int(argv[0]) if argv else 1
    seeds = list(range(1, n + 1))
    print(f"Real SWE-bench task: pallets/flask-5014 (Blueprint empty name) | seeds={seeds}\n")

    base, bsteps, btools = run_n(None, seeds)
    print(f"  baseline (qwen alone): {base}/{n} PASS   steps={bsteps}")
    for i, t in enumerate(btools):
        print(f"    seed{seeds[i]} tools: {t}")

    record = {"task": "flask-5014", "seeds": seeds, "baseline_pass": base,
              "baseline_steps": bsteps, "baseline_tools": btools}

    if base == n:
        print("\n  small model solves it unaided -> not a needs-experience task")
    else:
        mid = upload_recipe("coderepair::flask-5014", ISSUE, EXPERIENCE,
                            tags="coderepair,swe-bench,flask")
        fetched = fetch_recipe_solution(mid) if mid else None
        used = fetched or EXPERIENCE
        via = "Hub" if fetched else "local-fallback"
        print(f"\n  producer uploaded experience ({mid[:8] if mid else 'none'}); skill fetch via {via}")
        retry, rsteps, rtools = run_n(used, seeds)
        print(f"  retry (qwen + experience): {retry}/{n} PASS   steps={rsteps}")
        for i, t in enumerate(rtools):
            print(f"    seed{seeds[i]} tools: {t}")
        flip = base < n and retry > base
        print(f"\n  ==== baseline {base}/{n} -> retry {retry}/{n}   FLIP={flip} ====")
        record.update({"memory_id": mid, "fetched_via": via, "retry_pass": retry,
                       "retry_steps": rsteps, "retry_tools": rtools, "flip": flip})

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"swe_loop_{int(time.time())}.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
