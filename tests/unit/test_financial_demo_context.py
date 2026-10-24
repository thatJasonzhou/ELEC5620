"""Demo authority, approval and execution boundaries."""
import pytest

from src.demo.financial_app import FinancialDemoApp
from src.services.mock_payment_service import MockPaymentService


class CountingPayments(MockPaymentService):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.calls = 0

    def process_payment(self, payment):
        self.calls += 1
        return super().process_payment(payment)


def ok(result):
    assert result['status'] == 'success', result
    return result['data']


def approved(app):
    ctx = ok(app.create_demo())
    event = ctx['event_id']
    ok(app.request_quotations(event))
    ctx = ok(app.load_demo(event))
    ids = [q['quotation_id'] for q in ctx['quotations'] if q['available']]
    ok(app.update_selection(event, ids, 3000000, ctx['revision']))
    ok(app.prepare_budget(event))
    quote = ok(app.generate_customer_quotation(event))['customer_quotation']
    ctx = ok(app.load_demo(event))
    ok(app.approve_customer_quotation(event, quote['customer_quotation_id'], ctx['revision']))
    return event


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('ELEC5620_DEPOSIT_RATE', '0.30')
    return FinancialDemoApp(tmp_path / 'demo.sqlite3', payment_service=CountingPayments())


def test_creation_and_load_never_collect_or_book(app):
    ctx = ok(app.create_demo())
    event = ctx['event_id']
    assert ctx['approval'] is None
    assert not ok(app.get_history(event))['deposits']
    assert not app.procurement_records.all_bookings()
    assert app.payments.calls == 0
    assert app.create_operations_stub(event)['status'] == 'blocked'
    assert app.confirm_bookings(event)['status'] == 'blocked'
    assert app.reconcile(event)['status'] == 'blocked'


def test_approval_invalidated_and_stale_submit_blocked(app):
    event = approved(app)
    old = ok(app.load_demo(event))
    quote_id = old['customer_quotation']['customer_quotation_id']
    changed = ok(app.update_selection(event, old['selected_quotation_ids'], 1, old['revision']))
    assert changed['approval'] is None and changed['budget'] is None
    assert app.approve_customer_quotation(event, quote_id, old['revision'])['status'] == 'blocked'
    assert app.prepare_budget(event)['status'] == 'blocked'
    assert app.generate_customer_quotation(event)['status'] == 'blocked'
    assert app.prepare_deposit(event)['status'] == 'blocked'
    assert app.payments.calls == 0
    assert len(ok(app.get_history(event))['customer_quotations']) == 1


def test_revision_compare_and_swap(app):
    event = approved(app)
    ctx = ok(app.load_demo(event))
    assert app.update_selection(event, ctx['selected_quotation_ids'], 3000000, ctx['revision'] - 1)['status'] == 'blocked'
    assert ok(app.load_demo(event))['approval'] == ctx['approval']


def test_deposit_preparation_freezes_context_without_paying(app):
    event = approved(app)
    deposit = ok(app.prepare_deposit(event))['deposit']
    assert deposit['status'] == 'pending' and app.payments.calls == 0
    ctx = ok(app.load_demo(event))
    assert app.update_selection(event, ctx['selected_quotation_ids'], 1, ctx['revision'])['status'] == 'blocked'
    assert app.confirm_bookings(event)['status'] == 'blocked'


def test_missing_policy_does_not_create_request(app, monkeypatch):
    event = approved(app)
    monkeypatch.setenv('ELEC5620_DEPOSIT_RATE', 'invalid')
    assert app.prepare_deposit(event)['status'] != 'success'
    assert not ok(app.get_history(event))['deposits']


def test_storage_failure_is_error(app, monkeypatch):
    event = approved(app)
    import sqlite3
    def broken(*args):
        raise sqlite3.OperationalError('unavailable')
    monkeypatch.setattr(app.contexts, 'load', broken)
    assert app.load_demo(event)['status'] == 'error'


def test_failed_customer_payment_never_books(tmp_path, monkeypatch):
    monkeypatch.setenv('ELEC5620_DEPOSIT_RATE', '0.30')
    app = FinancialDemoApp(tmp_path / 'failure.db', payment_service=CountingPayments(customer_outcome='failure'))
    event = approved(app)
    request = ok(app.prepare_deposit(event))['deposit']
    result = app.pay_deposit(event, request['deposit_request_id'], request['amount_cents'])
    assert result['data']['deposit']['status'] == 'failed'
    assert app.confirm_bookings(event)['status'] == 'blocked'
    app.pay_deposit(event, request['deposit_request_id'], request['amount_cents'])
    assert app.payments.calls == 1
