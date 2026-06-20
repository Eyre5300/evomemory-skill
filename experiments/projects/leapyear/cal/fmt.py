"""Date formatting helpers (distractor)."""


def iso(y, m, d):
    return f"{y:04d}-{m:02d}-{d:02d}"


def days_in_month(m):
    return [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
