"""A1+A2: encoder sanity (sim) and P/G v2 calibration / determinism self-check.

A1 — embed a few task descriptions, print the similarity matrix (same-topic high,
     cross-topic low), and the sim of one cart experience to each task.
A2 — on the M6 labeled L1/L2/L3 set: check the description-length ordering
     (specific L1 > L2 > L3 in L, so G is monotonically increasing toward abstract),
     pick weights that maximize within-topic ordering, and assert determinism.

Run from repo root:
    python -m experiments.calibrate_pg
Everything is deterministic and CPU-only; the encoder is a fixed model (or the
Ollama fallback), never an LLM judgement.
"""

from __future__ import annotations

import itertools

from evomemory_sync.experience_quality import (
    ComplexityWeights,
    description_length,
    generalization_mdl,
)
from experiments.m6_validation import LABELED  # [(topic, level, text), ...]

TASKS = {
    "cart": "购物车批量折扣:数量达到阈值时享折扣,边界值算错(pricing.py 的 bulk_discount_rate, >= 应为 >)",
    "leap": "闰年判断:能被 4 整除,但被 100 整除时需再被 400 整除才是闰年",
    "stats": "统计:计算一组数的中位数与均值,处理空列表与奇偶长度",
    "slug": "把文章标题转成 URL slug:转小写、空格变连字符、去除特殊字符",
    "blueprint": "Flask Blueprint 空名应抛 ValueError(blueprints.py 的 __init__ 校验 name)",
}
CART_EXP = "在 src/store/pricing.py 的 bulk_discount_rate 中,把 quantity >= BULK_THRESHOLD 改成 >"


def a1_encoder_sanity() -> bool:
    try:
        from evomemory_sync import encoder
    except Exception as e:  # pragma: no cover
        print(f"  [SKIP] encoder import failed: {e}")
        return False
    try:
        print(f"  backend = {encoder.backend_name()}")
        names = list(TASKS)
        texts = [TASKS[n] for n in names]
        # full pairwise matrix via one query each (small N)
        print("  sim matrix (rows=query):")
        print("           " + " ".join(f"{n:>9}" for n in names))
        for i, n in enumerate(names):
            sims = encoder.sim_to(texts[i], texts)
            print(f"   {n:>8} " + " ".join(f"{s:9.3f}" for s in sims))
        csim = encoder.sim_to(CART_EXP, texts)
        pairs = sorted(zip(names, csim), key=lambda kv: -kv[1])
        print("  cart-experience → tasks (desc):", [f"{n}={s:.3f}" for n, s in pairs])
        ok = pairs[0][0] == "cart"
        print(f"  [{'PASS' if ok else 'CHECK'}] cart experience most similar to cart task")
        return ok
    except Exception as e:  # pragma: no cover
        print(f"  [SKIP] embedding failed (model/server unavailable?): {e}")
        return False


def _ordering_accuracy(weights: ComplexityWeights) -> tuple[int, int]:
    """Within each topic, count L(L1) > L(L2) > L(L3) pairs satisfied."""
    bytopic: dict[str, dict[str, float]] = {}
    for topic, level, text in LABELED:
        L = description_length("", text, weights=weights)["L"]
        bytopic.setdefault(topic, {})[level] = L
    ok = tot = 0
    for levels in bytopic.values():
        for lo, hi in (("L2", "L1"), ("L3", "L2"), ("L3", "L1")):  # abstract L < specific L
            if lo in levels and hi in levels:
                tot += 1
                if levels[lo] <= levels[hi]:
                    ok += 1
    return ok, tot


def a2_calibrate_and_selfcheck() -> bool:
    print("  per-item description length L and G (default weights, lam=0.1):")
    for topic, level, text in LABELED:
        d = generalization_mdl("", text)
        print(f"    {topic:10s} {level}  N_cond={d['N_cond']} N_ent={d['N_ent']} "
              f"N_depth={d['N_depth']}  L={d['L']:.1f}  G={d['G']:.3f}")

    ok, tot = _ordering_accuracy(ComplexityWeights())
    print(f"  default weights (1,0.5,1): within-topic ordering {ok}/{tot}")

    best = (ok, tot, ComplexityWeights())
    for w1, w2, w3 in itertools.product((0.5, 1.0, 1.5, 2.0), repeat=3):
        wok, wtot = _ordering_accuracy(ComplexityWeights(w1, w2, w3))
        if wok > best[0]:
            best = (wok, wtot, ComplexityWeights(w1, w2, w3))
    bw = best[2]
    print(f"  best weights (w1,w2,w3)=({bw.conditions},{bw.entities},{bw.depth}): "
          f"ordering {best[0]}/{best[1]}")

    # determinism: same text -> identical G twice
    sample = LABELED[0][2]
    g1 = generalization_mdl("", sample)["G"]
    g2 = generalization_mdl("", sample)["G"]
    det = g1 == g2
    print(f"  [{'PASS' if det else 'FAIL'}] determinism (test-retest G {g1:.4f} == {g2:.4f})")
    return det and best[0] >= best[1] - 1  # allow at most one tie/miss


def main() -> int:
    print("== A1: encoder sanity (sim) ==")
    a1 = a1_encoder_sanity()
    print("\n== A2: P/G v2 calibration + determinism ==")
    a2 = a2_calibrate_and_selfcheck()
    print(f"\n==== A1 encoder={'OK' if a1 else 'SKIPPED'}  "
          f"A2 calibration={'PASS' if a2 else 'CHECK'} ====")
    return 0 if a2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
