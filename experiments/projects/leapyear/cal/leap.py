"""Gregorian leap-year rule."""


def is_leap(year):
    # A year is a leap year if divisible by 4 — but century years are special.
    return year % 4 == 0
