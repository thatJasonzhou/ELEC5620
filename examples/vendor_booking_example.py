"""MOCK end-to-end quotation to booking demo; no real approval/payment/network."""
from copy import deepcopy
from pathlib import Path
import json

from src.agents.vendor_procurement_manager import VendorProcurementManagerAgent
from src.llm import MockLLMClient
from src.services.vendor_procurement_service import VendorProcurementService
from src.services.vendor_quotation_service import MockVendorQuotationService
from src.services.vendor_booking_service import MockVendorBookingService, VendorBookingService, quotation_fingerprint

ROOT = Path(__file__).resolve().parents[1]


def main():
    llm = MockLLMClient()
    llm.set_exception(AssertionError("no LLM for mock booking"))
    supplier = MockVendorBookingService.from_json_file(ROOT / "data/mock_vendor_bookings.json")
    service = VendorBookingService(supplier)
    vendors = VendorProcurementService.from_json_file(ROOT / "data/vendor_catalog.json")
    quotation_service = MockVendorQuotationService.from_json_file(ROOT / "data/mock_vendor_quotations.json")
    agent = VendorProcurementManagerAgent(llm,
        vendors, quotation_service, service)
    enquiry = {"event_id": "EV001", "proposal_id": "P1", "service_type": "catering",
               "event_date": "2026-12-05", "guest_count": 120, "location": "Melbourne"}
    quotations = agent.request_quotations(enquiry)["data"]["quotations"]
    linkage = {"event_id": "EV001", "proposal_id": "P1", "quotation_fingerprint": quotation_fingerprint(quotations)}
    item = {"event_id": "EV001", "proposal_id": "P1", "quotations": quotations,
            "approval": {**linkage, "approved": True, "approved_quotation_ids": [q["quotation_id"] for q in quotations]},
            "budget": {**linkage, "within_budget": True, "deposit_due_cents": 555000},
            "deposit": {**linkage, "payment_id": "MOCK-PAY1", "amount_cents": 555000, "status": "paid", "mock": True}}
    print("MOCK ONLY: approval, Financial review, payment and supplier replies are fixtures.")
    print("Memory-only booking store; restarts lose repeat protection. No charge/refund is made.")
    unpaid = deepcopy(item)
    unpaid["deposit"]["status"] = "pending"
    print("\nUnpaid deposit:")
    print(json.dumps(agent.confirm_bookings(unpaid), indent=2))
    print("Supplier calls before payment gate passed:", len(supplier.calls))
    print("\nConfirmed booking:")
    print(json.dumps(agent.confirm_bookings(item), indent=2))
    again = agent.confirm_bookings(item)
    print("\nRepeat request status:", again["status"], "supplier calls:", len(supplier.calls))
    assert len(supplier.calls) == 1 and not llm.calls
    preset = json.loads((ROOT / "data/mock_vendor_bookings.json").read_text(encoding="utf-8"))["scenarios"][0]
    for status in ("rejected", "pending"):
        final_reply = {**preset, "status": status, "supplier_confirmation_id": None,
                       "reason": "MOCK: final supplier reply is " + status}
        failed_service = VendorBookingService(MockVendorBookingService([final_reply]))
        failed_agent = VendorProcurementManagerAgent(llm, vendors, quotation_service, failed_service)
        result = failed_agent.confirm_bookings(item)
        print("\nPaid, supplier", status, ":", result["status"],
              "bookings:", len(result["data"]["bookings"]),
              "payment:", result["data"]["customer_payment"]["status"],
              "requires_attention:", result["data"]["requires_attention"])
        assert result["status"] == "blocked" and not result["data"]["bookings"]
        assert result["data"]["customer_payment"]["status"] == "paid"


if __name__ == "__main__":
    main()
