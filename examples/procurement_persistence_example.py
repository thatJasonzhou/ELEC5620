"""Offline SQLite restart demonstration; all supplier/payment data are MOCK."""
from pathlib import Path
from tempfile import TemporaryDirectory

from examples.budget_check_example import check_budget
from src.agents.vendor_procurement_manager import VendorProcurementManagerAgent
from src.llm import MockLLMClient
from src.services.procurement_record_service import ProcurementRecordService
from src.services.vendor_booking_service import (
    MockVendorBookingService, VendorBookingService, quotation_fingerprint,
)
from src.services.vendor_procurement_service import VendorProcurementService
from src.services.vendor_quotation_service import MockVendorQuotationService

ROOT = Path(__file__).resolve().parents[1]


def main():
    print("MOCK ONLY: no live API, payment or refund. Temporary SQLite demonstration.")
    with TemporaryDirectory(prefix="procurement-demo-") as directory:
        path = Path(directory) / "procurement.sqlite3"
        records = ProcurementRecordService(path)
        supplier = MockVendorBookingService.from_json_file(ROOT / "data/mock_vendor_bookings.json")
        bookings = VendorBookingService(supplier, record_service=records)
        llm = MockLLMClient()
        llm.set_exception(AssertionError("SQLite example must not call an LLM"))
        agent = VendorProcurementManagerAgent(llm,
            VendorProcurementService.from_json_file(ROOT / "data/vendor_catalog.json"),
            MockVendorQuotationService.from_json_file(ROOT / "data/mock_vendor_quotations.json"),
            bookings, record_service=records)
        enquiry = {"event_id": "EV001", "proposal_id": "P1", "service_type": "catering",
                   "event_date": "2026-12-05", "guest_count": 120, "location": "Melbourne"}
        result = agent.request_quotations(enquiry)
        assert result["status"] == "success", result["message"]
        quotes = records.get_quotations("EV001", "P1")
        link = {"event_id": "EV001", "proposal_id": "P1", "quotation_fingerprint": quotation_fingerprint(quotes)}
        request = {"event_id": "EV001", "proposal_id": "P1", "quotations": quotes,
            "approval": {**link, "approved": True, "approved_quotation_ids": [q["quotation_id"] for q in quotes]},
            "budget": {**check_budget(quotes, 100000000)["data"], "deposit_due_cents": 555000},
            "deposit": {**link, "payment_id": "MOCK-PAY1", "amount_cents": 555000, "status": "paid", "mock": True}}
        first = agent.confirm_bookings(request)
        assert first["status"] == "success", first["message"]
        print("Saved quotations:", len(quotes), "confirmed bookings:", len(first["data"]["bookings"]))
        print("Initial supplier calls:", len(supplier.calls))

        # All new dependencies; only the SQLite file carries the saved records.
        reopened = ProcurementRecordService(path)
        new_supplier = MockVendorBookingService([])
        restarted = VendorBookingService(new_supplier, record_service=reopened)
        again = restarted.confirm_bookings(request)
        assert again["status"] == "success", again["message"]
        assert again["data"]["bookings"] == first["data"]["bookings"]
        assert reopened.get_quotations("EV001", "P1") == quotes
        assert not new_supplier.calls and not llm.calls
        print("After reload: same booking IDs, supplier calls:", len(new_supplier.calls))
        print("Operations scoped read:", len(restarted.get_bookings("EV001", "P1")))
        print("Another event scoped read:", len(restarted.get_bookings("OTHER", "P1")))
    print("Temporary database removed. Existing approval/payment gates still apply.")


if __name__ == "__main__":
    main()
