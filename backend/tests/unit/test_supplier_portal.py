from pathlib import Path

import pytest

from src.services.supplier_portal_service import SupplierPortalService
from src.services.vendor_procurement_service import VendorProcurementService


DATA = Path(__file__).resolve().parents[2] / "data"


def make_service(tmp_path: Path) -> SupplierPortalService:
    catalog = VendorProcurementService.from_json_file(DATA / "vendor_catalog.json")
    return SupplierPortalService(tmp_path / "supplier.sqlite3", catalog)


def request_record(**updates):
    item = {
        "event_id": "EV-PORTAL",
        "proposal_id": "P-PORTAL",
        "vendor_id": "V-CAT-001",
        "vendor_name": "Golden Whisker Catering",
        "offering_id": "V-CAT-001-O2",
        "service_type": "catering",
        "event_summary": "Birthday in Sydney",
        "event_type": "Birthday",
        "event_date": "2026-12-05",
        "start_time": "15:00",
        "end_time": "18:00",
        "location": "Sydney",
        "guest_count": 50,
        "service_budget_cents": 1_500_000,
        "catalogue_estimate_cents": 980_000,
    }
    item.update(updates)
    return item


def test_supplier_can_receive_and_quote_an_rfq(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    created = service.create_quote_requests([request_record()])

    assert created[0]["status"] == "pending"
    assert created[0]["guest_count"] == 50
    answered = service.respond_to_quote_request(
        created[0]["request_id"],
        available=True,
        quoted_total_cents=1_025_000,
        message="Includes staff and delivery.",
    )

    assert answered["status"] == "quoted"
    assert answered["response"]["status"] == "accepted"
    assert answered["response"]["quoted_total_cents"] == 1_025_000
    assert answered["response"]["source"] == "vendor_portal"


def test_supplier_can_decline_without_a_price(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    request = service.create_quote_requests([request_record()])[0]

    answered = service.respond_to_quote_request(
        request["request_id"], available=False, quoted_total_cents=None
    )

    assert answered["status"] == "declined"
    assert answered["response"]["available"] is False
    assert answered["response"]["quoted_total_cents"] is None


def test_supplier_cannot_answer_the_same_request_twice(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    request = service.create_quote_requests([request_record()])[0]
    service.respond_to_quote_request(
        request["request_id"], available=True, quoted_total_cents=900_000
    )

    with pytest.raises(ValueError, match="already been answered"):
        service.respond_to_quote_request(
            request["request_id"], available=True, quoted_total_cents=850_000
        )


def test_vendor_list_comes_from_the_catalogue(tmp_path: Path) -> None:
    service = make_service(tmp_path)

    vendors = service.list_vendors()

    assert len(vendors) == 51
    assert {item["vendor_id"] for item in vendors}.issuperset(
        {"V-CAT-001", "V-PHOTO-001", "V-VENUE-001", "V-STAFF-005"}
    )
    assert {
        service_type
        for item in vendors
        for service_type in item["service_types"]
    } == {
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


def test_reset_clears_all_supplier_cases(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.create_quote_requests([request_record()])

    assert service.clear_all_quote_requests() == 1
    assert service.list_quote_requests() == []
    assert service.clear_all_quote_requests() == 0
