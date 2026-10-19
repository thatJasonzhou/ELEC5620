"""Offline booking gates, final confirmations and in-memory repeat safety."""
from copy import deepcopy
from pathlib import Path

import pytest

from src.agents.vendor_procurement_manager import VendorProcurementManagerAgent
from src.llm import MockLLMClient
from src.services.vendor_procurement_service import VendorProcurementService
from src.services.vendor_quotation_service import MockVendorQuotationService
from src.services.vendor_booking_service import MockVendorBookingService, VendorBookingService, quotation_fingerprint

ROOT = Path(__file__).resolve().parents[2]


def quote(qid="Q1", vendor="V-CAT-001", offering="V-CAT-001-O1", cents=1850000):
    return {"event_id": "EV001", "proposal_id": "P1", "quotation_id": qid, "vendor_id": vendor,
            "offering_id": offering, "service_type": "catering", "event_date": "2026-12-05",
            "guest_count": 120, "quoted_total_cents": cents, "available": True, "mock": True}


def scenario(q=None, status="confirmed", confirmation="CONF1"):
    q = q or quote()
    return {"scenario_id": "MOCK-B-" + q["quotation_id"],
            **{k: q[k] for k in ("vendor_id", "offering_id", "event_date", "guest_count")},
            "status": status, "reason": "MOCK final supplier reply: " + status,
            "supplier_confirmation_id": confirmation if status == "confirmed" else None}


def request(quotations=None):
    quotations = quotations if quotations is not None else [quote()]
    reference = {"event_id": "EV001", "proposal_id": "P1", "quotation_fingerprint": quotation_fingerprint(quotations)}
    return {"event_id": "EV001", "proposal_id": "P1", "quotations": quotations,
            "approval": {**reference, "approved": True, "approved_quotation_ids": [q["quotation_id"] for q in quotations]},
            "budget": {**reference, "within_budget": True, "deposit_due_cents": 555000},
            "deposit": {**reference, "payment_id": "PAY1", "amount_cents": 555000, "status": "paid", "mock": True}}


def service(status="confirmed"):
    supplier = MockVendorBookingService([scenario(status=status)])
    return VendorBookingService(supplier), supplier


def test_confirmation_creates_booking_and_preserves_payment():
    booking, supplier = service()
    item = request()
    saved = deepcopy(item)
    result = booking.confirm_bookings(item)
    assert result["status"] == "success" and len(supplier.calls) == 1
    record, = result["data"]["bookings"]
    assert record["status"] == "Confirmed" and record["mock"] is True
    assert record["event_id"] == "EV001" and record["quotation_id"] == "Q1"
    assert record["supplier_confirmation_id"] == "CONF1" and record["booking_id"].startswith("MB-")
    assert result["data"]["customer_payment"] == item["deposit"]
    assert not result["data"]["requires_attention"] and item == saved


def test_identical_retries_reuse_booking_without_supplier_call():
    booking, supplier = service()
    first = booking.confirm_bookings(request())
    second = booking.confirm_bookings(request())
    assert first["data"]["bookings"] == second["data"]["bookings"]
    assert second["status"] == "success" and len(supplier.calls) == 1


@pytest.mark.parametrize("field,value", [
    ("approved", False), ("within_budget", False), ("status", "pending"),
    ("status", "failed"), ("amount_cents", 0), ("amount_cents", 554999),
    ("approved_quotation_ids", ["OTHER"]),
    ("approved_quotation_ids", []),
])
def test_unmet_gates_never_contact_supplier(field, value):
    booking, supplier = service()
    item = request()
    record = item["approval"] if field in ("approved", "approved_quotation_ids") else (
        item["budget"] if field == "within_budget" else item["deposit"])
    record[field] = value
    result = booking.confirm_bookings(item)
    assert result["status"] == "blocked" and result["data"]["bookings"] == []
    assert supplier.calls == [] and booking.bookings == []


@pytest.mark.parametrize("record", ["approval", "budget", "deposit"])
@pytest.mark.parametrize("field,value", [("event_id", "OTHER"), ("proposal_id", "OTHER"),
                                        ("quotation_fingerprint", "OLD")])
def test_mismatched_or_old_records_block(record, field, value):
    booking, supplier = service()
    item = request()
    item[record][field] = value
    assert booking.confirm_bookings(item)["status"] == "blocked"
    assert supplier.calls == []


def test_price_revision_requires_new_records():
    booking, supplier = service()
    item = request()
    item["quotations"][0]["quoted_total_cents"] += 1
    assert booking.confirm_bookings(item)["status"] == "blocked" and not supplier.calls


@pytest.mark.parametrize("status", ["rejected", "pending"])
def test_unconfirmed_supplier_reply_does_not_create_booking(status):
    booking, supplier = service(status)
    result = booking.confirm_bookings(request())
    assert result["status"] == "blocked" and booking.bookings == []
    assert result["data"]["requires_attention"] is True
    assert result["data"]["customer_payment"]["status"] == "paid"
    assert result["data"]["supplier_replies"][0]["status"] == status


def test_missing_final_reply_is_not_acceptance():
    supplier = MockVendorBookingService([])
    booking = VendorBookingService(supplier)
    result = booking.confirm_bookings(request())
    assert result["status"] == "blocked" and not result["data"]["bookings"]
    assert result["data"]["supplier_replies"][0]["status"] == "unconfigured"


@pytest.mark.parametrize("override", [
    {"mock": False}, {"status": "accepted"}, {"status": []}, {"quotation_id": "OTHER"},
    {"event_id": "OTHER"}, {"proposal_id": "OTHER"}, {"vendor_id": "OTHER"},
    {"offering_id": "OTHER"}, {"event_date": "2026-12-06"}, {"guest_count": True},
    {"quoted_total_cents": True}, {"quoted_total_cents": 1},
    {"supplier_confirmation_id": ""}, {"scenario_id": ""}, {"reason": " "},
])
def test_malformed_supplier_reply_errors(override, monkeypatch):
    booking, supplier = service()
    original = supplier.request_booking
    monkeypatch.setattr(supplier, "request_booking", lambda q: {**original(q), **override})
    result = booking.confirm_bookings(request())
    assert result["status"] == "error" and not booking.bookings
    assert result["data"]["customer_payment"]["status"] == "paid"


def test_supplier_failure_is_error(monkeypatch):
    booking, supplier = service()
    def fail(q):
        raise OSError("simulated transport fault")
    monkeypatch.setattr(supplier, "request_booking", fail)
    assert booking.confirm_bookings(request())["status"] == "error"
    assert not booking.bookings


def test_partial_confirmation_is_retained_and_reused():
    q2 = quote("Q2", "V-CAT-002", "V-CAT-002-O1", 620000)
    supplier = MockVendorBookingService([scenario(), scenario(q2, "rejected")])
    booking = VendorBookingService(supplier)
    item = request([quote(), q2])
    first = booking.confirm_bookings(item)
    assert first["status"] == "blocked" and len(first["data"]["bookings"]) == 1
    assert first["data"]["bookings"][0]["quotation_id"] == "Q1"
    second = booking.confirm_bookings(item)
    assert second["data"]["bookings"] == first["data"]["bookings"]
    assert [c["quotation_id"] for c in supplier.calls].count("Q1") == 1


def test_changed_confirmed_quote_is_not_rebooked():
    booking, supplier = service()
    assert booking.confirm_bookings(request())["status"] == "success"
    changed = quote(cents=1850001)
    result = booking.confirm_bookings(request([changed]))
    assert result["status"] == "blocked" and len(supplier.calls) == 1
    assert booking.bookings[0]["quoted_total_cents"] == 1850000


@pytest.mark.parametrize("field", ["event_id", "proposal_id", "quotations", "approval", "budget", "deposit"])
def test_missing_input_needs_input(field):
    booking, supplier = service()
    item = request()
    del item[field]
    result = booking.confirm_bookings(item)
    assert result["status"] == "needs_input" and supplier.calls == []
    if field == "event_id":
        assert result["event_id"] is None


@pytest.mark.parametrize("record,field,value", [
    ("approval", "approved", 1), ("budget", "within_budget", "yes"),
    ("budget", "deposit_due_cents", 0), ("budget", "deposit_due_cents", True),
    ("deposit", "amount_cents", True), ("deposit", "mock", False),
    ("deposit", "payment_id", ""), ("deposit", "status", "unknown"),
])
def test_invalid_record_fields_need_input(record, field, value):
    booking, supplier = service()
    item = request()
    item[record][field] = value
    assert booking.confirm_bookings(item)["status"] == "needs_input" and not supplier.calls


def test_fingerprint_is_order_independent_but_binds_amount():
    q1, q2 = quote(), quote("Q2", "V-CAT-002", "V-CAT-002-O1", 620000)
    assert quotation_fingerprint([q1, q2]) == quotation_fingerprint([q2, q1])
    assert quotation_fingerprint([q1]) != quotation_fingerprint([{**q1, "quoted_total_cents": 1850001}])
    with pytest.raises(ValueError, match="duplicate"):
        quotation_fingerprint([q1, dict(q1)])
    with pytest.raises(ValueError, match="duplicate selected"):
        quotation_fingerprint([q1, {**q1, "quotation_id": "DUP-OFFER"}])


def test_public_views_do_not_mutate_service_state():
    booking, supplier = service()
    result = booking.confirm_bookings(request())
    result["data"]["bookings"][0]["status"] = "Cancelled"
    snapshot = booking.bookings
    snapshot[0]["status"] = "Cancelled"
    assert booking.bookings[0]["status"] == "Confirmed"


def test_agent_exposes_separate_booking_entry_and_preserves_quotation_entry():
    vendors = VendorProcurementService.from_json_file(ROOT / "data/vendor_catalog.json")
    quotation_service = MockVendorQuotationService.from_json_file(ROOT / "data/mock_vendor_quotations.json")
    supplier = MockVendorBookingService.from_json_file(ROOT / "data/mock_vendor_bookings.json")
    booking = VendorBookingService(supplier)
    llm = MockLLMClient()
    llm.set_exception(AssertionError("no LLM for booking"))
    agent = VendorProcurementManagerAgent(llm, vendors, quotation_service, booking)
    enquiry = {"event_id": "EV001", "proposal_id": "P1", "service_type": "catering",
               "event_date": "2026-12-05", "guest_count": 120, "location": "Melbourne"}
    quotations = agent.request_quotations(enquiry)["data"]["quotations"]
    result = agent.confirm_bookings(request(quotations))
    assert result["agent"] == "procurement" and result["status"] == "success"
    assert result["data"]["bookings"][0]["quotation_id"] == quotations[0]["quotation_id"]
    assert not llm.calls
    assert VendorProcurementManagerAgent(llm, vendors).confirm_bookings(request())["status"] == "error"


@pytest.mark.parametrize("override", [{"guest_count": True}, {"status": "maybe"},
                                       {"status": "confirmed", "supplier_confirmation_id": ""}])
def test_invalid_scenario_is_rejected(override):
    with pytest.raises(ValueError):
        MockVendorBookingService([{**scenario(), **override}])
