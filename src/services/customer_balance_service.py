"""Deterministic, durable customer balance and explicit final payment workflow."""
from copy import deepcopy
from datetime import date, datetime, timezone
from uuid import uuid4

from src.services.deposit_service import DepositService
from src.services.financial_record_service import canonical, FinancialRecordService
from src.shared.schemas import CustomerPayment, require_int, require_non_empty_str


class CustomerBalanceService:
    def __init__(self, payment_service, record_service):
        if not isinstance(record_service, FinancialRecordService):
            raise TypeError('Final payments require persistent FinancialRecordService')
        self._validator = DepositService(payment_service, record_service)
        self._payments = payment_service
        self._records = record_service

    def balance(self, request):
        return self._run(request, 'balance')

    def prepare(self, request):
        return self._run(request, 'prepare')

    def simulate_payment(self, request):
        return self._run(request, 'pay')

    def _result(self, saved, quote, customer):
        balance = self._records.customer_balance(quote, customer)
        return dict(status='success', message='Mock customer balance', data=dict(
            balance=balance, final_payment=deepcopy(saved['payment']) if saved else None,
            execution_state=saved['execution_state'] if saved else None))

    def _run(self, request, operation):
        try:
            if not isinstance(request, dict):
                raise ValueError('request must be an object')
            quote = self._validator._validate(request)
            customer = request['customer_id']
            if operation == 'balance':
                return self._result(None, quote, customer)
            if operation == 'prepare':
                now = datetime.now(timezone.utc).isoformat()
                payment = {key: quote[key] for key in (
                    'event_id', 'proposal_id', 'customer_quotation_id', 'quotation_fingerprint')}
                payment.update(final_request_id='FR-' + uuid4().hex, payment_id='CP-' + uuid4().hex,
                               payment_type='final', status='pending', mock=True, created_at=now)
                saved = dict(quote=deepcopy(quote), customer_id=customer, due_date=request['due_date'],
                             payment=payment, execution_state='prepared')
                saved, _ = self._records.prepare_final(saved)
                return self._result(saved, quote, customer)
            if request.get('simulate') is not True:
                raise ValueError('Explicit simulate=true required')
            token = require_non_empty_str(request.get('final_request_id'), 'final_request_id')
            amount = require_int(request.get('amount_cents'), 'amount_cents', minimum=1)
            saved = self._records.get_final(token)
            if saved is None:
                raise ValueError('Unknown final_request_id')
            payment = saved['payment']
            if (canonical(saved['quote']) != canonical(quote) or saved['customer_id'] != customer
                    or saved['due_date'] != request['due_date'] or payment['amount_cents'] != amount):
                raise ValueError('Final request, quotation, customer or amount mismatch')
            if saved['execution_state'] == 'completed' and payment['status'] in ('paid', 'failed'):
                return self._result(saved, quote, customer)
            if saved['execution_state'] != 'prepared':
                raise ValueError('Final request stale, executing or requires reconciliation')
            if not self._records.start_final(token):
                raise ValueError('Final request is stale because balance changed')
            try:
                entity = CustomerPayment(payment_id=payment['payment_id'], event_id=payment['event_id'],
                    amount_cents=amount, status='pending', created_at=datetime.fromisoformat(payment['created_at']),
                    customer_id=customer, payment_type='final', due_date=date.fromisoformat(saved['due_date']))
                reply = self._payments.process_payment(entity)
                if (not isinstance(reply, dict) or reply.get('status') not in ('paid', 'failed')
                        or reply.get('mock') is not True or reply.get('payment_id') != entity.payment_id
                        or type(reply.get('amount_cents')) is not int or reply['amount_cents'] != amount):
                    raise RuntimeError('Mismatched payment evidence')
                now = datetime.now(timezone.utc).isoformat()
                if reply['status'] == 'paid':
                    if reply.get('transaction_reference') != 'MOCK-' + entity.payment_id:
                        raise RuntimeError('Missing matching payment reference')
                    payment.update(status='paid', paid_at=now, transaction_reference=reply['transaction_reference'])
                else:
                    reason = require_non_empty_str(reply.get('failure_reason'), 'failure_reason')
                    payment.update(status='failed', failed_at=now, failure_reason=reason, transaction_reference=None)
                saved['execution_state'] = 'completed'
                self._records.finish_final(saved)
            except BaseException as exc:
                self._records.uncertain_final(token)
                if not isinstance(exc, Exception):
                    raise
                raise RuntimeError('Payment outcome uncertain; reconciliation required') from None
            return self._result(saved, quote, customer)
        except (ValueError, KeyError, TypeError) as exc:
            return dict(status='blocked', message=str(exc), data={})
        except (RuntimeError, OSError):
            return dict(status='error', message='Customer collection failed; review required', data={})
