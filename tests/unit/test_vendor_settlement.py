from copy import deepcopy
import sqlite3

import pytest

from examples.vendor_payment_example import demo_inputs
from src.agents.financial_manager import FinancialManagerAgent
from src.llm import MockLLMClient
from src.services.mock_payment_service import MockPaymentService
from src.services.procurement_record_service import ProcurementRecordService
from src.services.vendor_payment_record_service import (VendorPaymentRecordService,
    VendorPaymentConflict, VendorPaymentStorageError)
from src.services.vendor_settlement_service import VendorSettlementService


class CountingMock(MockPaymentService):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.calls = 0

    def process_payment(self, payment):
        self.calls += 1
        return super().process_payment(payment)


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / "records.sqlite3"
    procurement = ProcurementRecordService(path)
    request = demo_inputs(procurement)
    provider = CountingMock()
    records = VendorPaymentRecordService(path)
    return VendorSettlementService(provider, procurement, records), request, provider, records


def execution(service, request):
    payment = service.prepare(request)["data"]["vendor_payment"]
    return {**deepcopy(request), "simulate": True, "payment_id": payment["payment_id"],
            "amount_cents": payment["amount_cents"]}


@pytest.mark.parametrize('change', ['approval', 'budget', 'persisted', 'funds', 'stale'])
def test_current_financial_conditions_block_pending(setup, change):
    service, request, provider, records = setup
    pay = execution(service, request)
    if change == 'approval':
        pay['approval']['approved'] = False
    if change == 'budget':
        pay.pop('budget')
    if change == 'stale':
        pay['event']['revision'] = 2
    if change in ('persisted', 'funds'):
        with sqlite3.connect(records.database_path) as db:
            db.execute('DELETE FROM ' + ('financial_snapshots' if change == 'persisted'
                                        else 'financial_final_requests'))
    result = service.simulate_payment(pay)
    assert result['status'] == 'blocked'
    assert provider.calls == 0
    assert records.get(pay['payment_id'])['status'] == 'pending'
    if change == 'funds':
        assert result['data']['settlement_check']['funds_shortfall_cents'] == 10000


def test_activity_totals_restart_and_replay(setup):
    from src.services.financial_record_service import FinancialRecordService
    service, request, provider, records = setup
    pay = execution(service, request)
    paid = service.simulate_payment(pay)
    assert paid['data']['vendor_payment']['approved_at'] is None
    funds = FinancialRecordService(records.database_path).event_funds('EV001')
    assert funds['received_total_cents'] == 12000
    assert funds['vendor_paid_total_cents'] == 10000
    assert funds['available_funds_cents'] == 2000
    assert service.simulate_payment(pay) == paid and provider.calls == 1
    assert FinancialRecordService(records.database_path).event_funds('EV001') == funds


def test_historical_proposal_spend_counts_against_current_limit(setup):
    service, request, provider, records = setup
    pending = service.prepare(request)['data']['vendor_payment']
    old = {**pending, 'payment_id': 'VP-OLD', 'vendor_booking_id': 'OLD',
        'invoice_number': 'OLD', 'proposal_id': 'OLD', 'status': 'pending', 'amount_cents': 3000}
    records.create(old)
    old.update(status='paid', paid_at=pending['created_at'], transaction_reference='MOCK-VP-OLD')
    records.finish(old)
    result = service.simulate_payment({**request, 'simulate': True,
        'payment_id': pending['payment_id'], 'amount_cents': 10000})
    check = result['data']['settlement_check']
    assert result['status'] == 'blocked' and provider.calls == 0
    assert check['budget_shortfall_cents'] == 3000
    assert check['funds_shortfall_cents'] == 1000


def test_invalid_paid_evidence_blocks(setup):
    import json
    service, request, provider, records = setup
    with sqlite3.connect(records.database_path) as db:
        payload = json.loads(db.execute('SELECT payload FROM financial_final_requests').fetchone()[0])
        payload['payment']['transaction_reference'] = 'invalid'
        db.execute('UPDATE financial_final_requests SET payload=?', (json.dumps(payload),))
    assert service.prepare(request)['status'] == 'blocked'
    assert provider.calls == 0


@pytest.mark.parametrize("outcome,terminal", [("success", "paid"), ("failure", "failed")])
def test_pending_terminal_and_restart(setup, outcome, terminal):
    service, request, provider, records = setup
    provider.vendor_outcome = outcome
    original = deepcopy(request)
    pending = service.prepare(request)
    assert service.prepare(request) == pending and provider.calls == 0
    pay = execution(service, request)
    result = service.simulate_payment(pay)
    assert result["data"]["vendor_payment"]["status"] == terminal
    assert provider.calls == 1 and request == original
    new_provider = CountingMock()
    reopened = VendorSettlementService(new_provider, ProcurementRecordService(records.database_path),
                                      VendorPaymentRecordService(records.database_path))
    assert reopened.simulate_payment(pay) == result
    assert new_provider.calls == 0
    result["data"]["vendor_payment"]["status"] = "corrupted"
    assert records.get(pay["payment_id"])["status"] == terminal


@pytest.mark.parametrize("field,value", [("amount_cents", True), ("amount_cents", 1.5),
    ("amount_cents", "10000"), ("amount_cents", 0), ("amount_cents", 9999),
    ("vendor_id", "OTHER"), ("quotation_id", "OTHER"), ("mock", False), ("currency", "USD")])
def test_invalid_invoice_never_calls_provider(setup, field, value):
    service, request, provider, _ = setup
    request["invoice"][field] = value
    assert service.prepare(request)["status"] == "blocked"
    assert provider.calls == 0


@pytest.mark.parametrize("field,value", [("status", "pending"), ("mock", False),
    ("vendor_booking_id", "OTHER"), ("completed_at", "2099-01-01T00:00:00+00:00"),
    ("completed_at", "2026-01-01T00:00:00")])
def test_invalid_completion(setup, field, value):
    service, request, provider, _ = setup
    request["completion"][field] = value
    assert service.prepare(request)["status"] == "blocked" and provider.calls == 0


@pytest.mark.parametrize("change", ["consent", "amount", "id", "evidence", "source"])
def test_execution_revalidates(setup, change):
    service, request, provider, records = setup
    pay = execution(service, request)
    if change == "consent": pay["simulate"] = False
    if change == "amount": pay["amount_cents"] += 1
    if change == "id": pay["payment_id"] = "unknown"
    if change == "evidence": pay["completion"]["status"] = "pending"
    if change == "source":
        with sqlite3.connect(records.database_path) as db:
            db.execute("DELETE FROM procurement_quotations")
    assert service.simulate_payment(pay)["status"] == "blocked" and provider.calls == 0
    assert records.get_for_booking("VB1")["status"] == "pending"


def test_conflicting_prepare_and_database_constraints(setup):
    service, request, provider, records = setup
    saved = service.prepare(request)["data"]["vendor_payment"]
    request["invoice"]["invoice_number"] = "NEW"
    assert service.prepare(request)["status"] == "blocked"
    for changes in ({"payment_id": "NEW"},
                    {"payment_id": "NEW", "vendor_booking_id": "OTHER"}):
        with pytest.raises(VendorPaymentConflict):
            records.create({**saved, **changes})
    assert provider.calls == 0


def test_storage_errors_and_provider_error(setup, monkeypatch):
    service, request, provider, records = setup
    pay = execution(service, request)
    def fail(*args):
        raise RuntimeError("mock error")
    monkeypatch.setattr(provider, "process_payment", fail)
    assert service.simulate_payment(pay)["data"]["vendor_payment"]["status"] == "failed"
    def unavailable(*args):
        raise VendorPaymentStorageError("unavailable")
    monkeypatch.setattr(records, "get", unavailable)
    assert service.simulate_payment(pay)["status"] == "error"


def test_agent_and_legacy_stub(setup):
    service, request, provider, _ = setup
    llm = MockLLMClient()
    llm.set_exception(AssertionError("No LLM in payments"))
    worker = FinancialManagerAgent(llm, provider, settlement_service=service)
    pending = worker.handle({**request, "action": "prepare_vendor_payment_request"})
    assert pending["agent"] == "finance" and pending["data"]["vendor_payment"]["status"] == "pending"
    assert worker.handle({**execution(service, request), "action": "simulate_vendor_payment"})["status"] == "success"
    with pytest.raises(NotImplementedError):
        worker.settle_vendor_payment(None)
    assert not llm.calls
    assert FinancialManagerAgent(llm, provider).handle(
        {**request, "action": "prepare_vendor_payment_request"})["status"] == "error"


def test_failed_outcome_save_reports_manual_review(setup, monkeypatch):
    service, request, provider, records = setup
    pay = execution(service, request)
    def unavailable(*args):
        raise VendorPaymentStorageError("cannot save outcome")
    monkeypatch.setattr(records, "finish", unavailable)
    result = service.simulate_payment(pay)
    assert result["status"] == "error" and "manual review" in result["message"]
    assert provider.calls == 1
    assert records.get(pay["payment_id"])["status"] == "pending"
    # Intentionally do not retry: uncertain saves are a documented MVP limitation.


def test_persisted_source_fingerprint_mismatch_blocks(setup):
    import json
    service, request, provider, records = setup
    with sqlite3.connect(records.database_path) as db:
        payload = json.loads(db.execute("SELECT payload FROM procurement_bookings").fetchone()[0])
        payload["source_quotation_fingerprint"] = "STALE"
        db.execute("UPDATE procurement_bookings SET payload=?", (json.dumps(payload),))
    assert service.prepare(request)["status"] == "blocked"
    assert provider.calls == 0 and records.get_for_booking("VB1") is None
