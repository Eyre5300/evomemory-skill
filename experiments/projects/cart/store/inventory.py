"""Inventory tracking (unrelated to pricing)."""


class Inventory:
    def __init__(self):
        self._stock = {}

    def restock(self, name, amount):
        self._stock[name] = self._stock.get(name, 0) + amount

    def available(self, name):
        return self._stock.get(name, 0)

    def reserve(self, name, amount):
        if self.available(name) < amount:
            raise ValueError("insufficient stock")
        self._stock[name] -= amount
