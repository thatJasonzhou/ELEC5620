"""Shared exact Finance cost policy used across the workflow."""
from __future__ import annotations

from src.shared.schemas import require_int


def calculate_event_costs(vendor_cost_cents: int) -> dict[str, int]:
    """Return GST-inclusive totals with independently rounded 10% charges."""
    vendor = require_int(vendor_cost_cents, "vendor_cost_cents", minimum=0)
    fee = (vendor + 5) // 10
    return {
        "vendor_cost_cents": vendor,
        "service_fee_cents": fee,
        "contingency_amount_cents": fee,
        "tax_amount_cents": 0,
        "customer_price_cents": vendor + fee + fee,
    }


def supplier_budget_ceiling(customer_budget_cents: int) -> int:
    """Largest whole-cent supplier subtotal whose complete cost fits."""
    limit = require_int(customer_budget_cents, "customer_budget_cents", minimum=0)
    low, high = 0, limit
    while low < high:
        middle = (low + high + 1) // 2
        if calculate_event_costs(middle)["customer_price_cents"] <= limit:
            low = middle
        else:
            high = middle - 1
    return low
