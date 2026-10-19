"""Offline KAN-19 quotation Agent demo; no model, network or booking."""
from pathlib import Path
import json

from src.agents.vendor_procurement_manager import VendorProcurementManagerAgent
from src.llm import MockLLMClient
from src.services.vendor_procurement_service import VendorProcurementService
from src.services.vendor_quotation_service import MockVendorQuotationService

ROOT = Path(__file__).resolve().parents[1]


def main():
    llm = MockLLMClient()
    llm.set_exception(AssertionError("quotation enquiries must not call an LLM"))
    agent = VendorProcurementManagerAgent(
        llm,
        VendorProcurementService.from_json_file(ROOT / "data/vendor_catalog.json"),
        MockVendorQuotationService.from_json_file(ROOT / "data/mock_vendor_quotations.json"),
    )
    request = {"event_id": "EV001", "proposal_id": "P-001", "service_type": "catering",
               "event_date": "2026-12-05", "guest_count": 120, "location": "Melbourne"}
    print("MOCK ONLY: simulated supplier confirmations, no payment or booking.")
    scenarios = [
        ("Accepted + pending", request),
        ("Supplier rejection", {**request, "service_type": "photography", "location": "Sydney", "guest_count": 80}),
        ("No configured reply", {**request, "guest_count": 80}),
        ("Missing proposal", {k: v for k, v in request.items() if k != "proposal_id"}),
    ]
    for title, item in scenarios:
        print("\n" + title)
        print(json.dumps(agent.request_quotations(item), indent=2))
    assert not llm.calls


if __name__ == "__main__":
    main()
