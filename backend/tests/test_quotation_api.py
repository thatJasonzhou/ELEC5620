from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.api.routes.quotations import calculate_quotation
from app.schemas.quotation import QuotationRequest, VendorCostItem


def test_quotation_endpoint_returns_agent_activity() -> None:
    request = QuotationRequest(
        event_id="EVT-001",
        customer_budget=Decimal("10000.00"),
        currency="AUD",
        vendor_costs=[
            VendorCostItem(description="Catering", quantity=1, unit_price=Decimal("3500.00")),
            VendorCostItem(description="Lighting", quantity=1, unit_price=Decimal("1200.00")),
        ],
    )

    response = calculate_quotation(request)

    assert response.total_quotation == Decimal("5971.35")
    assert response.within_budget is True
    assert response.activity.agent == "FinancialManagerAgent"


def test_quotation_endpoint_reports_missing_cost_data() -> None:
    request = QuotationRequest(
        event_id="EVT-001",
        customer_budget=Decimal("10000.00"),
        vendor_costs=[],
    )

    with pytest.raises(HTTPException) as error:
        calculate_quotation(request)

    assert error.value.status_code == 400
    assert error.value.detail["code"] == "MISSING_COST_DATA"

