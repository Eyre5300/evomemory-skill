"""Registry of mini code-repair tasks (M4 Phase A — local, multi-task).

Each task is a small multi-file project under projects/<id> with one bug and a
failing test. `good` is the producer's pruning experience (points to the right
file + bug nature, NOT the literal diff); `misleading` points to a distractor
file. `kind` groups tasks for cross-kind generalization analysis.
"""

from __future__ import annotations

from dataclasses import dataclass

VAGUE = "Read the code carefully, find the bug, and fix it so that all tests pass."


@dataclass(frozen=True)
class CodeTask:
    id: str
    kind: str
    good: str
    misleading: str


TASKS: list[CodeTask] = [
    CodeTask(
        "cart", "boundary",
        good=("The failing test is a boundary bug in the bulk-discount rule: an order at exactly the "
              "threshold is wrongly given the discount. The discount decision is in store/pricing.py — "
              "cart.py only sums, discounts.py holds constants, inventory.py is unrelated. Look at how the "
              "quantity is compared against the threshold there and make it correct, then run the tests."),
        misleading=("The bug is in store/cart.py: the total() method rounds the sum incorrectly. Fix the "
                    "rounding logic in cart.py and the tests will pass."),
    ),
    CodeTask(
        "stats", "arithmetic",
        good=("The failing test is in mean(): in calc/aggregate.py the mean divides the sum by the wrong "
              "count (it does not divide by the number of values). Fix the denominator in aggregate.py. "
              "calc/util.py is unrelated, so do not edit it."),
        misleading=("The bug is in calc/util.py: is_sorted returns the wrong result, which breaks the mean. "
                    "Fix is_sorted in util.py."),
    ),
    CodeTask(
        "leapyear", "conditional",
        good=("is_leap in cal/leap.py only checks divisibility by 4, so it wrongly calls century years "
              "(like 1900) leap. Add the Gregorian century exception: a year divisible by 100 is a leap "
              "year only if also divisible by 400. cal/fmt.py is unrelated."),
        misleading=("The bug is in cal/fmt.py: days_in_month returns the wrong number of days. Fix the "
                    "month table in fmt.py."),
    ),
    CodeTask(
        "slug", "string",
        good=("slugify in textkit/slug.py only replaces spaces with hyphens; it must also strip surrounding "
              "whitespace and lowercase the text before hyphenating. Fix slugify in slug.py. textkit/clean.py "
              "is unrelated."),
        misleading=("The bug is in textkit/clean.py: collapse_spaces is wrong, which corrupts the slug. Fix "
                    "collapse_spaces in clean.py."),
    ),
]
