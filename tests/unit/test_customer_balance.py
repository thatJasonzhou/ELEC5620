"""KAN-30 balance, terminal results, SQLite races and recovery boundaries."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import sqlite3
from threading import Event

import pytest

from test_deposit import deposit_request, pay_request
from src.services.customer_balance_service import CustomerBalanceService
from src.services.deposit_service import DepositService
from src.services.financial_record_service import FinancialRecordService
from src.services.mock_payment_service import MockPaymentService
from src.agents.financial_manager import FinancialManagerAgent
from src.llm import MockLLMClient


class CountingMock(MockPaymentService):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.calls = 0

    def process_payment(self, payment):
        self.calls += 1
        return super().process_payment(payment)


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setenv('ELEC5620_DEPOSIT_RATE', '0.30')
    records = FinancialRecordService(tmp_path / 'finance.db')
    provider = CountingMock()
    return records, provider, DepositService(provider, records), deposit_request()


def final_pay(service, request):
    result = service.prepare(request)
    assert result['status'] == 'success', result
    p = result['data']['final_payment']
    return {**deepcopy(request), 'simulate': True, 'final_request_id': p['final_request_id'],
            'amount_cents': p['amount_cents']}


def test_deposit_deduction_paid_restart_and_no_double_charge(context):
    records, provider, deposit, r = context
    dp = pay_request(deposit, r)
    final = CustomerBalanceService(provider, records)
    assert final.balance(r)['data']['balance']['paid_total_cents'] == 0
    deposit.simulate_payment(dp)
    fp = final_pay(final, r)
    assert fp['amount_cents'] == 845
    before = final.prepare(r)
    assert final.prepare(r) == before
    assert provider.calls == 1
    result = final.simulate_payment(fp)
    assert result['data']['balance']['balance_cents'] == 0
    assert result['data']['final_payment']['status'] == 'paid'
    assert final.simulate_payment(fp) == result
    fresh_provider = CountingMock()
    fresh = CustomerBalanceService(fresh_provider, FinancialRecordService(records.database_path))
    assert fresh.simulate_payment(fp) == result
    assert fresh.prepare(r)['data']['final_payment'] is None
    assert fresh_provider.calls == 0 and provider.calls == 2


def test_changed_balance_stales_old_and_prepares_new(context):
    records, provider, deposit, r = context
    final = CustomerBalanceService(provider, records)
    old = final_pay(final, r)
    deposit.simulate_payment(pay_request(deposit, r))
    new = final_pay(final, r)
    assert new['final_request_id'] != old['final_request_id']
    assert new['amount_cents'] == 845
    assert records.get_final(old['final_request_id'])['execution_state'] == 'stale'
    assert final.simulate_payment(old)['status'] == 'blocked'
    assert provider.calls == 1


def test_balance_change_at_execution_marks_stale(context):
    records, provider, deposit, r = context
    final = CustomerBalanceService(provider, records)
    old = final_pay(final, r)
    deposit.simulate_payment(pay_request(deposit, r))
    assert final.simulate_payment(old)['status'] == 'blocked'
    assert records.get_final(old['final_request_id'])['execution_state'] == 'stale'
    assert provider.calls == 1


@pytest.mark.parametrize('kind', ['deposit', 'final'])
def test_failure_is_durable_terminal_and_replay_never_calls_mock(context, kind):
    records, _, _, r = context
    provider = CountingMock(customer_outcome='failure')
    service = DepositService(provider, records) if kind == 'deposit' else CustomerBalanceService(provider, records)
    pay = pay_request(service, r) if kind == 'deposit' else final_pay(service, r)
    result = service.simulate_payment(pay)
    key = 'deposit' if kind == 'deposit' else 'final_payment'
    assert result['data'][key]['status'] == 'failed'
    assert service.simulate_payment(pay) == result
    new_provider = CountingMock()
    fresh_records = FinancialRecordService(records.database_path)
    fresh = DepositService(new_provider, fresh_records) if kind == 'deposit' else CustomerBalanceService(new_provider, fresh_records)
    assert fresh.simulate_payment(pay) == result
    assert CustomerBalanceService(new_provider, fresh_records).balance(r)['data']['balance']['balance_cents'] == 1207
    if kind == 'final':
        assert fresh.prepare(r)['status'] == 'blocked'
    assert new_provider.calls == 0 and provider.calls == 1


@pytest.mark.parametrize('change', ['low', 'high', 'event', 'customer', 'quote', 'proposal', 'approval', 'simulate', 'unknown'])
def test_invalid_payments_are_blocked_before_provider(context, change):
    records, provider, _, r = context
    final = CustomerBalanceService(provider, records)
    pay = final_pay(final, r)
    if change == 'low': pay['amount_cents'] -= 1
    if change == 'high': pay['amount_cents'] += 1
    if change == 'event': pay['event_id'] = 'other'
    if change == 'customer': pay['customer_id'] = 'other'
    if change == 'quote': pay['customer_quotation']['estimated_total_cents'] += 1
    if change == 'proposal': pay['proposal']['revision'] = 999
    if change == 'approval': pay['approval']['approved'] = False
    if change == 'simulate': pay.pop('simulate')
    if change == 'unknown': pay['final_request_id'] = 'missing'
    assert final.simulate_payment(pay)['status'] == 'blocked'
    assert provider.calls == 0


@pytest.mark.parametrize('first', ['deposit', 'final'])
def test_deposit_and_final_share_transactional_claim(context, first):
    records, provider, deposit, r = context
    final = CustomerBalanceService(provider, records)
    dp, fp = pay_request(deposit, r), final_pay(final, r)
    entered, release = Event(), Event()
    original = provider.process_payment

    def pause(payment):
        entered.set()
        assert release.wait(10)
        return original(payment)

    provider.process_payment = pause
    operation, pay = (deposit, dp) if first == 'deposit' else (final, fp)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(operation.simulate_payment, pay)
        try:
            assert entered.wait(10)
            other_records = FinancialRecordService(records.database_path)
            other_provider = CountingMock()
            other = CustomerBalanceService(other_provider, other_records) if first == 'deposit' else DepositService(other_provider, other_records)
            result = other.simulate_payment(fp if first == 'deposit' else dp)
            assert result['status'] == 'blocked'
            assert other_provider.calls == 0
        finally:
            release.set()
        assert future.result()['status'] == 'success'
    assert provider.calls == 1
    # A committed final payment also prevents a later deposit overcollection.
    if first == 'final':
        assert deposit.simulate_payment(dp)['status'] == 'blocked'
        assert provider.calls == 1


@pytest.mark.parametrize('boundary', ['create', 'claim', 'finish', 'both'])
def test_sqlite_failure_boundaries(context, boundary):
    records, provider, deposit, r = context
    final = CustomerBalanceService(provider, records)
    if boundary != 'create':
        pay = final_pay(final, r)
    trigger = {
        'create': 'BEFORE INSERT ON financial_final_requests',
        'claim': "BEFORE UPDATE ON financial_final_requests WHEN NEW.execution_state='executing'",
        'finish': "BEFORE UPDATE ON financial_final_requests WHEN NEW.execution_state='completed'",
        'both': "BEFORE UPDATE ON financial_final_requests WHEN OLD.execution_state='executing'",
    }[boundary]
    with sqlite3.connect(records.database_path) as db:
        db.execute("CREATE TRIGGER reject_write " + trigger + " BEGIN SELECT RAISE(ABORT,'injected'); END")
    result = final.prepare(r) if boundary == 'create' else final.simulate_payment(pay)
    assert result['status'] == 'error'
    assert provider.calls == (1 if boundary in ('finish', 'both') else 0)
    if boundary in ('finish', 'both'):
        fresh_provider = CountingMock()
        fresh_records = FinancialRecordService(records.database_path)
        fresh = CustomerBalanceService(fresh_provider, fresh_records)
        assert fresh.simulate_payment(pay)['status'] != 'success'
        assert fresh.balance(r)['data']['balance']['paid_total_cents'] == 0
        assert DepositService(fresh_provider, fresh_records).simulate_payment(pay_request(deposit, r))['status'] == 'blocked'
        assert fresh_provider.calls == 0
        assert records.get_final(pay['final_request_id'])['execution_state'] == ('executing' if boundary == 'both' else 'requires_reconciliation')


def test_reapproved_quote_keeps_historical_deposit(context):
    records, provider, deposit, r = context
    deposit.simulate_payment(pay_request(deposit, r))
    llm = MockLLMClient()
    llm.set_exception(AssertionError('No LLM for financial arithmetic'))
    agent = FinancialManagerAgent(llm, provider, record_service=records)
    changed = deepcopy(r)
    changed['proposal']['revision'] = 2
    changed['budget'] = agent.handle({**changed, 'action': 'prepare_budget'})['data']
    quote = agent.handle({**changed, 'action': 'generate_customer_quotation'})['data']['customer_quotation']
    assert quote['customer_quotation_id'] != r['customer_quotation']['customer_quotation_id']
    changed['customer_quotation'] = quote
    changed['approval'].update(customer_quotation_id=quote['customer_quotation_id'])
    final = CustomerBalanceService(provider, records)
    assert final.balance(changed)['data']['balance']['paid_total_cents'] == 362
    assert final_pay(final, changed)['amount_cents'] == 845
    assert not llm.calls


def test_interrupted_execution_blocks_restart(context):
    records, provider, _, r = context
    final = CustomerBalanceService(provider, records)
    pay = final_pay(final, r)
    def crash(payment):
        raise SystemExit('process terminated')
    provider.process_payment = crash
    with pytest.raises(SystemExit):
        final.simulate_payment(pay)
    assert records.get_final(pay['final_request_id'])['execution_state'] == 'requires_reconciliation'
    fresh_provider = CountingMock()
    fresh = CustomerBalanceService(fresh_provider, FinancialRecordService(records.database_path))
    assert fresh.simulate_payment(pay)['status'] != 'success'
    assert fresh_provider.calls == 0


def test_invalid_paid_evidence_does_not_reduce_balance(context):
    records, provider, deposit, r = context
    deposit.simulate_payment(pay_request(deposit, r))
    with sqlite3.connect(records.database_path) as db:
        db.execute("UPDATE financial_deposits SET payload=json_set(payload,'$.deposit.transaction_reference','forged')")
    assert CustomerBalanceService(provider, records).balance(r)['status'] == 'blocked'


def test_final_requires_storage(context):
    _, provider, _, r = context
    agent = FinancialManagerAgent(MockLLMClient(), provider)
    assert agent.handle({**r, 'action': 'prepare_final_payment_request'})['status'] == 'error'
