"""Offline KAN-30 approval -> deposit -> final -> restart demonstration."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from examples.customer_quotation_example import generate_customer_quotation
from examples.financial_persistence_example import CountingPayments
from src.agents.financial_manager import FinancialManagerAgent
from src.llm import MockLLMClient
from src.services.financial_record_service import FinancialRecordService


def run_demo():
    request, budget, _ = generate_customer_quotation()
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'financial.sqlite3'
        provider = CountingPayments()
        llm = MockLLMClient()
        llm.set_exception(AssertionError('No LLM payment decisions'))
        worker = FinancialManagerAgent(llm, provider, record_service=FinancialRecordService(path))
        request['budget'] = budget
        quote = worker.handle({**request, 'action': 'generate_customer_quotation'})['data']['customer_quotation']
        approval = {k: quote[k] for k in ('event_id', 'proposal_id', 'quotation_fingerprint', 'customer_quotation_id')}
        approval.update(approved=True, approved_quotation_ids=quote['selected_quotation_ids'])
        request.update(customer_quotation=quote, customer_id='MOCK-CUSTOMER', due_date='2026-12-01', approval=approval)

        def call(action, **fields):
            result = worker.handle({**request, 'action': action, **fields})
            assert result['status'] == 'success', result
            return result['data']

        deposit = call('prepare_deposit_request')['deposit']
        assert provider.calls == 0
        deposit = call('simulate_deposit_payment', simulate=True,
                       deposit_request_id=deposit['deposit_request_id'], amount_cents=deposit['amount_cents'])['deposit']
        before = call('get_customer_balance')['balance']
        pending = call('prepare_final_payment_request')
        final = pending['final_payment']
        assert call('prepare_final_payment_request') == pending
        assert provider.calls == 1
        assert final['amount_cents'] == quote['estimated_total_cents'] - deposit['amount_cents']
        pay = dict(simulate=True, final_request_id=final['final_request_id'], amount_cents=final['amount_cents'])
        paid = call('simulate_final_payment', **pay)
        assert paid['final_payment']['status'] == 'paid'
        assert paid['balance']['balance_cents'] == 0 and provider.calls == 2
        assert call('simulate_final_payment', **pay) == paid
        restarted_provider = CountingPayments()
        worker = FinancialManagerAgent(llm, restarted_provider, record_service=FinancialRecordService(path))
        assert call('simulate_final_payment', **pay) == paid
        restored = call('get_customer_balance')['balance']
        assert restored['balance_cents'] == 0 and restarted_provider.calls == 0
        history = call('get_event_financial_records')
        assert len(history['final_payments']) == 1
        assert not llm.calls
        return dict(status='success', mock=True, quotation_total_cents=quote['estimated_total_cents'],
                    deposit_paid_cents=deposit['amount_cents'], before_final=before,
                    final_paid_cents=final['amount_cents'], restored_balance=restored,
                    payment_calls=provider.calls, restart_payment_calls=restarted_provider.calls,
                    final_execution_state=history['final_payments'][0]['execution_state'])


if __name__ == '__main__':
    print('MOCK ONLY: temporary SQLite, explicit deposit and final payment, no live calls.')
    print(json.dumps(run_demo(), indent=2))
