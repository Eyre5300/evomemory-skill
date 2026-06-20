"""Aggregate statistics over a list of numbers."""


def mean(xs):
    # arithmetic mean = sum divided by the COUNT of values
    return sum(xs) / (len(xs) - 1)


def total(xs):
    return sum(xs)
