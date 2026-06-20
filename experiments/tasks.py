"""Pure-reasoning tasks for the closed-loop MVP (no web/file tools needed).

Each task is multi-step and has a checkable answer. They are chosen to be the kind
of trap a small model (qwen-8B) tends to get wrong but a strong model (Claude) gets
right — so a transferable 'method' experience can flip the weak model. The harness
verifies empirically which tasks actually exhibit the fail→success flip.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Task:
    id: str
    prompt: str
    answer: str  # canonical expected answer


def _norm(s: str) -> str:
    return re.sub(r"[\s,]", "", (s or "").strip().lower())


_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def grade(task: Task, answer: str) -> bool:
    """Grade by the answer's final number (numeric tasks) or exact match."""
    got = (answer or "").strip()
    if not got:
        return False
    if _norm(got) == _norm(task.answer):
        return True
    try:
        exp = float(task.answer)
    except ValueError:
        return _norm(task.answer) in _norm(got)  # non-numeric expected
    nums = _NUM_RE.findall(got.replace(",", ""))
    return bool(nums) and abs(float(nums[-1]) - exp) < 1e-6


TASKS: list[Task] = [
    Task(
        "units_tower",
        "What is the units digit of 7^(7^7)? Give a single number.",
        "3",
    ),
    Task(
        "last2_3pow2024",
        "What are the last two digits of 3^2024? Give a two-digit number.",
        "81",
    ),
    Task(
        "divisors_360",
        "What is the sum of all positive divisors of 360 (including 1 and 360)? Give a single number.",
        "1170",
    ),
    Task(
        "domino_2x10",
        "In how many ways can a 2x10 rectangle be tiled completely by 1x2 dominoes? Give a single number.",
        "89",
    ),
    Task(
        "no_zero_pairs",
        "How many ordered pairs (a, b) of positive integers satisfy a + b = 1000 where neither a nor b "
        "contains the digit 0 anywhere? Give a single number.",
        "738",
    ),
    Task(
        "sum_minus_odds",
        "Compute (1 + 2 + 3 + ... + 100) minus (the sum of the first 100 positive odd numbers). "
        "Give a single number (it may be negative).",
        "-4950",
    ),
    Task(
        "trailing_100fact",
        "How many trailing zeros does 100! (100 factorial) have? Give a single number.",
        "24",
    ),
    Task(
        "knights_knaves",
        "On an island, knights always tell the truth and knaves always lie. You meet A and B. "
        "A says: 'Both of us are knaves.' What is A and what is B? Answer with exactly two words: "
        "the type of A then the type of B (e.g. 'knave knight').",
        "knave knight",
    ),
]
