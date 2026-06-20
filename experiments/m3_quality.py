"""M3: P/G quality scoring + quality-based experience selection (proposal §3, §4.4).

Given a POOL of candidate experiences of varying quality for the same multi-step
task, this:
  1. computes each experience's structural quality (ContextDensity, G_structural)
     at "upload" time and stores it in the client-side P/G sidecar;
  2. verifies each experience by having the weak model (qwen) try the task with it
     over several seeds, feeding P_empirical / G_empirical back into the sidecar;
  3. ranks by P(e) and selects the best — showing that quality filtering picks the
     experience that actually works, even when several "look" specific.

Run from repo root (temp 0 recommended):
    python -m experiments.m3_quality 3
"""

from __future__ import annotations

import json
import sys
import time

from evomemory_sync.context_density import (
    build_swebench_dimensions,
    compute_context_density,
    extract_experience_constraints,
)
from evomemory_sync.experience_quality import g_structural_from_text
from evomemory_sync.quality_sidecar import QualitySidecar

from .agent import run_consumer
from .code_env import (
    CODE_SYSTEM,
    TASK_PROMPT,
    CodeEnv,
    code_executor,
    code_tools_openai,
    make_workdir,
)
from .config import RESULTS_DIR

TASK_KIND = "cart_bulk_discount"
POOL = json.loads((__import__("pathlib").Path(__file__).resolve().parent / "code_experiences.json").read_text(encoding="utf-8"))

# Measured stats of the cart project (drive the ContextDensity decision model).
CART_STATS = dict(
    repo_py_files=5, module_py_files=5, keyword_candidate_files=3,
    target_file_functions=2, edit_sites_in_function=2, subpackages=1, module_name="store",
)


def structural_scores(text: str) -> tuple[float, float]:
    constraints = extract_experience_constraints("", text)
    dims = build_swebench_dimensions(constraints=constraints, **CART_STATS)
    cd = compute_context_density(dims).context_density
    gs = g_structural_from_text("", text)
    return cd, gs


def verify_once(text: str, seed: int) -> bool:
    env = CodeEnv(make_workdir())
    try:
        res = run_consumer(
            TASK_PROMPT, system=CODE_SYSTEM,
            extra_context=f"A peer agent shared this guidance. Use it:\n{text}",
            seed=seed, tools_openai=code_tools_openai(), execute_fn=code_executor(env), max_steps=18,
        )
        _ = res
        return env.tests_pass()
    finally:
        env.cleanup()


def main(argv: list[str]) -> int:
    n = int(argv[0]) if argv else 3
    seeds = list(range(1, n + 1))
    db = RESULTS_DIR / "quality_sidecar.db"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if db.exists():
        db.unlink()
    side = QualitySidecar(str(db))

    print("== 1. structural scores at upload (cold start, no verification yet) ==")
    for e in POOL:
        cd, gs = structural_scores(e["text"])
        side.upsert_structural(e["id"], context_density=cd, g_structural=gs, text=e["text"])
        q = side.quality(e["id"])
        print(f"  {e['id']:14s} ContextDensity={cd:.2f} G_struct={gs:.2f}  -> cold P={q.p:.2f} G={q.g:.2f}")

    print(f"\n== 2. verify each experience on the task ({len(seeds)} seeds) ==")
    for e in POOL:
        oks = []
        for s in seeds:
            ok = verify_once(e["text"], s)
            side.record_verification(e["id"], task_kind=TASK_KIND, success=ok)
            oks.append("P" if ok else "F")
        print(f"  {e['id']:14s} {' '.join(oks)}  ({oks.count('P')}/{len(seeds)} pass)")

    print("\n== 3. final P/G ranking (after verification) ==")
    ranked = side.ranked(by="p")
    for eid, q in ranked:
        m = q.metadata
        print(f"  {eid:14s} P={q.p:.2f}  G={q.g:.2f}  (P_emp={q.p_empirical:.2f} x CD={q.context_density:.2f}; "
              f"verified {m['successes']}/{m['trials']})")

    best = side.best(min_p=0.5)
    print(f"\n== 4. quality filter selects: {best[0] if best else None} "
          f"(P={best[1].p:.2f}) -> inject this one ==" if best else "\n== no experience meets min_p ==")

    out = RESULTS_DIR / f"m3_quality_{int(time.time())}.json"
    out.write_text(json.dumps(
        {"seeds": seeds, "ranking": [{"eid": eid, **q.to_dict()} for eid, q in ranked],
         "selected": best[0] if best else None}, ensure_ascii=False, indent=2), encoding="utf-8")
    side.close()
    print(f"saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
