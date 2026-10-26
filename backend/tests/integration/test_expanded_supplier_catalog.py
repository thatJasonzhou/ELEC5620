"""Coverage checks for the merged ten-category supplier demo data."""
from pathlib import Path

import pytest

from src.services.vendor_booking_service import MockVendorBookingService
from src.services.vendor_procurement_service import VendorProcurementService
from src.services.vendor_quotation_service import MockVendorQuotationService


DATA = Path(__file__).resolve().parents[2] / "data"
SERVICE_TYPES = {
    "catering",
    "decoration",
    "entertainment",
    "event_staff",
    "lighting",
    "photography",
    "sound",
    "transport",
    "venue",
    "videography",
}


@pytest.mark.parametrize("city", ["Sydney", "Melbourne"])
@pytest.mark.parametrize("event_date", ["2026-12-16", "2026-12-17"])
@pytest.mark.parametrize("guest_count", [50, 80])
def test_each_expanded_supplier_has_an_explicit_reply_and_booking(
    city: str, event_date: str, guest_count: int
) -> None:
    catalogue = VendorProcurementService.from_json_file(
        DATA / "vendor_catalog.json"
    )
    quotations = MockVendorQuotationService.from_json_file(
        DATA / "mock_vendor_quotations.json"
    )
    bookings = MockVendorBookingService.from_json_file(
        DATA / "mock_vendor_bookings.json"
    )

    for service_type in SERVICE_TYPES:
        candidates = catalogue.filter_vendors(
            service_type=service_type,
            date=event_date,
            guest_count=guest_count,
            location=city,
        )
        assert len(candidates) >= 5
        for candidate in candidates:
            reply = quotations.request_quotation(
                event_id="EV-DATA-COVERAGE",
                proposal_id="P-DATA-COVERAGE",
                vendor_id=candidate["vendor_id"],
                offering_id=candidate["offering_id"],
                event_date=event_date,
                guest_count=guest_count,
            )
            assert reply["status"] in {"accepted", "rejected"}
            if reply["status"] == "accepted":
                final = bookings.request_booking(
                    {**reply, "service_type": service_type}
                )
                assert final["status"] == "confirmed"
                assert final["mock"] is True
