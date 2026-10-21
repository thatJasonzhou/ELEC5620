"""Procurement mock quote to Financial Budget Check V1 integration."""
from examples.budget_check_example import run_budget_check
from examples.budget_check_example import check_budget
from pathlib import Path
import pytest
from src.services.vendor_booking_service import VendorBookingService, MockVendorBookingService


@pytest.mark.parametrize("gate", ["ready", "approval", "deposit", "fingerprint", "over-budget"])
def test_financial_to_procurement_handoff(gate):
    root = Path(__file__).resolve().parents[2]
    # Use the actual Procurement quotation path and its returned identity.
    from src.agents.vendor_procurement_manager import VendorProcurementManagerAgent
    from src.services.vendor_procurement_service import VendorProcurementService
    from src.services.vendor_quotation_service import MockVendorQuotationService
    from src.llm import MockLLMClient
    procurement = VendorProcurementManagerAgent(MockLLMClient(),
        VendorProcurementService.from_json_file(root / "data/vendor_catalog.json"),
        MockVendorQuotationService.from_json_file(root / "data/mock_vendor_quotations.json"))
    quotes = procurement.request_quotations(dict(event_id="EV001", proposal_id="P1",
        service_type="catering", event_date="2026-12-05", guest_count=120,
        location="Melbourne"))["data"]["quotations"]
    financial = check_budget(quotes, 1 if gate == "over-budget" else 3000000)
    budget = {**financial["data"], "deposit_due_cents": 555000}
    link = {name: budget[name] for name in ("event_id", "proposal_id", "quotation_fingerprint")}
    approval = {**link, "approved": gate != "approval",
                "approved_quotation_ids": [q["quotation_id"] for q in quotes]}
    deposit = {**link, "payment_id": "P1", "amount_cents": 555000,
               "status": "pending" if gate == "deposit" else "paid", "mock": True}
    if gate == "fingerprint":
        budget["quotation_fingerprint"] = "OLD"
    supplier = MockVendorBookingService.from_json_file(root / "data/mock_vendor_bookings.json")
    booking = VendorBookingService(supplier)
    result = booking.confirm_bookings(dict(event_id="EV001", proposal_id="P1", quotations=quotes,
        budget=budget, approval=approval, deposit=deposit))
    assert result["status"] == ("success" if gate == "ready" else "blocked")
    assert len(supplier.calls) == (1 if gate == "ready" else 0)


def test_procurement_financial_flow():
    within, over = run_budget_check()
    assert within["data"]["budget_valid"] is True
    assert within["data"]["vendor_total_cents"] == 1850000
    assert within["data"]["estimated_total_cents"] == 2220000
    assert within["data"]["tax_amount_cents"] == 0
    assert within["data"]["quotation_fingerprint"] == over["data"]["quotation_fingerprint"]
    assert over["status"] == "blocked" and over["data"]["over_budget_cents"] == 1
