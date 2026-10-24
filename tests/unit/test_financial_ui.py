"""Streamlit reruns must not create approvals, bookings or payments."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.demo.financial_app import FinancialDemoApp

UI = Path(__file__).resolve().parents[2] / 'ui/financial_ui.py'


def click(t, key):
    t.button(key=key).click().run(timeout=30)
    assert not t.exception, t.exception


def test_initial_render_has_no_activity_and_rerun_is_read_only(tmp_path, monkeypatch):
    path = tmp_path / 'page.db'
    monkeypatch.setenv('ELEC5620_DB_PATH', str(path))
    monkeypatch.setenv('ELEC5620_DEPOSIT_RATE', '0.30')
    t = AppTest.from_file(str(UI)).run(timeout=30)
    assert not t.exception
    app = FinancialDemoApp(path)
    assert app.contexts.list_events() == []
    click(t, 'create_demo')
    event = app.contexts.list_events()[0]
    before = app.current_context(event)
    t.run(timeout=30)
    assert app.current_context(event) == before
    assert not app.records.get_event_financial_records(event)['deposits']
    assert not app.procurement_records.all_bookings()


def test_bad_policy_disables_deposit_button(tmp_path, monkeypatch):
    monkeypatch.setenv('ELEC5620_DB_PATH', str(tmp_path / 'bad-policy.db'))
    monkeypatch.setenv('ELEC5620_DEPOSIT_RATE', 'invalid')
    t = AppTest.from_file(str(UI)).run(timeout=30)
    click(t, 'create_demo')
    assert t.button(key='prepare_deposit').disabled
    assert any('ELEC5620_DEPOSIT_RATE' in e.value for e in t.error)
