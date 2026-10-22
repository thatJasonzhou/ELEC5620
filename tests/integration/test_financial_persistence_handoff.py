from examples.financial_persistence_example import run_demo
from examples.vendor_payment_example import demo_inputs
from src.services.financial_record_service import FinancialRecordService
from src.services.mock_payment_service import MockPaymentService
from src.services.procurement_record_service import ProcurementRecordService
from src.services.vendor_payment_record_service import VendorPaymentRecordService
from src.services.vendor_settlement_service import VendorSettlementService


def test_agent_save_restart_retry(monkeypatch):
    monkeypatch.setenv('ELEC5620_DEPOSIT_RATE', '0.30')
    result = run_demo()
    assert result['restart_payment_calls'] == 0
    assert result['history']['deposits'][0]['deposit']['status'] == 'paid'


def test_existing_vendor_settlement_in_financial_history(tmp_path):
    path = tmp_path / 'shared.sqlite3'
    procurement = ProcurementRecordService(path)
    request = demo_inputs(procurement)
    vendor_records = VendorPaymentRecordService(path)
    settlement = VendorSettlementService(MockPaymentService(), procurement, vendor_records)
    pending = settlement.prepare(request)['data']['vendor_payment']
    paid = settlement.simulate_payment({**request, 'simulate': True,
        'payment_id': pending['payment_id'], 'amount_cents': pending['amount_cents']})
    assert paid['status'] == 'success'
    records = FinancialRecordService(path)
    history = records.get_event_financial_records(request['event_id'], request['proposal_id'])
    assert history['vendor_payments'] == [paid['data']['vendor_payment']]
    assert history['budgets'] == [] and history['deposits'] == []
    assert procurement.get_bookings(request['event_id'], request['proposal_id'])
