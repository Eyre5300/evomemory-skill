"""Unrelated helpers (distractor)."""


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def is_sorted(xs):
    return all(a <= b for a, b in zip(xs, xs[1:]))
