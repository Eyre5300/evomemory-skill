"""Line pricing with bulk discounts."""

from .discounts import BULK_DISCOUNT_RATE, BULK_THRESHOLD


def bulk_discount_rate(quantity):
    """Discount rate for a line of `quantity` units.

    Bulk pricing applies only to orders ABOVE the threshold; exactly
    BULK_THRESHOLD units is a normal order.
    """
    if quantity >= BULK_THRESHOLD:
        return BULK_DISCOUNT_RATE
    return 0.0


def line_total(unit_price, quantity):
    """Total cost of one cart line after any bulk discount."""
    rate = bulk_discount_rate(quantity)
    return unit_price * quantity * (1.0 - rate)
