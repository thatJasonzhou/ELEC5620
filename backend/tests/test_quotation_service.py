from decimal import Decimal

import pytest

from app.schemas.quotation import QuotationRequest, VendorCostItem
from app.services.quotation_service import MissingCostDataError, QuotationService


def test_calculates_itemised_customer_quotation() -> None:
    request = QuotationRequest(
        event_id="EVT-001",
        customer_budget=Decimal("10000.00"),
        vendor_costs=[
            VendorCostItem(description="Catering", quantity=1, unit_price=Decimal("3500.00")),
            VendorCostItem(description="Lighting", quantity=1, unit_price=Decimal("1200.00")),
        ],
        contingency_rate=Decimal("0.05"),
        tax_rate=Decimal("0.10"),
        service_fee_rate=Decimal("0.10"),
    )

    result = QuotationService().calculate(request)

    assert result.vendor_subtotal == Decimal("4700.00")
    assert result.contingency_amount == Decimal("235.00")
    assert result.tax_amount == Decimal("493.50")
    assert result.estimated_event_cost == Decimal("5428.50")
    assert result.service_fee == Decimal("542.85")
    assert result.total_quotation == Decimal("5971.35")
    assert result.within_budget is True
    assert result.budget_difference == Decimal("4028.65")


def test_rejects_missing_vendor_costs() -> None:
    request = QuotationRequest(
        event_id="EVT-001",
        customer_budget=Decimal("10000.00"),
        vendor_costs=[],
    )

    with pytest.raises(MissingCostDataError):
        QuotationService().calculate(request)

