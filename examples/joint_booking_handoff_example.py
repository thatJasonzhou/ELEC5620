"""Offline joint Procurement -> Finance -> deposit -> booking handoff.

Replays supplier choices already observed in the school Live tests. This tests
handoff and gates, not model reasoning, Planner/UI integration or real payments.
Run: python -m examples.joint_booking_handoff_example
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.agents.financial_manager import FinancialManagerAgent
from src.agents.vendor_procurement_manager import VendorProcurementManagerAgent
from src.llm import MockLLMClient
from src.services.financial_record_service import FinancialRecordService
from src.services.mock_payment_service import MockPaymentService
from src.services.procurement_record_service import ProcurementRecordService
from src.services.vendor_booking_service import MockVendorBookingService, VendorBookingService
from src.services.vendor_procurement_service import VendorProcurementService
from src.services.vendor_quotation_service import MockVendorQuotationService

ROOT = Path(__file__).resolve().parents[1]
BASE_SELECTION = {
    "photography": "V-PHOTO-003", "catering": "V-CAT-003", "venue": "V-VENUE-001",
    "sound": "V-SOUND-001", "decoration": "V-DECOR-001",
}
CASES = {
    "photography_priority": ("procurement_priority_request.json",
                             {**BASE_SELECTION, "photography": "V-PHOTO-004"}, 931000),
    "lowest_cost": ("procurement_lowest_cost_request.json", BASE_SELECTION, 873300),
    "sound_priority": ("procurement_sound_priority_request.json",
                       {**BASE_SELECTION, "sound": "V-SOUND-004"}, 974800),
}


class CountingPayments(MockPaymentService):
    """Count provider effects rather than just trusting final status."""

    def __init__(self, *, customer_outcome="success"):
        super().__init__(customer_outcome=customer_outcome)
        self.calls = 0

    def process_payment(self, payment):
        self.calls += 1
        return super().process_payment(payment)


def build_case(name, directory, *, customer_outcome="success", supplier=None):
    """Prepare actual current quotation/budget/customer-quote snapshots only."""
    filename, selection, expected = CASES[name]
    request = json.loads((ROOT / "examples/requests" / filename).read_text(encoding="utf-8"))
    directory = Path(directory)
    records = ProcurementRecordService(directory / "procurement.sqlite3")
    financial_records = FinancialRecordService(directory / "financial.sqlite3")
    vendors = VendorProcurementService.from_json_file(ROOT / "data/vendor_catalog.json")
    names = {vendor.vendor_id: vendor.name for vendor in vendors.catalog}

    def replay(messages):
        facts = json.loads(messages[-1]["content"].split("\n", 1)[1])
        indices = [next(row[0] for row in service["quotes"]
                        if row[1] == names[selection[service["service"]]])
                   for service in facts["services"]]
        return json.dumps({"choices": indices,
                           "reason": "MOCK replay of previously observed Live selections."})

    supplier = supplier if supplier is not None else MockVendorBookingService.from_json_file(
        ROOT / "data/mock_vendor_bookings.json")
    booking = VendorBookingService(supplier, record_service=records)
    procurement = VendorProcurementManagerAgent(
        MockLLMClient(replay), vendors,
        MockVendorQuotationService.from_json_file(ROOT / "data/mock_vendor_quotations.json"),
        booking, record_service=records, compact_llm=True, joint_selection=True)
    compared = procurement.procure_services(request)
    assert compared["status"] == "success", compared["message"]
    quotes = compared["data"]["quotations"]
    assert len(quotes) == 5 and len(compared["data"]["candidate_quotations"]) == 15
    assert sum(q["quoted_total_cents"] for q in quotes) == expected

    payments = CountingPayments(customer_outcome=customer_outcome)
    finance_llm = MockLLMClient()
    finance_llm.set_exception(AssertionError("Financial handoff must not invoke a model"))
    finance = FinancialManagerAgent(finance_llm, payments, record_service=financial_records)
    handoff = {
        "event_id": request["event_id"],
        "event": {k: request[k] for k in (
            "event_id", "event_date", "guest_count", "budget_limit_cents")},
        "proposal": {"event_id": request["event_id"], "proposal_id": request["proposal_id"],
                     "required_services": [s["service_type"] for s in request["services"]]},
        "quotations": quotes,
        "selected_quotation_ids": compared["data"]["selected_quotation_ids"],
    }
    budget = finance.handle({**handoff, "action": "prepare_budget"})
    assert budget["status"] == "success", budget["message"]
    handoff["budget"] = budget["data"]
    customer = finance.handle({**handoff, "action": "generate_customer_quotation"})
    assert customer["status"] == "success", customer["message"]
    quote = customer["data"]["customer_quotation"]
    handoff.update(customer_quotation=quote, customer_id="MOCK-HANDOFF-CUSTOMER",
                   due_date="2026-12-01")
    approval = {k: quote[k] for k in (
        "event_id", "proposal_id", "quotation_fingerprint", "customer_quotation_id")}
    approval.update(approved=True, approved_quotation_ids=list(quote["selected_quotation_ids"]))
    return dict(request=handoff, approval=approval, finance=finance, payments=payments,
                finance_llm=finance_llm, procurement=procurement, booking=booking,
                supplier=supplier, records=records, financial_records=financial_records)


def prepare_deposit(case):
    """Explicit simulated customer approval, supplied by this fixture."""
    request = {**case["request"], "approval": case["approval"]}
    result = case["finance"].handle({**request, "action": "prepare_deposit_request"})
    assert result["status"] == "success", result["message"]
    deposit = result["data"]["deposit"]
    payment_click = {
        **request, "action": "simulate_deposit_payment", "simulate": True,
        "deposit_request_id": deposit["deposit_request_id"], "amount_cents": deposit["amount_cents"],
    }
    return result, payment_click


def booking_request(case, payment_result):
    return {
        "event_id": case["request"]["event_id"],
        "proposal_id": case["request"]["proposal"]["proposal_id"],
        "quotations": case["request"]["quotations"], "approval": case["approval"],
        **payment_result["data"],
    }


def run_case(name, directory):
    case = build_case(name, directory)
    finance, procurement = case["finance"], case["procurement"]
    # No approval: Finance cannot even prepare a deposit.
    unapproved = finance.handle({**case["request"], "approval": {**case["approval"], "approved": False},
                                 "action": "prepare_deposit_request"})
    assert unapproved["status"] == "blocked" and case["payments"].calls == 0

    pending, payment_click = prepare_deposit(case)
    assert pending["data"]["deposit"]["status"] == "pending"
    pending_booking = booking_request(case, pending)
    denied_approval = procurement.confirm_bookings({
        **pending_booking, "approval": {**case["approval"], "approved": False}})
    assert denied_approval["status"] == "blocked"
    unpaid = procurement.confirm_bookings(pending_booking)
    assert unpaid["status"] == "blocked" and not case["supplier"].calls

    # Only this explicit fixture click initiates the simulated payment.
    paid = finance.handle(payment_click)
    assert paid["status"] == "success" and paid["data"]["deposit"]["status"] == "paid"
    assert case["payments"].calls == 1
    ready = booking_request(case, paid)
    changed = deepcopy(ready)
    changed["quotations"][0]["quoted_total_cents"] += 1
    stale = procurement.confirm_bookings(changed)
    assert stale["status"] == "blocked" and not case["supplier"].calls

    booked = procurement.confirm_bookings(ready)
    assert booked["status"] == "success", booked["message"]
    ids = {b["booking_id"] for b in booked["data"]["bookings"]}
    assert len(ids) == len(case["supplier"].calls) == 5
    assert finance.handle(payment_click)["data"] == paid["data"]
    assert {b["booking_id"] for b in procurement.confirm_bookings(ready)["data"]["bookings"]} == ids
    assert case["payments"].calls == 1 and len(case["supplier"].calls) == 5

    # New service/Agent instances, same persisted records: no provider effects.
    fresh_payments = CountingPayments()
    fresh_finance = FinancialManagerAgent(case["finance_llm"], fresh_payments,
        record_service=FinancialRecordService(case["financial_records"].database_path))
    assert fresh_finance.handle(payment_click)["data"] == paid["data"]
    fresh_supplier = MockVendorBookingService.from_json_file(ROOT / "data/mock_vendor_bookings.json")
    fresh_records = ProcurementRecordService(case["records"].database_path)
    fresh_procurement = VendorProcurementManagerAgent(
        case["procurement"].llm, case["procurement"]._vendor_service,
        booking_service=VendorBookingService(fresh_supplier, record_service=fresh_records),
        record_service=fresh_records)
    restored = fresh_procurement.confirm_bookings(ready)
    assert restored["status"] == "success"
    assert {b["booking_id"] for b in restored["data"]["bookings"]} == ids
    assert fresh_payments.calls == 0 and fresh_supplier.calls == []
    assert len(procurement.llm.calls) == 1 and case["finance_llm"].calls == []
    return {
        "scenario": name, "status": "success", "selected_count": 5,
        "supplier_total_cents": paid["data"]["budget"]["vendor_total_cents"],
        "financial_total_cents": paid["data"]["budget"]["estimated_total_cents"],
        "deposit_cents": paid["data"]["deposit"]["amount_cents"],
        "booking_count": 5, "payment_provider_calls": case["payments"].calls,
        "supplier_booking_calls": len(case["supplier"].calls),
        "restart_payment_calls": fresh_payments.calls,
        "restart_supplier_calls": len(fresh_supplier.calls),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=tuple(CASES), help="Default: verify all three scenarios.")
    args = parser.parse_args()
    print("OFFLINE MOCK: replayed supplier choices, explicit approval/payment fixtures, 30% deposit.")
    # Test policy scoped to this process; no configuration file or production default is changed.
    with patch.dict(os.environ, {"ELEC5620_DEPOSIT_RATE": "0.30"}):
        with TemporaryDirectory(prefix="joint-booking-handoff-") as directory:
            for name in ([args.scenario] if args.scenario else CASES):
                result = run_case(name, Path(directory) / name)
                print(f"{name}: success | selected={result['selected_count']} | "
                      f"Financial AUD{result['financial_total_cents'] / 100:,.2f} | "
                      f"deposit AUD{result['deposit_cents'] / 100:,.2f} paid | bookings=5")
    print("Gates passed; repeat/restart produced no duplicate payment or booking calls.")


if __name__ == "__main__":
    main()
