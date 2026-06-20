"""Behaviour tests for the store package."""

from store.cart import Cart


def test_small_order_no_discount():
    c = Cart()
    c.add("widget", 2.0, 3)
    assert c.total() == 6.0


def test_exactly_threshold_is_not_bulk():
    # 10 units is NOT a bulk order -> no discount -> 2.0 * 10 = 20.0
    c = Cart()
    c.add("widget", 2.0, 10)
    assert c.total() == 20.0


def test_above_threshold_gets_bulk_discount():
    # 11 units IS a bulk order -> 10% off -> 2.0 * 11 * 0.9 = 19.8
    c = Cart()
    c.add("widget", 2.0, 11)
    assert c.total() == 19.8
