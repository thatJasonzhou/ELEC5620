"""Offline page acceptance, real SQLite, Operations explicitly STUB."""
from streamlit.testing.v1 import AppTest

from src.demo.financial_app import FinancialDemoApp
from tests.unit.test_financial_ui import UI, click


def test_page_full_flow_and_new_session_restore(tmp_path, monkeypatch):
    path = tmp_path / 'page-flow.db'
    monkeypatch.setenv('ELEC5620_DB_PATH', str(path))
    monkeypatch.setenv('ELEC5620_DEPOSIT_RATE', '0.30')
    t = AppTest.from_file(str(UI)).run(timeout=30)
    click(t, 'create_demo')
    click(t, 'request_quotes')
    submit = next(b for b in t.button if b.label == 'Save selection and budget')
    submit.click().run(timeout=30)
    assert not t.exception
    click(t, 'budget')
    click(t, 'quote')
    click(t, 'approve')
    click(t, 'prepare_deposit')
    click(t, 'pay_deposit')
    assert t.button(key='pay_deposit').disabled
    click(t, 'book')
    click(t, 'operations')
    app = FinancialDemoApp(path)
    event = app.contexts.list_events()[0]
    ctx = app.current_context(event)
    booking = app.procurement_records.get_bookings(event, ctx['proposal_id'])[0]
    # Customer deposit alone cannot fund supplier settlement.
    click(t, 'prepare_vendor_' + booking['booking_id'])
    assert t.warning
    click(t, 'prepare_final')
    final = app.records.get_event_financial_records(event)['final_payments'][0]['payment']
    click(t, 'pay_final_' + final['final_request_id'])
    click(t, 'prepare_vendor_' + booking['booking_id'])
    payment = app.vendor_records.get_for_event(event)[0]
    click(t, 'pay_vendor_' + payment['payment_id'])
    click(t, 'reconcile')
    assert any('Financial check passed within' in s.value for s in t.success)
    history = app.records.get_event_financial_records(event)
    t.run(timeout=30)
    assert not t.exception
    assert app.records.get_event_financial_records(event) == history
    # A new page session has no form/session-state history to recover from.
    restored = AppTest.from_file(str(UI)).run(timeout=30)
    assert not restored.exception
    assert restored.button(key='pay_deposit').disabled
    click(restored, 'reconcile')
    assert any('Financial check passed within' in s.value for s in restored.success)
