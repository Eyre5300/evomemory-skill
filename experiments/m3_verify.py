"""M3 acceptance verification: are all M3 goals met?

Goals:
  G1  L1/L2/L3 are generated (non-empty, distinct).
  G2  §2.3 ordering: G_structural increases L1->L2->L3; ContextDensity decreases
      L1->L3; L1 names a file, L3 names none.
  G3  The three levels integrate into the P/G sidecar (3 entries, each with P/G).
  G4  Quality selection: among experiences of differing verified quality, best()
      picks the working one (deterministic check, no qwen).

Run from repo root:
    python -m experiments.m3_verify
Exit code 0 = all goals met.
"""

from __future__ import annotations

import sys

from evomemory_sync.abstraction import generate_levels
from evomemory_sync.context_density import extract_experience_constraints
from evomemory_sync.quality_sidecar import QualitySidecar

from .m3_quality import structural_scores

RAW = (
    "The failing test is a boundary bug: an order whose quantity is exactly the bulk "
    "threshold is wrongly given the bulk discount. Fix it in store/pricing.py, in the "
    "function bulk_discount_rate, by changing the comparison `quantity >= BULK_THRESHOLD` "
    "to `quantity > BULK_THRESHOLD`, then run the tests."
)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


def main() -> int:
    print("== generate L1/L2/L3 from one raw experience (local qwen) ==")
    lv = generate_levels(RAW, seed=0)
    for k in ("l1", "l2", "l3"):
        print(f"  {k.upper()}: {lv[k]}")
    if lv.get("_error"):
        print(f"  (abstraction error: {lv['_error']})")

    print("\n== G1: levels generated, non-empty and distinct ==")
    check("L1/L2/L3 non-empty", all(lv[k] for k in ("l1", "l2", "l3")))
    check("levels are distinct", len({lv["l1"], lv["l2"], lv["l3"]}) == 3)

    print("\n== G2: §2.3 abstraction ordering ==")
    cd1, gs1 = structural_scores(lv["l1"])
    cd2, gs2 = structural_scores(lv["l2"])
    cd3, gs3 = structural_scores(lv["l3"])
    print(f"  L1: ContextDensity={cd1:.2f} G_struct={gs1:.2f}")
    print(f"  L2: ContextDensity={cd2:.2f} G_struct={gs2:.2f}")
    print(f"  L3: ContextDensity={cd3:.2f} G_struct={gs3:.2f}")
    check("G_structural non-decreasing L1<=L2<=L3", gs1 <= gs2 + 1e-9 and gs2 <= gs3 + 1e-9,
          f"{gs1:.2f} <= {gs2:.2f} <= {gs3:.2f}")
    check("G_structural separates L1<L3", gs3 > gs1 + 1e-9, f"{gs1:.2f} < {gs3:.2f}")
    check("ContextDensity L1>=L3 (L1 prunes more)", cd1 >= cd3 - 1e-9, f"{cd1:.2f} >= {cd3:.2f}")
    check("L1 names a file", len(extract_experience_constraints("", lv["l1"]).pinned_files) > 0)
    check("L3 names no file", len(extract_experience_constraints("", lv["l3"]).pinned_files) == 0)

    print("\n== G3: three levels integrate into the P/G sidecar ==")
    side = QualitySidecar()
    for lvl, (cd, gs) in (("L1", (cd1, gs1)), ("L2", (cd2, gs2)), ("L3", (cd3, gs3))):
        side.upsert_structural(f"cart::{lvl}", context_density=cd, g_structural=gs, text=lv[lvl.lower()])
    qs = {eid: side.quality(eid) for eid in side.eids()}
    check("3 levels stored with P/G", len(qs) == 3 and all(0 <= q.p <= 1 and 0 <= q.g <= 1 for q in qs.values()))

    print("\n== G4: quality selection picks the verified-working experience ==")
    sel = QualitySidecar()
    sel.upsert_structural("good", context_density=0.8, g_structural=0.4)
    sel.upsert_structural("misleading", context_density=0.8, g_structural=0.4)  # same structure
    for _ in range(3):
        sel.record_verification("good", task_kind="k", success=True)
        sel.record_verification("misleading", task_kind="k", success=False)
    best = sel.best(min_p=0.5)
    check("best() selects 'good' over 'misleading'", best is not None and best[0] == "good",
          f"P(good)={sel.quality('good').p:.2f} vs P(misleading)={sel.quality('misleading').p:.2f}")
    side.close()
    sel.close()

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n==== M3 goals: {passed}/{len(results)} checks PASS ====")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
