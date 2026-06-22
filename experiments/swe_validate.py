"""Gold-patch validation for the Docker-free SWE-bench harness.

A task is *env-valid* when our environment grades it the same way the official
benchmark would: without any fix the FAIL_TO_PASS tests fail, and after applying
the gold patch they pass. Only env-valid tasks are usable for the experiment.

Run on tate (with EVOMEMORY_SWE_PYTHON pointing at a conda env that has pytest +
the repo deps):
    python -u -m experiments.swe_validate sympy/sympy 8
"""

from __future__ import annotations

import sys
from collections import Counter

from .swe_bench import SweEnv, load_tasks


def validate(task) -> str:
    env = SweEnv(task)
    try:
        if env.tests_pass():            # tests should FAIL before any fix
            return "skip-already-pass"
        if not env.apply_gold():        # gold patch should apply cleanly
            return "gold-apply-fail"
        return "valid" if env.tests_pass() else "gold-no-pass"
    except Exception as e:
        return f"error:{type(e).__name__}"
    finally:
        env.cleanup()


def main(argv):
    repo = argv[0] if argv else "sympy/sympy"
    n = int(argv[1]) if len(argv) > 1 else 8
    tasks = [t for t in load_tasks() if t.repo == repo][:n]
    print(f"validating {len(tasks)} tasks from {repo}", flush=True)
    res = Counter()
    valid_ids = []
    for t in tasks:
        v = validate(t)
        res[v] += 1
        if v == "valid":
            valid_ids.append(t.id)
        print(f"  {t.id:32s} -> {v}", flush=True)
    print("summary:", dict(res), flush=True)
    print("valid_ids:", valid_ids, flush=True)
    import json
    from .swe_bench import SWEBENCH_DIR
    out = SWEBENCH_DIR / f"valid_{repo.replace('/', '_')}.json"
    out.write_text(json.dumps(valid_ids), encoding="utf-8")
    print(f"saved {len(valid_ids)} valid ids -> {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
