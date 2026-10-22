"""KAN-29 offline save/restart/retry demonstration; external approval is MOCK."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from examples.customer_quotation_example import generate_customer_quotation
from src.agents.financial_manager import FinancialManagerAgent
from src.llm import MockLLMClient
from src.services.financial_record_service import FinancialRecordService
from src.services.mock_payment_service import MockPaymentService


class CountingPayments(MockPaymentService):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def process_payment(self, payment):
        self.calls += 1
        return super().process_payment(payment)


def run_demo():
    request, _, _ = generate_customer_quotation()
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'financial.sqlite3'
        records = FinancialRecordService(path)
        provider = CountingPayments()
        llm = MockLLMClient()
        llm.set_exception(AssertionError('Persistence demo must not call LLM'))
        worker = FinancialManagerAgent(llm, provider, record_service=records)
        budget = worker.handle(request)
        assert budget['status'] == 'success', budget
        request.update(budget=budget['data'])
        quote_result = worker.handle({**request, 'action': 'generate_customer_quotation'})
        assert quote_result['status'] == 'success', quote_result
        quote = quote_result['data']['customer_quotation']
        approval = {k: quote[k] for k in (
            'event_id', 'proposal_id', 'quotation_fingerprint', 'customer_quotation_id')}
        approval.update(approved=True, approved_quotation_ids=quote['selected_quotation_ids'])
        request.update(customer_quotation=quote, customer_id='MOCK-CUSTOMER',
                       due_date='2026-12-01', approval=approval)
        pending = worker.handle({**request, 'action': 'prepare_deposit_request'})
        assert pending['status'] == 'success', pending
        deposit = pending['data']['deposit']
        pay = {**request, 'action': 'simulate_deposit_payment', 'simulate': True,
               'deposit_request_id': deposit['deposit_request_id'], 'amount_cents': deposit['amount_cents']}
        paid = worker.handle(pay)
        assert paid['status'] == 'success', paid
        assert paid['data']['deposit']['status'] == 'paid' and provider.calls == 1
        new_provider = CountingPayments()
        fresh = FinancialManagerAgent(llm, new_provider, record_service=FinancialRecordService(path))
        assert fresh.handle(pay)['data'] == paid['data']
        assert fresh.handle({**request, 'action': 'prepare_deposit_request'})['data'] == paid['data']
        assert fresh.handle({**request, 'action': 'generate_customer_quotation'})['data'] == quote_result['data']
        query = dict(event_id=request['event_id'], action='get_event_financial_records')
        history = fresh.handle(query)
        assert history['status'] == 'success', history
        assert history['data']['budgets'] == [budget['data']]
        assert history['data']['customer_quotations'] == [quote]
        assert history['data']['deposits'][0]['execution_state'] == 'result_recorded'
        assert new_provider.calls == 0 and not llm.calls
        return dict(status='success', mock=True, restart_payment_calls=new_provider.calls,
                    history=history['data'])


if __name__ == '__main__':
    print('MOCK ONLY: temporary SQLite, external approval fixture, explicit deposit simulation.')
    print(json.dumps(run_demo(), indent=2))
