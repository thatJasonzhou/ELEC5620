"""Real Agent/Service integration with explicit Operations STUB evidence."""
from src.demo.financial_app import FinancialDemoApp
from tests.unit.test_financial_demo_context import CountingPayments, approved, ok


def test_complete_flow_funds_gates_and_restart(tmp_path, monkeypatch):
    monkeypatch.setenv('ELEC5620_DEPOSIT_RATE', '0.30')
    path = tmp_path / 'demo.db'
    provider = CountingPayments()
    app = FinancialDemoApp(path, payment_service=provider)
    event = approved(app)
    deposit = ok(app.prepare_deposit(event))['deposit']
    ok(app.pay_deposit(event, deposit['deposit_request_id'], deposit['amount_cents']))
    booking = ok(app.confirm_bookings(event))['bookings'][0]
    evidence = ok(app.create_operations_stub(event))
    assert ok(app.create_operations_stub(event)) == evidence
    assert app.prepare_vendor_payment(event, booking['booking_id'])['status'] == 'blocked'
    assert app.reconcile(event)['status'] == 'blocked'
    final = ok(app.prepare_final(event))['final_payment']
    ok(app.pay_final(event, final['final_request_id'], final['amount_cents']))
    pending = ok(app.prepare_vendor_payment(event, booking['booking_id']))['vendor_payment']
    ok(app.pay_vendor(event, pending['payment_id'], pending['amount_cents']))
    result = ok(app.reconcile(event))
    assert result['financial_check_passed']
    assert result['customer']['balance_cents'] == result['vendors']['balance_cents'] == 0
    assert provider.calls == 3
    restarted_provider = CountingPayments()
    app = FinancialDemoApp(path, payment_service=restarted_provider)
    ok(app.pay_deposit(event, deposit['deposit_request_id'], deposit['amount_cents']))
    ok(app.pay_final(event, final['final_request_id'], final['amount_cents']))
    ok(app.pay_vendor(event, pending['payment_id'], pending['amount_cents']))
    assert ok(app.reconcile(event))['financial_check_passed']
    assert restarted_provider.calls == 0
    assert ok(app.create_operations_stub(event)) == evidence
    assert app.procurement_records.get_bookings(event, booking['proposal_id'])[0]['status'] == 'Confirmed'
    assert not app.llm.calls


def test_changed_scope_is_not_silently_regenerated(tmp_path, monkeypatch):
    monkeypatch.setenv('ELEC5620_DEPOSIT_RATE', '0.30')
    app = FinancialDemoApp(tmp_path / 'scope.db')
    event = approved(app)
    d = ok(app.prepare_deposit(event))['deposit']
    ok(app.pay_deposit(event, d['deposit_request_id'], d['amount_cents']))
    ok(app.confirm_bookings(event))
    ok(app.create_operations_stub(event))
    original = app.operations._bookings
    monkeypatch.setattr(app.operations, '_bookings', lambda e: original(e) + [{'booking_id': 'new'}])
    assert app.create_operations_stub(event)['status'] == 'blocked'
    assert app.reconcile(event)['status'] != 'success'


def test_uncertain_vendor_execution_blocks_retry_after_restart(tmp_path, monkeypatch):
    monkeypatch.setenv('ELEC5620_DEPOSIT_RATE', '0.30')
    path = tmp_path / 'uncertain.db'
    provider = CountingPayments()
    app = FinancialDemoApp(path, payment_service=provider)
    event = approved(app)
    d = ok(app.prepare_deposit(event))['deposit']
    ok(app.pay_deposit(event, d['deposit_request_id'], d['amount_cents']))
    booking = ok(app.confirm_bookings(event))['bookings'][0]
    f = ok(app.prepare_final(event))['final_payment']
    ok(app.pay_final(event, f['final_request_id'], f['amount_cents']))
    ok(app.create_operations_stub(event))
    p = ok(app.prepare_vendor_payment(event, booking['booking_id']))['vendor_payment']
    def fail_save(record):
        from src.services.vendor_payment_record_service import VendorPaymentStorageError
        raise VendorPaymentStorageError('uncertain result save')
    monkeypatch.setattr(app.finance._settlement_service._records, 'finish', fail_save)
    assert app.pay_vendor(event, p['payment_id'], p['amount_cents'])['status'] == 'error'
    assert provider.calls == 3
    restarted = FinancialDemoApp(path, payment_service=CountingPayments())
    assert restarted.pay_vendor(event, p['payment_id'], p['amount_cents'])['status'] == 'blocked'
    assert restarted.payments.calls == 0
    assert restarted.reconcile(event)['status'] == 'blocked'
