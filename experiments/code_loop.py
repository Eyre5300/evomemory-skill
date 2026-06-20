"""Closed-loop MVP on a multi-step code-repair task (faithful to the proposal §1-2).

A genuinely multi-step agentic task with a real exploration space: the weak model
(qwen) must navigate a multi-file project, locate a bug, edit it, and pass the tests.
Without guidance it tends to explore the wrong files and exhaust its step budget; the
experience (from Claude, the producer) prunes the search space to the right file/fix.

Run from repo root:
    python -m experiments.code_loop          # seed 1, baseline vs +experience
    python -m experiments.code_loop 5         # seeds 1..5, report pass rates
"""

from __future__ import annotations

import json
import sys
import time
from types import SimpleNamespace

from .agent import run_consumer
from .closed_loop import share_experience
from .code_env import (
    CODE_SYSTEM,
    TASK_PROMPT,
    CodeEnv,
    code_executor,
    code_tools_openai,
    make_workdir,
)
from .config import RESULTS_DIR

EXP_HEADER = "A peer agent that fixed a similar bug shared this guidance. Use it:"
EXPERIENCE = (__import__("pathlib").Path(__file__).resolve().parent / "code_experience.txt").read_text(encoding="utf-8").strip()
MAX_STEPS = 18


def run_trial(experience: str | None, seed: int) -> dict:
    env = CodeEnv(make_workdir())
    try:
        extra = f"{EXP_HEADER}\n{experience}" if experience else ""
        res = run_consumer(
            TASK_PROMPT, system=CODE_SYSTEM, extra_context=extra, seed=seed,
            tools_openai=code_tools_openai(), execute_fn=code_executor(env), max_steps=MAX_STEPS,
        )
        passed = env.tests_pass()
        files_touched = sorted({c["args"].get("path", "") for c in res.tool_calls
                                if c["name"] == "edit_file"})
        return {"passed": passed, "tool_steps": len(res.tool_calls),
                "tools_used": [c["name"] for c in res.tool_calls], "files_edited": files_touched,
                "error": res.error}
    finally:
        env.cleanup()


def main(argv: list[str]) -> int:
    n = int(argv[0]) if argv else 1
    seeds = list(range(1, n + 1))
    print(f"Code-repair closed loop | seeds={seeds} | experience from Claude (producer)\n")

    # Share the experience to the Hub once (real skill path).
    share = share_experience(SimpleNamespace(id="cart_bulk_discount", prompt=TASK_PROMPT),
                             EXPERIENCE, "(Claude, in-session producer)")
    print(f"experience -> Hub: {share.get('uploaded')}  {share.get('memory_id') or share.get('reason','')}\n")

    records = []
    base_pass = exp_pass = 0
    for s in seeds:
        b = run_trial(None, s)
        e = run_trial(EXPERIENCE, s)
        base_pass += int(b["passed"])
        exp_pass += int(e["passed"])
        flip = (not b["passed"]) and e["passed"]
        print(f"seed={s}  baseline={'PASS' if b['passed'] else 'FAIL'}({b['tool_steps']}st)  "
              f"+exp={'PASS' if e['passed'] else 'FAIL'}({e['tool_steps']}st)  FLIP={flip}")
        records.append({"seed": s, "baseline": b, "with_experience": e, "flip": flip})

    print(f"\n==== baseline {base_pass}/{len(seeds)} PASS   |   +experience {exp_pass}/{len(seeds)} PASS ====")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"code_loop_{int(time.time())}.json"
    out.write_text(json.dumps({"seeds": seeds, "experience": EXPERIENCE,
                               "baseline_pass": base_pass, "experience_pass": exp_pass,
                               "share": share, "records": records}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
