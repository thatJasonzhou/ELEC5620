"""KAN-32 demonstration: real SQLite Financial records, STUB Operations scope."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from examples.vendor_payment_example import demo_inputs
from src.services.financial_record_service import FinancialRecordService
from src.services.procurement_record_service import ProcurementRecordService
from src.services.vendor_payment_record_service import VendorPaymentRecordService
from src.services.vendor_settlement_service import VendorSettlementService
from src.services.financial_reconciliation_service import FinancialReconciliationService
from src.services.mock_payment_service import MockPaymentService


def setup_demo(path):
    procurement = ProcurementRecordService(path)
    context = demo_inputs(procurement)
    financial = FinancialRecordService(path)
    vendors = VendorPaymentRecordService(path)
    scope = dict(event_id='EV001', settlement_scope_id='STUB-SCOPE-1', scope_complete=True,
                 bookings=[dict(proposal_id='P1', vendor_booking_id='VB1', quotation_id='Q1', vendor_id='V1')])
    reconciliation = FinancialReconciliationService(financial, procurement, vendors,
        context_provider=lambda event_id: context, scope_provider=lambda event_id: scope)
    return reconciliation, context, scope, VendorSettlementService(MockPaymentService(), procurement, vendors)


def main():
    with TemporaryDirectory() as directory:
        service, context, scope, settlement = setup_demo(Path(directory) / 'demo.db')
        before = service.reconcile('EV001')
        payment = settlement.prepare(context)['data']['vendor_payment']
        settlement.simulate_payment({**context, 'simulate': True, 'payment_id': payment['payment_id'],
                                     'amount_cents': payment['amount_cents']})
        after = service.reconcile('EV001')
        assert before['status'] == 'blocked' and after['data']['financial_check_passed']
        print(json.dumps(dict(operations_source='STUB', before=before, after=after)))


if __name__ == '__main__':
    main()
