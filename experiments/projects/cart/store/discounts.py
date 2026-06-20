"""Discount policy constants.

Bulk orders (strictly MORE than BULK_THRESHOLD units of a single line) get a
percentage off that line. An order of exactly BULK_THRESHOLD units is a normal
order and gets no discount.
"""

BULK_THRESHOLD = 10        # units; bulk pricing applies above this, not at it
BULK_DISCOUNT_RATE = 0.10  # 10% off the qualifying line

# Loyalty tiers are unrelated to bulk pricing (kept here for reference).
LOYALTY_RATES = {"silver": 0.02, "gold": 0.05}
