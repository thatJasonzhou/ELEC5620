"""Shared demo data must support arbitrary top-three shortlists, not only one fixed model."""
from collections import Counter
from pathlib import Path

import pytest

from examples.event_procurement_example import SERVICE_TYPES
from examples.shared_catalog_procurement_example import build_agent, catalog_service_types, event_request
from src.services.vendor_booking_service import MockVendorBookingService
from src.services.vendor_procurement_service import VendorProcurementService
from src.services.vendor_quotation_service import MockVendorQuotationService

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("city", ["Sydney", "Melbourne"])
@pytest.mark.parametrize("date", ["2026-12-16", "2026-12-17"])
@pytest.mark.parametrize("guests", [50, 80])
def test_every_eligible_supplier_has_explicit_quote_and_final_reply(city, date, guests):
    catalog = VendorProcurementService.from_json_file(ROOT / "data/vendor_catalog.json")
    supplier = MockVendorQuotationService.from_json_file(ROOT / "data/mock_vendor_quotations.json")
    booking = MockVendorBookingService.from_json_file(ROOT / "data/mock_vendor_bookings.json")
    for service in catalog_service_types():
        candidates = catalog.filter_vendors(
            service_type=service, date=date, guest_count=guests, location=city)
        assert len({c["vendor_id"] for c in candidates}) >= 5
        for c in candidates:
            reply = supplier.request_quotation(
                event_id="EV-COVERAGE", proposal_id="P-COVERAGE",
                vendor_id=c["vendor_id"], offering_id=c["offering_id"],
                event_date=date, guest_count=guests)
            assert reply["status"] in ("accepted", "rejected")
            if reply["status"] == "accepted":
                final = booking.request_booking({**reply, "service_type": service})
                assert final["status"] == "confirmed"
                assert final["mock"] is True


@pytest.mark.parametrize("city", ["Sydney", "Melbourne"])
@pytest.mark.parametrize("date", ["2026-12-16", "2026-12-17"])
@pytest.mark.parametrize("guests", [50, 80])
@pytest.mark.parametrize("services", [
    SERVICE_TYPES,
    ("videography", "lighting", "entertainment", "transport", "event_staff"),
    ("photography", "catering", "lighting", "transport", "event_staff"),
    ("videography", "venue", "entertainment"),
])
def test_full_shared_catalog_procurement_has_complete_selected_only_handoff(city, date, guests, services):
    result = build_agent().procure_services(event_request(city=city, date=date, guests=guests, services=services))
    assert result["status"] == "success", result["message"]
    data = result["data"]
    assert data["selection_complete"] is True
    assert len(data["quotations"]) == len(data["selected_quotation_ids"]) == len(services)
    assert Counter(q["service_type"] for q in data["quotations"]) == Counter(services)
    assert sum(len(r["enquiries"]) for r in data["service_rounds"]) == 3 * len(services)
    assert {q["quotation_id"] for q in data["quotations"]} == set(data["selected_quotation_ids"])
    for r in data["service_rounds"]:
        shortlisted = {e["candidate"]["vendor_id"] for e in r["enquiries"]}
        assert len(shortlisted) == 3
        assert all(q["vendor_id"] in shortlisted for q in r["quotations"])
        assert r["awaiting_replies"] is False

def test_catalogue_exposes_ten_choices_without_raising_activity_limit():
    types = catalog_service_types()
    assert set(types) == {
        "photography", "catering", "venue", "sound", "decoration",
        "videography", "lighting", "entertainment", "transport", "event_staff",
    }
    agent = build_agent()
    result = agent.procure_services(event_request(services=types))
    assert result["status"] == "needs_input"
    assert not agent.llm.calls
