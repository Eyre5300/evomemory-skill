"""Text cleanup helpers (distractor)."""


def collapse_spaces(s):
    return " ".join(s.split())


def truncate(s, n):
    return s if len(s) <= n else s[:n]
