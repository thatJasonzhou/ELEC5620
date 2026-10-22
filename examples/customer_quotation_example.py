"""Offline Procurement -> FIN-01 -> KAN-25 customer review demo."""
import json

from examples.budget_check_example import UnusedPayments
from src.agents.financial_manager import FinancialManagerAgent
from src.llm import MockLLMClient


def generate_customer_quotation():
    # Obtain the actual Procurement snapshots via the existing offline demo.
    from pathlib import Path
    from src.agents.vendor_procurement_manager import VendorProcurementManagerAgent
    from src.services.vendor_procurement_service import VendorProcurementService
    from src.services.vendor_quotation_service import MockVendorQuotationService

    root = Path(__file__).resolve().parents[1]
    llm = MockLLMClient()
    llm.set_exception(AssertionError("Quotation demo must not call LLM"))
    procurement = VendorProcurementManagerAgent(llm,
        VendorProcurementService.from_json_file(root / "data/vendor_catalog.json"),
        MockVendorQuotationService.from_json_file(root / "data/mock_vendor_quotations.json"))
    quotes = procurement.request_quotations(dict(event_id="EV001", proposal_id="P1",
        service_type="catering", event_date="2026-12-05", guest_count=120,
        location="Melbourne"))["data"]["quotations"]
    worker = FinancialManagerAgent(llm, UnusedPayments())
    request = dict(event_id="EV001", action="prepare_budget",
        event=dict(event_id="EV001", event_date="2026-12-05", guest_count=120,
                   budget_limit_cents=3000000),
        proposal=dict(event_id="EV001", proposal_id="P1", required_services=["catering"]),
        quotations=quotes, selected_quotation_ids=[q["quotation_id"] for q in quotes])
    budget = worker.handle(request)
    assert budget["status"] == "success"
    result = worker.handle({**request, "action": "generate_customer_quotation", "budget": budget["data"]})
    assert result["status"] == "success"
    assert not llm.calls
    return request, budget["data"], result


if __name__ == "__main__":
    print("Customer quotation for review; supplier replies are MOCK; amounts are AUD cents.")
    print(json.dumps(generate_customer_quotation()[2], indent=2))
