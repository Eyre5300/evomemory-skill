"""Shopping cart that sums its lines."""

from .pricing import line_total


class Cart:
    def __init__(self):
        self._lines = []  # (name, unit_price, quantity)

    def add(self, name, unit_price, quantity):
        self._lines.append((name, unit_price, quantity))

    def total(self):
        return round(sum(line_total(p, q) for _, p, q in self._lines), 2)
