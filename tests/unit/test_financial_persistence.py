"""KAN-29 restart, immutable identities, execution journal and failure boundaries."""
from copy import deepcopy
import sqlite3
import pytest

from test_deposit import deposit_request, pay_request
from src.agents.financial_manager import FinancialManagerAgent
from src.llm import MockLLMClient
from src.services.customer_quotation_service import CustomerQuotationService, budget_fingerprint
from src.services.deposit_service import DepositService
from src.services.financial_record_service import FinancialRecordService, FinancialRecordConflict, FinancialStorageError
from src.services.mock_payment_service import MockPaymentService
from src.services.vendor_payment_record_service import VendorPaymentRecordService, VendorPaymentStorageError


class CountingMock(MockPaymentService):
    def __init__(self):
        super().__init__()
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


def test_restart_paid_and_current_approval(context):
    records, provider, service, request = context
    pay = pay_request(service, request)
    paid = service.simulate_payment(pay)
    assert paid['data']['deposit']['status'] == 'paid'
    assert provider.calls == 1
    fresh_provider = CountingMock()
    reopened = FinancialRecordService(records.database_path)
    fresh = DepositService(fresh_provider, reopened)
    assert fresh.simulate_payment(pay) == paid
    assert fresh.prepare(request) == paid
    assert fresh.records == [paid['data']['deposit']]
    assert fresh_provider.calls == 0
    assert reopened.get_deposit(pay['deposit_request_id'])['execution_state'] == 'result_recorded'
    revoked = deepcopy(pay)
    revoked['approval']['approved'] = False
    assert fresh.simulate_payment(revoked)['status'] == 'blocked'
    assert fresh.prepare(revoked)['status'] == 'blocked'
    assert fresh_provider.calls == 0


@pytest.mark.parametrize('field,value', [('due_date', '2026-12-02'), ('amount', 1), ('quote', 1)])
def test_deposit_immutable_conflict(context, field, value):
    records, provider, service, request = context
    pending = service.prepare(request)
    saved = records.get_deposit(pending['data']['deposit']['deposit_request_id'])
    modified = deepcopy(saved)
    if field == 'due_date':
        modified[field] = value
        assert service.prepare({**request, field: value})['status'] == 'blocked'
    elif field == 'amount':
        modified['deposit']['amount_cents'] += value
    else:
        modified['quote']['estimated_total_cents'] += value
    with pytest.raises(FinancialRecordConflict):
        records.create_deposit(modified)
    assert provider.calls == 0
    assert records.get_deposit(saved['deposit']['deposit_request_id']) == saved


def test_customer_identity_cannot_reuse_request_id(context):
    records, provider, service, request = context
    pay = pay_request(service, request)
    saved = records.get_deposit(pay['deposit_request_id'])
    saved['customer_id'] = 'OTHER'
    with pytest.raises(FinancialRecordConflict):
        records.create_deposit(saved)
    assert service.simulate_payment({**pay, 'customer_id': 'OTHER'})['status'] == 'blocked'
    assert provider.calls == 0


def test_quotation_pure_validation_and_reuse(context, monkeypatch):
    records, provider, service, request = context
    quotes = CustomerQuotationService(records)
    original = quotes.generate(request)['data']['customer_quotation']
    assert quotes.generate(request)['data']['customer_quotation'] == original
    assert CustomerQuotationService(FinancialRecordService(records.database_path)).generate(
        request)['data']['customer_quotation'] == original
    def forbidden():
        raise AssertionError('Validation must not generate UUID')
    monkeypatch.setattr('src.services.customer_quotation_service.uuid4', forbidden)
    assert service.prepare(request)['status'] == 'success'
    assert len(records.get_event_records(request['event_id'])['customer_quotations']) == 1
    stale = deepcopy(request)
    stale['event']['budget_limit_cents'] += 1
    assert quotes.generate(stale)['status'] == 'blocked'
    assert provider.calls == 0


@pytest.mark.parametrize('boundary', ['create', 'start', 'finish'])
def test_sqlite_write_failure_boundaries(context, boundary):
    records, provider, service, request = context
    if boundary != 'create':
        pay = pay_request(service, request)
    trigger = {
        'create': 'BEFORE INSERT ON financial_deposits',
        'start': "BEFORE UPDATE OF execution_state ON financial_deposits WHEN NEW.execution_state='execution_started'",
        'finish': "BEFORE UPDATE OF payload ON financial_deposits WHEN NEW.execution_state='result_recorded'",
    }[boundary]
    with sqlite3.connect(records.database_path) as db:
        db.execute("CREATE TRIGGER reject_write " + trigger + " BEGIN SELECT RAISE(ABORT, 'injected'); END")
    result = service.prepare(request) if boundary == 'create' else service.simulate_payment(pay)
    assert result['status'] == 'error' and result['data'] == {}
    assert provider.calls == (1 if boundary == 'finish' else 0)
    if boundary == 'create':
        assert records.get_event_records(request['event_id'])['deposits'] == []
    else:
        saved = records.get_deposit(pay['deposit_request_id'])
        assert saved['deposit']['status'] == 'pending'
        assert saved['execution_state'] == ('requires_reconciliation' if boundary == 'finish' else 'not_started')
        if boundary == 'finish':
            fresh_provider = CountingMock()
            fresh = DepositService(fresh_provider, FinancialRecordService(records.database_path))
            assert fresh.simulate_payment(pay)['status'] == 'error'
            assert fresh_provider.calls == 0


def test_crash_after_start_blocks_restart(context, monkeypatch):
    records, provider, service, request = context
    pay = pay_request(service, request)
    def crash(payment):
        raise SystemExit('simulated process termination')
    monkeypatch.setattr(provider, 'process_payment', crash)
    with pytest.raises(SystemExit):
        service.simulate_payment(pay)
    assert records.get_deposit(pay['deposit_request_id'])['execution_state'] == 'requires_reconciliation'
    fresh_provider = CountingMock()
    fresh = DepositService(fresh_provider, FinancialRecordService(records.database_path))
    assert fresh.simulate_payment(pay)['status'] == 'error'
    assert fresh_provider.calls == 0


def test_outcome_and_reconciliation_save_both_fail(context):
    records, provider, service, request = context
    pay = pay_request(service, request)
    with sqlite3.connect(records.database_path) as db:
        db.execute("CREATE TRIGGER reject_finish BEFORE UPDATE ON financial_deposits "
                   "WHEN OLD.execution_state='execution_started' BEGIN SELECT RAISE(ABORT, 'injected'); END")
    assert service.simulate_payment(pay)['status'] == 'error'
    assert records.get_deposit(pay['deposit_request_id'])['execution_state'] == 'execution_started'
    assert service.simulate_payment(pay)['status'] == 'error'
    assert provider.calls == 1


def test_provider_exception_requires_reconciliation(context, monkeypatch):
    records, provider, service, request = context
    pay = pay_request(service, request)
    def fail(payment):
        provider.calls += 1
        raise OSError('unknown execution outcome')
    monkeypatch.setattr(provider, 'process_payment', fail)
    assert service.simulate_payment(pay)['status'] == 'error'
    assert service.simulate_payment(pay)['status'] == 'error'
    assert records.get_deposit(pay['deposit_request_id'])['execution_state'] == 'requires_reconciliation'
    assert provider.calls == 1


def test_agent_budget_quote_restore_and_query(context):
    records, provider, _, request = context
    agent = FinancialManagerAgent(MockLLMClient(), provider, record_service=records)
    budget = agent.handle({**request, 'action': 'prepare_budget'})
    assert budget['status'] == 'success'
    quote = agent.handle({**request, 'action': 'generate_customer_quotation'})
    fresh = FinancialManagerAgent(MockLLMClient(), CountingMock(),
                                  record_service=FinancialRecordService(records.database_path))
    history = fresh.handle(dict(event_id=request['event_id'], action='get_event_financial_records'))
    assert history['data']['budgets'] == [budget['data']]
    assert history['data']['customer_quotations'] == [quote['data']['customer_quotation']]
    empty = fresh.handle(dict(event_id='OTHER', action='get_event_financial_records'))
    assert empty['status'] == 'success' and all(v == [] for v in empty['data'].values())
    with sqlite3.connect(records.database_path) as db:
        db.execute('DROP TABLE financial_snapshots')
    assert fresh.handle(dict(event_id='OTHER', action='get_event_financial_records'))['status'] == 'error'


def test_vendor_event_query_no_migration(context):
    records, _, _, request = context
    vendors = VendorPaymentRecordService(records.database_path)
    record = dict(payment_id='VP', vendor_booking_id='VB', vendor_id='V', invoice_number='INV',
                  status='pending', event_id=request['event_id'], proposal_id='P1')
    vendors.create(record)
    with sqlite3.connect(records.database_path) as db:
        columns = list(db.execute('PRAGMA table_info(vendor_payments)'))
    assert vendors.get_for_event(request['event_id'], 'P1') == [record]
    assert vendors.get_for_event(request['event_id'], 'OTHER') == []
    assert records.get_event_financial_records(request['event_id'])['vendor_payments'] == [record]
    with sqlite3.connect(records.database_path) as db:
        assert list(db.execute('PRAGMA table_info(vendor_payments)')) == columns
        db.execute("UPDATE vendor_payments SET payload='invalid JSON'")
    with pytest.raises(VendorPaymentStorageError):
        records.get_event_financial_records(request['event_id'])


def test_budget_fingerprint_stays_list_order_sensitive(context):
    _, _, _, request = context
    budget = deepcopy(request['budget'])
    budget['selected_quotation_ids'] = ['Q1', 'Q2']
    a = budget_fingerprint(budget)
    budget['selected_quotation_ids'].reverse()
    assert budget_fingerprint(budget) != a


def test_env_and_schema_version(context, monkeypatch):
    records, _, _, request = context
    monkeypatch.setenv('ELEC5620_DB_PATH', str(records.database_path))
    assert FinancialRecordService.from_env().database_path == records.database_path
    records.save_budget(request['budget'])
    with sqlite3.connect(records.database_path) as db:
        db.execute('UPDATE financial_snapshots SET schema_version=99')
    with pytest.raises(FinancialStorageError):
        records.get_event_records(request['event_id'])


def test_pending_restart_preserves_ids_and_timestamp(context):
    records, _, service, request = context
    pending = service.prepare(request)
    provider = CountingMock()
    fresh = DepositService(provider, FinancialRecordService(records.database_path))
    assert fresh.prepare(request) == pending
    pay = pay_request(fresh, request)
    assert fresh.simulate_payment(pay)['data']['deposit']['status'] == 'paid'
    assert provider.calls == 1


def test_agent_snapshot_save_failure_returns_error(context):
    records, provider, _, request = context
    with sqlite3.connect(records.database_path) as db:
        db.execute("CREATE TRIGGER reject_snapshot BEFORE INSERT ON financial_snapshots "
                   "BEGIN SELECT RAISE(ABORT, 'injected'); END")
    agent = FinancialManagerAgent(MockLLMClient(), provider, record_service=records)
    for action in ('prepare_budget', 'generate_customer_quotation'):
        result = agent.handle({**request, 'action': action})
        assert result['status'] == 'error' and result['data'] == {}
    assert records.get_event_records(request['event_id'])['budgets'] == []
    assert records.get_event_records(request['event_id'])['customer_quotations'] == []


def test_history_query_does_not_initialize_vendor_table(context):
    records, _, _, request = context
    assert records.get_event_financial_records(request['event_id'])['vendor_payments'] == []
    with sqlite3.connect(records.database_path) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='vendor_payments'").fetchone() is None


def test_corrupt_deposit_read_is_error(context):
    records, _, service, request = context
    pay = pay_request(service, request)
    with sqlite3.connect(records.database_path) as db:
        db.execute("UPDATE financial_deposits SET payload='invalid JSON'")
    assert service.simulate_payment(pay)['status'] == 'error'
    with pytest.raises(FinancialStorageError):
        records.get_event_records(request['event_id'])
