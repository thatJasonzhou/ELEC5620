"""Financial/persistence integration only; Operations scope is a STUB."""
import sqlite3
import pytest
from examples.financial_reconciliation_example import setup_demo


def test_single_snapshot_read_only_and_restart(tmp_path):
    path = tmp_path / 'demo.db'
    service, context, scope, settlement = setup_demo(path)
    payment = settlement.prepare(context)['data']['vendor_payment']
    settlement.simulate_payment({**context, 'simulate': True, 'payment_id': payment['payment_id'],
                                 'amount_cents': payment['amount_cents']})
    first = service.reconcile('EV001')
    assert first['status'] == 'success'
    with service.financial.reconciliation_snapshot() as db:
        assert db.execute('PRAGMA query_only').fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            db.execute('DELETE FROM vendor_payments')
    from src.services.financial_record_service import FinancialRecordService
    from src.services.financial_reconciliation_service import FinancialReconciliationService
    from src.services.vendor_payment_record_service import VendorPaymentRecordService
    from src.services.procurement_record_service import ProcurementRecordService
    fresh = FinancialReconciliationService(FinancialRecordService(path), ProcurementRecordService(path),
        VendorPaymentRecordService(path), context_provider=lambda _: context, scope_provider=lambda _: scope)
    assert fresh.reconcile('EV001') == first
