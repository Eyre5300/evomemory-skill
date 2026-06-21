"""M6: metric trustworthiness validation (the reviewer's main attack surface).

Two checks that need no API:
  1. Determinism — our ContextDensity / G_structural are rule-based, so test-retest
     reliability is 1.0 by construction (no LLM noise to ICC away). We assert it.
  2. G_structural validity — a labelled set (each idea written at L1/L2/L3 by a strong
     model) is scored; G_structural must rank the concrete (L1) below the abstract
     (L3). We report within-topic ordering accuracy.

Known limitation surfaced honestly: rule-based G_structural counts only *hard* pins
(file/function/literal), so it cannot separate L2 (pattern) from L3 (principle) when
neither names specifics — that separation needs G_empirical (cross-kind verification).

Run from repo root:
    python -m experiments.m6_validation
"""

from __future__ import annotations

from evomemory_sync.context_density import extract_experience_constraints
from evomemory_sync.experience_quality import g_structural_from_text

# Each topic written at three abstraction levels by a strong model (the reference labels).
LABELED = [
    # topic, level, text
    ("cart", "L1", "Edit src/store/pricing.py in the function bulk_discount_rate: change the "
                   "comparison `quantity >= BULK_THRESHOLD` to `quantity > BULK_THRESHOLD`."),
    ("cart", "L2", "For a bulk-discount boundary bug, check the quantity-versus-threshold comparison "
                   "operator in the pricing logic; it often wrongly includes the threshold value."),
    ("cart", "L3", "When a test fails exactly at a boundary, suspect an inclusive-versus-exclusive "
                   "comparison and re-derive the intended edge behaviour."),
    ("blueprint", "L1", "In src/flask/blueprints.py, in Blueprint.__init__, add before `self.name = name` "
                        "the lines `if not name: raise ValueError(\"'name' must not be empty.\")`."),
    ("blueprint", "L2", "Constructor validation bugs live in the class __init__; add the missing guard "
                        "next to the existing argument checks and raise the same error type."),
    ("blueprint", "L3", "Validate inputs at the boundary where an object is created, failing fast with a "
                        "clear error rather than allowing an invalid state."),
    ("leap", "L1", "In cal/leap.py, change `return year % 4 == 0` to also apply the century rule: "
                   "`return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)`."),
    ("leap", "L2", "For a leap-year check, remember the Gregorian century exception: divisibility by 4 "
                   "is not sufficient; handle the 100/400 special case."),
    ("leap", "L3", "Encode the full rule, not the common case — special exceptions at round numbers are "
                   "where naive conditionals break."),
]

LEVEL_RANK = {"L1": 0, "L2": 1, "L3": 2}


def main() -> int:
    print("== 1. determinism (rule-based metric -> test-retest = 1.0) ==")
    sample = LABELED[0][2]
    a = g_structural_from_text("", sample)
    b = g_structural_from_text("", sample)
    det = a == b
    print(f"  [{'PASS' if det else 'FAIL'}] same text -> identical G_structural ({a:.3f} == {b:.3f})")

    print("\n== 2. G_structural validity vs strong-model abstraction labels ==")
    scored = []
    for topic, level, text in LABELED:
        gs = g_structural_from_text("", text)
        n = len(extract_experience_constraints("", text).pinned_files) \
            + len(extract_experience_constraints("", text).pinned_functions) \
            + len(extract_experience_constraints("", text).literal_parameters)
        scored.append((topic, level, gs, n))
        print(f"  {topic:10s} {level}  G_structural={gs:.2f}  (hard pins={n})")

    # within-topic ordering: L1 must score below L3 (concrete < abstract)
    topics = sorted({t for t, _, _, _ in scored})
    ok_pairs, total_pairs, strict_L1_below_L3 = 0, 0, 0
    for topic in topics:
        rows = {lv: gs for t, lv, gs, _ in scored if t == topic}
        for lo, hi in (("L1", "L2"), ("L2", "L3"), ("L1", "L3")):
            total_pairs += 1
            if rows[lo] <= rows[hi] + 1e-9:
                ok_pairs += 1
        if rows["L1"] < rows["L3"] - 1e-9:
            strict_L1_below_L3 += 1

    print(f"\n  monotonic ordering (L1<=L2<=L3) held on {ok_pairs}/{total_pairs} within-topic pairs")
    print(f"  L1 strictly below L3 (concrete < abstract): {strict_L1_below_L3}/{len(topics)} topics")
    print("  note: L2 vs L3 may tie — rule-based G_structural only counts hard pins; "
          "L2/L3 separation needs G_empirical.")

    det_ok = det
    valid_ok = strict_L1_below_L3 == len(topics) and ok_pairs == total_pairs
    print(f"\n==== M6: determinism={'PASS' if det_ok else 'FAIL'}  "
          f"G_structural validity={'PASS' if valid_ok else 'FAIL'} ====")
    return 0 if (det_ok and valid_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
