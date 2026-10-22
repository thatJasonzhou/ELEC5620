"""AC1-5 using a trusted STUB scope and persistent payment facts."""
import json
import sqlite3
import pytest
from examples.financial_reconciliation_example import setup_demo
from src.agents.financial_manager import FinancialManagerAgent
from src.llm import MockLLMClient
from src.services.mock_payment_service import MockPaymentService
from src.services.financial_record_service import FinancialStorageError


@pytest.fixture
def setup(tmp_path):
    service, context, scope, settlement = setup_demo(tmp_path / 'demo.db')
    return service, context, scope, settlement


def settle(setup):
    service, context, scope, settlement = setup
    payment = settlement.prepare(context)['data']['vendor_payment']
    settlement.simulate_payment({**context, 'simulate': True, 'payment_id': payment['payment_id'],
                                'amount_cents': payment['amount_cents']})


def mutate(service, table, change):
    with sqlite3.connect(service.financial.database_path) as db:
        rowid, payload = db.execute(f'SELECT rowid,payload FROM {table}').fetchone()
        record = json.loads(payload)
        change(record)
        db.execute(f'UPDATE {table} SET payload=? WHERE rowid=?', (json.dumps(record), rowid))


def test_ac2_missing_pending_failed(setup):
    service, context, _, settlement = setup
    assert 'VENDOR_PAYMENT_MISSING' in service.reconcile('EV001')['data']['reason_codes']
    settlement.prepare(context)
    assert 'VENDOR_PAYMENT_UNPAID' in service.reconcile('EV001')['data']['reason_codes']
    mutate(service, 'vendor_payments', lambda p: p.update(status='failed'))
    assert 'VENDOR_PAYMENT_FAILED' in service.reconcile('EV001')['data']['reason_codes']


def test_ac1_customer_debt(setup):
    service, _, _, _ = setup
    with sqlite3.connect(service.financial.database_path) as db:
        db.execute('DELETE FROM financial_final_requests')
    result = service.reconcile('EV001')
    assert result['status'] == 'blocked'
    assert result['data']['customer']['balance_cents'] > 0


def test_ac3_ac5_agent_and_read_only(setup):
    settle(setup)
    service = setup[0]
    agent = FinancialManagerAgent(MockLLMClient(), MockPaymentService(), reconciliation_service=service)
    with sqlite3.connect(service.financial.database_path) as db:
        before = list(db.iterdump())
    first = agent.handle(dict(event_id='EV001', action='reconcile_payments'))
    assert first['status'] == 'success' and agent.reconcile_payments('EV001') is True
    assert first['data'] == service.reconcile('EV001')['data']
    with sqlite3.connect(service.financial.database_path) as db:
        assert before == list(db.iterdump())


@pytest.mark.parametrize('kind', ['scope', 'incomplete', 'quote', 'approval', 'booking', 'amount', 'identity'])
def test_ac4_invalid_evidence(setup, kind):
    settle(setup)
    service, context, scope, _ = setup
    if kind == 'scope': service.scope_provider = lambda _: None
    if kind == 'incomplete': scope['scope_complete'] = False
    if kind == 'quote': context['customer_quotation']['customer_quotation_id'] = 'missing'
    if kind == 'approval': context['approval']['approved'] = False
    if kind == 'booking': scope['bookings'][0]['vendor_booking_id'] = 'missing'
    if kind == 'amount': mutate(service, 'vendor_payments', lambda p: p.update(amount_cents=1))
    if kind == 'identity': mutate(service, 'vendor_payments', lambda p: p.update(vendor_id='wrong'))
    result = service.reconcile('EV001')
    assert result['status'] == 'blocked' and result['data']['financial_check_passed'] is False


def test_complete_empty_scope(setup):
    service, _, scope, _ = setup
    scope['bookings'] = []
    result = service.reconcile('EV001')
    assert result['status'] == 'success'
    assert result['data']['vendors']['amount_due_cents'] == 0


def test_read_failure_is_error(setup):
    service = setup[0]
    service.scope_provider = lambda _: (_ for _ in ()).throw(OSError('unavailable'))
    assert service.reconcile('EV001')['status'] == 'error'
    agent = FinancialManagerAgent(MockLLMClient(), MockPaymentService(), reconciliation_service=service)
    with pytest.raises(FinancialStorageError): agent.reconcile_payments('EV001')
