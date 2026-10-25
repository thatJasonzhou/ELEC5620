"""Offline SQLite durability, isolation, conflict and failure behaviour."""
from copy import deepcopy
from pathlib import Path
import json
import sqlite3
import subprocess
import sys

import pytest

from src.agents.vendor_procurement_manager import VendorProcurementManagerAgent
from src.llm import MockLLMClient
from src.services.procurement_record_service import (
    ProcurementRecordService, ProcurementRecordConflict, ProcurementStorageError,
)
from src.services.vendor_booking_service import (
    MockVendorBookingService, VendorBookingService, quotation_fingerprint,
)
from src.services.vendor_procurement_service import VendorProcurementService
from src.services.vendor_quotation_service import MockVendorQuotationService

ROOT = Path(__file__).resolve().parents[2]
ENQUIRY = {"event_id": "EV001", "proposal_id": "P1", "service_type": "catering",
           "event_date": "2026-12-05", "guest_count": 120, "location": "Melbourne"}


def quote(**changes):
    return {"event_id": "EV001", "proposal_id": "P1", "quotation_id": "Q1",
            "vendor_id": "V-CAT-001", "offering_id": "V-CAT-001-O1", "service_type": "catering",
            "event_date": "2026-12-05", "guest_count": 120, "quoted_total_cents": 1850000,
            "available": True, "mock": True, "scenario_id": "MOCK-Q1",
            "recommendation_reason": "MOCK confirmed price. 素食待确认。", **changes}


def scenario(q=None, confirmation="CONF1", status="confirmed"):
    q = q or quote()
    return {**{k: q[k] for k in ("vendor_id", "offering_id", "event_date")},
            "scenario_id": "MOCK-B-" + q["quotation_id"], "status": status, "reason": "MOCK " + status,
            "supplier_confirmation_id": confirmation if status == "confirmed" else None}


def request(quotes=None):
    quotes = quotes if quotes is not None else [quote()]
    link = {"event_id": quotes[0]["event_id"], "proposal_id": quotes[0]["proposal_id"],
            "quotation_fingerprint": quotation_fingerprint(quotes)}
    return {"event_id": link["event_id"], "proposal_id": link["proposal_id"], "quotations": quotes,
            "approval": {**link, "approved": True, "approved_quotation_ids": [q["quotation_id"] for q in quotes]},
            "budget": {**link, "within_budget": True, "deposit_due_cents": 555000},
            "deposit": {**link, "payment_id": "MOCK-PAY", "amount_cents": 555000, "status": "paid", "mock": True}}


def agent(records):
    llm = MockLLMClient()
    llm.set_exception(AssertionError("no LLM for offline persistence"))
    return VendorProcurementManagerAgent(llm,
        VendorProcurementService.from_json_file(ROOT / "data/vendor_catalog.json"),
        MockVendorQuotationService.from_json_file(ROOT / "data/mock_vendor_quotations.json"),
        record_service=records)


@pytest.fixture
def records(tmp_path):
    return ProcurementRecordService(tmp_path / "records.sqlite3")


def test_agent_saves_only_accepted_quotes_and_reopens(records):
    worker = agent(records)
    result = worker.request_quotations(ENQUIRY)
    assert result["status"] == "success" and not worker.llm.calls
    reopened = ProcurementRecordService(records.database_path)
    assert reopened.get_quotations("EV001", "P1") == result["data"]["quotations"]
    assert len(reopened.get_quotations("EV001", "P1")) == 1
    assert any(r["status"] == "pending" for r in result["data"]["supplier_replies"])


def test_quote_roundtrip_is_lossless_detached_and_idempotent(records):
    item = quote()
    records.save_quotations([item])
    records.save_quotations([deepcopy(item)])
    loaded = records.get_quotations("EV001", "P1")
    assert loaded == [item] and type(loaded[0]["quoted_total_cents"]) is int
    loaded[0]["quoted_total_cents"] = 1
    item["recommendation_reason"] = "changed by caller"
    assert records.get_quotations("EV001", "P1") == [quote()]


@pytest.mark.parametrize("field", ["event_id", "proposal_id"])
def test_scoped_reads_never_mix_events_or_proposals(records, field):
    first, other = quote(), quote(**{field: "OTHER"})
    records.save_quotations([first, other])
    assert records.get_quotations("EV001", "P1") == [first]
    assert records.get_quotations(other["event_id"], other["proposal_id"]) == [other]
    assert records.get_quotations("missing", "missing") == []
    assert records.get_bookings("missing", "missing") == []


def test_ids_are_sql_parameters(records):
    item = quote(event_id="EV'; DROP TABLE procurement_quotations; --")
    records.save_quotations([item])
    assert records.get_quotations(item["event_id"], "P1") == [item]
    records.save_quotations([quote()])
    assert records.get_quotations("EV001", "P1") == [quote()]


def test_changed_quote_is_not_overwritten_and_batch_rolls_back(records):
    records.save_quotations([quote()])
    with pytest.raises(ProcurementRecordConflict):
        records.save_quotations([quote(quotation_id="Q2"), quote(quoted_total_cents=1)])
    assert records.get_quotations("EV001", "P1") == [quote()]


@pytest.mark.parametrize("change", [
    {"quoted_total_cents": True}, {"quoted_total_cents": 1.0}, {"quoted_total_cents": -1},
    {"guest_count": True}, {"event_date": "2026-02-30"}, {"mock": False},
    {"available": None}, {"available": False}, {"scenario_id": ""}, {"event_id": ""},
])
def test_invalid_or_unconfirmed_quotation_is_not_saved(records, change):
    with pytest.raises(ValueError):
        records.save_quotations([quote(**change)])
    assert records.get_quotations("EV001", "P1") == []


@pytest.mark.parametrize("quotes", [[], None, {}, [quote(), quote()]])
def test_bad_quote_batch_rejected(records, quotes):
    with pytest.raises(ValueError):
        records.save_quotations(quotes)


def test_restart_reuses_booking_without_supplier_call(records):
    first_supplier = MockVendorBookingService([scenario()])
    first = VendorBookingService(first_supplier, record_service=records).confirm_bookings(request())
    assert first["status"] == "success" and len(first_supplier.calls) == 1
    reopened = ProcurementRecordService(records.database_path)
    new_supplier = MockVendorBookingService([])
    restarted = VendorBookingService(new_supplier, record_service=reopened)
    again = restarted.confirm_bookings(request())
    assert again["status"] == "success" and not new_supplier.calls
    assert again["data"]["bookings"] == first["data"]["bookings"]
    assert restarted.get_bookings("EV001", "P1") == first["data"]["bookings"]
    assert restarted.get_bookings("OTHER", "P1") == []
    assert restarted.get_bookings("EV001", "OTHER") == []


def test_real_new_process_reloads_and_reuses_confirmed_booking(records):
    VendorBookingService(MockVendorBookingService([scenario()]), record_service=records).confirm_bookings(request())
    code = '''import json, sys
from src.services.procurement_record_service import ProcurementRecordService
from src.services.vendor_booking_service import VendorBookingService, MockVendorBookingService
records = ProcurementRecordService(sys.argv[1])
supplier = MockVendorBookingService([])
result = VendorBookingService(supplier, record_service=records).confirm_bookings(json.load(sys.stdin))
assert result["status"] == "success" and len(result["data"]["bookings"]) == 1
assert not supplier.calls
print("reloaded")
'''
    completed = subprocess.run([sys.executable, "-c", code, str(records.database_path)],
        input=json.dumps(request()), capture_output=True, text=True, cwd=ROOT, timeout=15)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "reloaded"


def test_restart_still_checks_payment_and_quote_changes(records):
    VendorBookingService(MockVendorBookingService([scenario()]), record_service=records).confirm_bookings(request())
    supplier = MockVendorBookingService([])
    restarted = VendorBookingService(supplier, record_service=ProcurementRecordService(records.database_path))
    unpaid = request()
    unpaid["deposit"]["status"] = "pending"
    assert restarted.confirm_bookings(unpaid)["status"] == "blocked"
    changed = request([quote(quoted_total_cents=1)])
    result = restarted.confirm_bookings(changed)
    assert result["status"] == "blocked" and result["data"]["requires_attention"]
    assert not supplier.calls


def test_partial_confirmation_survives_restart(records):
    second = quote(quotation_id="Q2", vendor_id="V2", offering_id="O2")
    supplier = MockVendorBookingService([scenario(), scenario(second, status="pending")])
    first = VendorBookingService(supplier, record_service=records).confirm_bookings(request([quote(), second]))
    assert first["status"] == "blocked" and len(first["data"]["bookings"]) == 1
    next_supplier = MockVendorBookingService([scenario(second, confirmation="CONF2")])
    restarted = VendorBookingService(next_supplier, record_service=ProcurementRecordService(records.database_path))
    again = restarted.confirm_bookings(request([quote(), second]))
    assert again["status"] == "success" and len(again["data"]["bookings"]) == 2
    assert [call["quotation_id"] for call in next_supplier.calls] == ["Q2"]


@pytest.mark.parametrize("status", ["pending", "rejected"])
def test_unconfirmed_booking_not_persisted(records, status):
    result = VendorBookingService(MockVendorBookingService([scenario(status=status)]),
                                  record_service=records).confirm_bookings(request())
    assert result["status"] == "blocked" and result["data"]["requires_attention"]
    assert result["data"]["customer_payment"]["status"] == "paid"
    assert ProcurementRecordService(records.database_path).get_bookings("EV001", "P1") == []


def test_booking_conflict_preserves_original_confirmation(records):
    result = VendorBookingService(MockVendorBookingService([scenario()]), record_service=records).confirm_bookings(request())
    saved, = result["data"]["bookings"]
    records.save_booking(saved)
    with pytest.raises(ProcurementRecordConflict):
        records.save_booking({**saved, "quoted_total_cents": 1})
    with pytest.raises(ProcurementRecordConflict):
        records.save_booking({**saved, "quotation_id": "Q2", "booking_id": "B2"})
    assert records.get_bookings("EV001", "P1") == [saved]


@pytest.mark.parametrize("change", [{"status": "Pending"}, {"mock": False}, {"quoted_total_cents": True}])
def test_invalid_booking_is_not_persisted(records, change):
    result = VendorBookingService(MockVendorBookingService([scenario()])).confirm_bookings(request())
    saved = result["data"]["bookings"][0]
    with pytest.raises(ValueError):
        records.save_booking({**saved, **change})
    assert not records.get_bookings("EV001", "P1")


def unavailable():
    raise sqlite3.OperationalError("simulated unavailable database")


def test_db_read_failure_stops_before_supplier_call(records, monkeypatch):
    supplier = MockVendorBookingService([scenario()])
    booking = VendorBookingService(supplier, record_service=records)
    monkeypatch.setattr(records, "_connect", unavailable)
    result = booking.confirm_bookings(request())
    assert result["status"] == "error" and result["data"]["requires_attention"]
    assert result["data"]["customer_payment"]["status"] == "paid" and not supplier.calls


def test_db_write_failure_prevents_successful_quote_handoff(records, monkeypatch):
    worker = agent(records)
    monkeypatch.setattr(records, "_connect", unavailable)
    result = worker.request_quotations(ENQUIRY)
    assert result["status"] == "error" and result["data"] == {} and not worker.llm.calls


def test_failed_save_retains_confirmation_and_recovers_without_resending(records, monkeypatch):
    supplier = MockVendorBookingService([scenario()])
    booking = VendorBookingService(supplier, record_service=records)
    save = records.save_booking
    def fail(_):
        raise ProcurementStorageError("simulated full disk")
    monkeypatch.setattr(records, "save_booking", fail)
    result = booking.confirm_bookings(request())
    assert result["status"] == "error" and result["data"]["requires_attention"]
    assert len(result["data"]["bookings"]) == 1 and len(supplier.calls) == 1
    assert result["data"]["supplier_replies"][0]["status"] == "confirmed"
    monkeypatch.setattr(records, "save_booking", save)
    again = booking.confirm_bookings(request())
    assert again["status"] == "success" and len(supplier.calls) == 1
    assert records.get_bookings("EV001", "P1") == result["data"]["bookings"]


@pytest.mark.parametrize("payload", ["{invalid", "[]", json.dumps(quote(quoted_total_cents=True)),
                                      json.dumps(quote(event_id="OTHER"))])
def test_corrupted_saved_quote_never_silently_becomes_empty(records, payload):
    records.save_quotations([quote()])
    with sqlite3.connect(records.database_path) as connection:
        connection.execute("UPDATE procurement_quotations SET payload=?", (payload,))
    with pytest.raises(ProcurementStorageError):
        records.get_quotations("EV001", "P1")


def test_env_configuration_and_no_memory_fallback(tmp_path, monkeypatch):
    path = tmp_path / "custom" / "records.sqlite3"
    monkeypatch.setenv("ELEC5620_DB_PATH", str(path))
    assert ProcurementRecordService.from_env().database_path == path.resolve()
    assert path.is_file()
    monkeypatch.setenv("ELEC5620_DB_PATH", "")
    with pytest.raises(ValueError):
        ProcurementRecordService.from_env()
    with pytest.raises(ProcurementStorageError):
        ProcurementRecordService(tmp_path)  # directory is not a SQLite file


@pytest.mark.parametrize("path", [None, "", "   ", ":memory:", "file:mem?mode=memory", 1])
def test_invalid_file_configuration_rejected(path):
    with pytest.raises(ValueError):
        ProcurementRecordService(path)


def test_saved_quote_conflict_reaches_agent_error(records):
    worker = agent(records)
    first = worker.request_quotations(ENQUIRY)
    saved = first["data"]["quotations"][0]
    # Simulate a previously reviewed snapshot with a different quoted price.
    # The new enquiry must not silently overwrite it or return success.
    with sqlite3.connect(records.database_path) as connection:
        connection.execute("UPDATE procurement_quotations SET payload=?", (
            records._json({**saved, "quoted_total_cents": saved["quoted_total_cents"] + 1}),))
    assert worker.request_quotations(ENQUIRY)["status"] == "error"


def test_optional_dependency_type_validation():
    with pytest.raises(TypeError):
        VendorBookingService(MockVendorBookingService([]), record_service=object())
    with pytest.raises(TypeError):
        agent(object())
