"""Joint-mode handoff uses actual Finance/deposit/booking services offline."""
from copy import deepcopy

import pytest

from examples.joint_booking_handoff_example import (
    ROOT, booking_request, build_case, prepare_deposit, run_case,
)
from src.services.vendor_booking_service import MockVendorBookingService


@pytest.fixture(autouse=True)
def explicit_test_deposit_policy(monkeypatch):
    monkeypatch.setenv("ELEC5620_DEPOSIT_RATE", "0.30")


@pytest.mark.parametrize("scenario,vendor_total,financial_total,deposit", [
    ("photography_priority", 931000, 1117200, 335160),
    ("lowest_cost", 873300, 1047960, 314388),
    ("sound_priority", 974800, 1169760, 350928),
])
def test_three_joint_selections_pass_full_approved_paid_confirmed_handoff(
        tmp_path, scenario, vendor_total, financial_total, deposit):
    # run_case exercises unapproved/unpaid/stale-quote gates, real payment
    # simulation, five supplier confirmations, retries and SQLite restarts.
    result = run_case(scenario, tmp_path)
    assert result["supplier_total_cents"] == vendor_total
    assert result["financial_total_cents"] == financial_total
    assert result["deposit_cents"] == deposit
    assert result["selected_count"] == result["booking_count"] == 5
    assert result["payment_provider_calls"] == 1 and result["supplier_booking_calls"] == 5
    assert result["restart_payment_calls"] == result["restart_supplier_calls"] == 0


def test_failed_customer_payment_cannot_trigger_supplier_booking(tmp_path):
    case = build_case("photography_priority", tmp_path, customer_outcome="failure")
    _, click = prepare_deposit(case)
    failed = case["finance"].handle(click)
    assert failed["status"] == "success" and failed["data"]["deposit"]["status"] == "failed"
    booking = case["procurement"].confirm_bookings(booking_request(case, failed))
    assert booking["status"] == "blocked" and booking["data"]["bookings"] == []
    assert case["supplier"].calls == [] and case["payments"].calls == 1
    assert case["finance"].handle(click)["data"] == failed["data"]
    assert case["payments"].calls == 1


def test_payment_requires_explicit_click_and_exact_prepared_amount(tmp_path):
    case = build_case("photography_priority", tmp_path)
    pending, click = prepare_deposit(case)
    for invalid in ({**click, "simulate": False}, {**click, "amount_cents": click["amount_cents"] - 1}):
        result = case["finance"].handle(invalid)
        assert result["status"] == "blocked"
    assert case["payments"].calls == 0 and case["supplier"].calls == []
    assert pending["data"]["deposit"]["status"] == "pending"
    assert case["finance"].handle(click)["data"]["deposit"]["status"] == "paid"
    assert case["payments"].calls == 1


def test_customer_must_approve_the_exact_five_selected_quotations(tmp_path):
    case = build_case("photography_priority", tmp_path)
    approval = deepcopy(case["approval"])
    approval["approved_quotation_ids"].pop()
    result = case["finance"].handle({
        **case["request"], "action": "prepare_deposit_request", "approval": approval})
    assert result["status"] == "blocked"
    assert case["payments"].calls == 0 and case["supplier"].calls == []


def test_supplier_decline_after_payment_retains_payment_for_attention(tmp_path):
    class DecliningSupplier(MockVendorBookingService):
        def request_booking(self, quotation):
            reply = super().request_booking(quotation)
            return {**reply, "status": "rejected", "supplier_confirmation_id": None,
                    "reason": "MOCK supplier declines final booking."}

    source = MockVendorBookingService.from_json_file(ROOT / "data/mock_vendor_bookings.json")
    supplier = DecliningSupplier(list(source._index.values()))
    case = build_case("photography_priority", tmp_path, supplier=supplier)
    _, click = prepare_deposit(case)
    paid = case["finance"].handle(click)
    result = case["procurement"].confirm_bookings(booking_request(case, paid))
    assert result["status"] == "blocked" and result["data"]["requires_attention"] is True
    assert result["data"]["bookings"] == [] and len(supplier.calls) == 1
    assert result["data"]["customer_payment"] == paid["data"]["deposit"]
    assert result["data"]["customer_payment"]["status"] == "paid"
    assert case["payments"].calls == 1
