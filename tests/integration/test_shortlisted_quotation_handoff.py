"""Real Procurement -> Financial -> gated mock booking handoff for KAN-36."""
from examples.budget_check_example import check_budget
from examples.shortlisted_quotation_example import run_shortlist_demo
from src.services.procurement_record_service import ProcurementRecordService
from src.services.vendor_booking_service import (
    MockVendorBookingService, VendorBookingService, quotation_fingerprint,
)


def test_selected_quote_handoff_persistence_and_existing_booking_gates(tmp_path):
    records = ProcurementRecordService(tmp_path / "procurement.sqlite3")
    _, compared = run_shortlist_demo(record_service=records)
    selected = compared["data"]["selected_quotations"]
    q, = selected
    assert q["vendor_id"] == "B"
    budget_result = check_budget(selected, 150000)
    assert budget_result["status"] == "success"
    budget = {**budget_result["data"], "deposit_due_cents": 28500}
    assert budget["vendor_total_cents"] == 95000
    assert budget["estimated_total_cents"] == 114000
    assert budget["quotation_fingerprint"] == quotation_fingerprint(selected)
    # All accepted alternatives are saved, but not counted as simultaneous purchases.
    stored = ProcurementRecordService(records.database_path).get_quotations(q["event_id"], q["proposal_id"])
    assert {item["quoted_total_cents"] for item in stored} == {95000, 130000}
    assert q in stored
    supplier = MockVendorBookingService([{
        "scenario_id": "MOCK-SHORTLIST-BOOKING", "vendor_id": q["vendor_id"],
        "offering_id": q["offering_id"], "event_date": q["event_date"],
        "guest_count": q["guest_count"], "status": "confirmed",
        "reason": "MOCK final supplier confirmation", "supplier_confirmation_id": "MOCK-CONF-B",
    }])
    booking = VendorBookingService(supplier, record_service=records)
    link = {k: budget[k] for k in ("event_id", "proposal_id", "quotation_fingerprint")}
    approval = {**link, "approved": False, "approved_quotation_ids": [q["quotation_id"]]}
    deposit = {**link, "payment_id": "MOCK-DEPOSIT", "status": "pending",
               "amount_cents": 28500, "mock": True}
    request = {"event_id": q["event_id"], "proposal_id": q["proposal_id"],
               "quotations": selected, "budget": budget, "approval": approval, "deposit": deposit}
    assert booking.confirm_bookings(request)["status"] == "blocked"
    assert supplier.calls == []
    approval["approved"] = True
    assert booking.confirm_bookings(request)["status"] == "blocked"
    assert supplier.calls == []
    deposit["status"] = "paid"
    result = booking.confirm_bookings(request)
    assert result["status"] == "success" and len(supplier.calls) == 1
    restarted = VendorBookingService(supplier, record_service=ProcurementRecordService(records.database_path))
    assert restarted.confirm_bookings(request)["status"] == "success"
    assert len(supplier.calls) == 1


def test_final_financial_total_can_still_exceed_event_budget():
    _, compared = run_shortlist_demo()
    selected = compared["data"]["selected_quotations"]
    assert selected[0]["quoted_total_cents"] == 95000  # Below the 100000 service target.
    result = check_budget(selected, 100000)
    assert result["status"] == "blocked"
    assert result["data"]["estimated_total_cents"] == 114000
    assert result["data"]["over_budget_cents"] == 14000


def test_five_service_selected_quotes_flow_through_existing_financial_and_booking(tmp_path):
    from examples.event_procurement_example import run_event_demo
    records = ProcurementRecordService(tmp_path / "five-services.sqlite3")
    result, enquiries = run_event_demo(record_service=records)
    data = result["data"]
    quotes = data["quotations"]
    assert len(enquiries.calls) == 15
    assert len(ProcurementRecordService(records.database_path).get_quotations("EV-FIVE", "P-FIVE")) == 10
    checked = check_budget(quotes, 1000000)
    assert checked["status"] == "success"
    assert checked["data"]["vendor_total_cents"] == 760000
    assert checked["data"]["estimated_total_cents"] == 912000
    budget = {**checked["data"], "deposit_due_cents": 273600}
    link = {k: budget[k] for k in ("event_id", "proposal_id", "quotation_fingerprint")}
    approval = {**link, "approved": False, "approved_quotation_ids": data["selected_quotation_ids"]}
    deposit = {**link, "payment_id": "MOCK-FIVE-DEPOSIT", "status": "pending",
               "amount_cents": 273600, "mock": True}
    supplier = MockVendorBookingService([{
        "scenario_id": "MOCK-BOOK-" + q["service_type"],
        "vendor_id": q["vendor_id"], "offering_id": q["offering_id"],
        "event_date": q["event_date"], "guest_count": q["guest_count"],
        "status": "confirmed", "reason": "MOCK final booking",
        "supplier_confirmation_id": "CONF-" + q["service_type"],
    } for q in quotes])
    booking = VendorBookingService(supplier, record_service=records)
    request = {**{k: link[k] for k in ("event_id", "proposal_id")},
               "quotations": quotes, "budget": budget, "approval": approval, "deposit": deposit}
    assert booking.confirm_bookings(request)["status"] == "blocked" and not supplier.calls
    approval["approved"] = True
    assert booking.confirm_bookings(request)["status"] == "blocked" and not supplier.calls
    deposit["status"] = "paid"
    confirmed = booking.confirm_bookings(request)
    assert confirmed["status"] == "success" and len(confirmed["data"]["bookings"]) == 5
    assert len(supplier.calls) == 5
    reloaded = VendorBookingService(supplier, record_service=ProcurementRecordService(records.database_path))
    assert reloaded.confirm_bookings(request)["status"] == "success" and len(supplier.calls) == 5
