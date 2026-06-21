"""A3: glue between the fixed encoder and the quality sidecar.

The experiment loop calls these so that P(e) is weighted by the *real* similarity
between the experience's applicability context ψ(e) and each verification task,
and G(e) comes from the experience text. No schema change: the per-verification
``sim`` is computed here and passed to :meth:`QualitySidecar.record_verification`.
"""

from __future__ import annotations

from evomemory_sync import encoder
from evomemory_sync.quality_sidecar import QualitySidecar


def add_experience(sidecar: QualitySidecar, eid: str, *, text: str) -> None:
    """Register an experience by its text (G is derived from this text via MDL)."""
    sidecar.upsert_structural(eid, context_density=0.0, g_structural=0.0, text=text)


def record_with_sim(
    sidecar: QualitySidecar,
    eid: str,
    *,
    exp_context: str,
    task_text: str,
    task_kind: str,
    success: bool,
) -> float:
    """Record one verification, weighting it by encoder sim(ψ(e), task).

    Returns the similarity used (so the caller can log it).
    """
    sim = encoder.sim_to(exp_context, [task_text])[0]
    sidecar.record_verification(eid, task_kind=task_kind, success=bool(success), sim=sim)
    return sim


def _demo() -> int:
    from experiments.calibrate_pg import TASKS, CART_EXP

    sc = QualitySidecar()
    exp_ctx = "购物车批量折扣边界 bug:pricing.py 的 bulk_discount_rate, >= 应为 >"
    add_experience(sc, "cart_fix", text=CART_EXP)
    log = []
    for _ in range(3):
        log.append(("cart", record_with_sim(sc, "cart_fix", exp_context=exp_ctx,
                                             task_text=TASKS["cart"], task_kind="cart", success=True)))
    log.append(("leap", record_with_sim(sc, "cart_fix", exp_context=exp_ctx,
                                         task_text=TASKS["leap"], task_kind="leap", success=False)))
    q = sc.quality_v2("cart_fix")
    print("  verifications (kind, sim):", [(k, round(s, 3)) for k, s in log])
    print(f"  P={q['P']:.3f} (a_P={q['a_P']:.3f}, b_P={q['b_P']:.3f})  "
          f"G={q['G']:.3f} (L={q['L']:.1f})  trials={q['trials']}")
    ok = q["P"] > 0.5 and 0.0 < q["G"] <= 1.0
    print(f"  [{'PASS' if ok else 'FAIL'}] end-to-end: real-sim-weighted P + MDL G")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_demo())
