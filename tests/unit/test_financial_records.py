import sqlite3
import pytest
from src.services.financial_record_service import (
    FinancialRecordService, FinancialRecordConflict, FinancialStorageError,
)


def test_snapshot_identity_restart_conflict(tmp_path):
    path = tmp_path / 'records.db'
    service = FinancialRecordService(path)
    q = dict(event_id='E', proposal_id='P', budget_fingerprint='BF',
             customer_quotation_id='CQ1', generated_at='original', amount=42)
    assert service.save_quotation(q) == q
    retry = dict(q, customer_quotation_id='CQ2', generated_at='later')
    assert FinancialRecordService(path).save_quotation(retry) == q
    with pytest.raises(FinancialRecordConflict):
        service.save_quotation(dict(retry, amount=43))
    assert service.get_event_records('other')['customer_quotations'] == []
    assert service.get_event_records('E', 'P')['customer_quotations'] == [q]


def test_transaction_rollback_and_read_error(tmp_path):
    path = tmp_path / 'records.db'
    service = FinancialRecordService(path)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TRIGGER reject_save BEFORE INSERT ON financial_snapshots "
                   "BEGIN SELECT RAISE(ABORT, 'injected'); END")
    b = dict(event_id='E', proposal_id='P', budget_fingerprint='BF')
    with pytest.raises(FinancialStorageError):
        service.save_budget(b)
    assert service.get_event_records('E')['budgets'] == []
    with sqlite3.connect(path) as db:
        db.execute('DROP TABLE financial_snapshots')
    with pytest.raises(FinancialStorageError):
        service.get_event_records('E')


def test_initialization_error(tmp_path):
    with pytest.raises(FinancialStorageError):
        FinancialRecordService(tmp_path)
