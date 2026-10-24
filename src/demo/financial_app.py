"""Single-operator demo coordinator. Monetary decisions remain in Services."""
from copy import deepcopy
from functools import wraps
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from src.agents.financial_manager import FinancialManagerAgent
from src.agents.vendor_procurement_manager import VendorProcurementManagerAgent
from src.demo.context_service import DemoContextService, now
from src.demo.operations_stub import DemoOperationsStub
from src.llm import MockLLMClient
from src.services.financial_record_service import FinancialRecordService
from src.services.financial_reconciliation_service import FinancialReconciliationService
from src.services.mock_payment_service import MockPaymentService
from src.services.procurement_record_service import ProcurementRecordService
from src.services.vendor_booking_service import VendorBookingService, MockVendorBookingService
from src.services.vendor_payment_record_service import VendorPaymentRecordService
from src.services.vendor_procurement_service import VendorProcurementService
from src.services.vendor_quotation_service import MockVendorQuotationService
from src.services.vendor_settlement_service import VendorSettlementService
from src.shared.schemas import require_int

ROOT = Path(__file__).resolve().parents[2]


def operation(fn):
    @wraps(fn)
    def wrapped(self, *args, **kwargs):
        event_id = args[0] if args else None
        try:
            result = fn(self, *args, **kwargs)
            if isinstance(result, dict) and 'status' in result and 'agent' in result:
                return result
            return self.finance.envelope(event_id, 'success', 'Demo operation complete', result)
        except (sqlite3.Error, OSError, RuntimeError, json.JSONDecodeError):
            return self.finance.envelope(event_id, 'error', 'Storage or execution failed; manual review required')
        except (ValueError, KeyError, TypeError) as exc:
            return self.finance.envelope(event_id, 'blocked', str(exc))
    return wrapped


class FinancialDemoApp:
    def __init__(self, database_path=None, *, payment_service=None):
        raw = database_path or os.environ.get('ELEC5620_DB_PATH') or ROOT / 'runtime/financial-demo.sqlite3'
        self.database_path = Path(raw).resolve()
        self.contexts = DemoContextService(self.database_path)
        self.records = FinancialRecordService(self.database_path)
        self.procurement_records = ProcurementRecordService(self.database_path)
        self.vendor_records = VendorPaymentRecordService(self.database_path)
        self.payments = payment_service or MockPaymentService()
        self.llm = MockLLMClient()
        self.llm.set_exception(AssertionError('Financial demo must not call an LLM'))
        self.operations = DemoOperationsStub(self.contexts, self.procurement_records)
        reconciliation = FinancialReconciliationService(self.records, self.procurement_records,
            self.vendor_records, context_provider=self.current_context, scope_provider=self.operations.get_scope)
        self.finance = FinancialManagerAgent(self.llm, self.payments, record_service=self.records,
            settlement_service=VendorSettlementService(self.payments, self.procurement_records, self.vendor_records),
            reconciliation_service=reconciliation)
        self.procurement = VendorProcurementManagerAgent(self.llm,
            VendorProcurementService.from_json_file(ROOT / 'data/vendor_catalog.json'),
            MockVendorQuotationService.from_json_file(ROOT / 'data/mock_vendor_quotations.json'),
            VendorBookingService(MockVendorBookingService.from_json_file(ROOT / 'data/mock_vendor_bookings.json'),
                                 record_service=self.procurement_records), record_service=self.procurement_records)

    def current_context(self, event_id):
        ctx = self.contexts.load(event_id)
        ctx['quotations'] = self.procurement_records.get_quotations(event_id, ctx['proposal_id'])
        return ctx

    def _call(self, event_id, action, **fields):
        return self.finance.handle({**self.current_context(event_id), **fields, 'action': action})

    def _unfrozen(self, event_id):
        history = self.records.get_event_financial_records(event_id)
        if history['deposits'] or history['final_payments'] or self.procurement_records.get_bookings(
                event_id, self.contexts.load(event_id)['proposal_id']):
            raise ValueError('Demo context frozen after a payment request; create a new demo to change it')

    @operation
    def create_demo(self):
        token = uuid4().hex[:12]
        event_id, proposal_id = 'DEMO-' + token, 'P-' + token
        return self.contexts.create(dict(schema_version=1, source='PLANNING_STUB', event_id=event_id,
            proposal_id=proposal_id, customer_id='MOCK-C-' + token, due_date='2026-12-01',
            event=dict(event_id=event_id, event_date='2026-12-05', guest_count=120,
                       location='Melbourne', budget_limit_cents=3000000),
            proposal=dict(event_id=event_id, proposal_id=proposal_id, required_services=['catering']),
            selected_quotation_ids=[], budget=None, customer_quotation=None, approval=None))

    @operation
    def load_demo(self, event_id):
        return self.current_context(event_id)

    @operation
    def request_quotations(self, event_id):
        ctx = self.current_context(event_id)
        self._unfrozen(event_id)
        return self.procurement.request_quotations(dict(event_id=event_id, proposal_id=ctx['proposal_id'],
            service_type='catering', event_date=ctx['event']['event_date'], guest_count=120, location='Melbourne'))

    @operation
    def update_selection(self, event_id, selected_ids, budget_limit_cents, expected_revision):
        self._unfrozen(event_id)
        ctx = self.current_context(event_id)
        require_int(budget_limit_cents, 'budget_limit_cents', minimum=1)
        eligible = {q['quotation_id'] for q in ctx['quotations'] if q.get('available') is True}
        if not isinstance(selected_ids, list) or len(selected_ids) != 1 or selected_ids[0] not in eligible:
            raise ValueError('Select exactly one available mock quotation')
        ctx.pop('quotations')
        ctx.update(selected_quotation_ids=selected_ids, budget=None, customer_quotation=None, approval=None)
        ctx.pop('approval_audit', None)
        ctx['event']['budget_limit_cents'] = budget_limit_cents
        return self.contexts.save(ctx, expected_revision)

    @operation
    def prepare_budget(self, event_id):
        ctx = self.contexts.load(event_id)
        result = self._call(event_id, 'prepare_budget')
        if result['data'].get('budget_valid'):
            if ctx['budget'] != result['data']:
                ctx.update(budget=result['data'], customer_quotation=None, approval=None)
                self.contexts.save(ctx, ctx['revision'])
        return result

    @operation
    def generate_customer_quotation(self, event_id):
        ctx = self.contexts.load(event_id)
        result = self._call(event_id, 'generate_customer_quotation')
        if result['status'] == 'success':
            quote = result['data']['customer_quotation']
            if ctx['customer_quotation'] != quote:
                ctx.update(customer_quotation=quote, approval=None)
                self.contexts.save(ctx, ctx['revision'])
        return result

    @operation
    def approve_customer_quotation(self, event_id, customer_quotation_id, expected_revision):
        ctx = self.contexts.load(event_id)
        quote = ctx['customer_quotation']
        if not quote or quote['customer_quotation_id'] != customer_quotation_id:
            raise ValueError('Current customer quotation required')
        validation = self._call(event_id, 'generate_customer_quotation')
        if validation['status'] != 'success':
            return validation
        ctx['approval'] = {k: quote[k] for k in (
            'event_id', 'proposal_id', 'customer_quotation_id', 'quotation_fingerprint')}
        ctx['approval'].update(approved=True, approved_quotation_ids=quote['selected_quotation_ids'])
        ctx['approval_audit'] = dict(source='DEMO_USER', approved_at=now(), revision=expected_revision)
        return self.contexts.save(ctx, expected_revision)

    @operation
    def prepare_deposit(self, event_id):
        return self._call(event_id, 'prepare_deposit_request')

    @operation
    def pay_deposit(self, event_id, deposit_request_id, amount_cents):
        return self._call(event_id, 'simulate_deposit_payment', simulate=True,
                          deposit_request_id=deposit_request_id, amount_cents=amount_cents)

    @operation
    def confirm_bookings(self, event_id):
        ctx = self.current_context(event_id)
        # Reuse the Financial validation of the original current approval and quotation.
        checked = self._call(event_id, 'get_customer_balance')
        if checked['status'] != 'success':
            return checked
        saved = [r for r in self.records.get_event_financial_records(event_id)['deposits']
                 if r['quote']['customer_quotation_id'] == ctx['customer_quotation']['customer_quotation_id']]
        if len(saved) != 1 or saved[0]['deposit']['status'] != 'paid' or saved[0]['execution_state'] != 'result_recorded':
            raise ValueError('A durable successful deposit is required before booking')
        deposit = saved[0]['deposit']
        selected = {q['quotation_id']: q for q in ctx['quotations']}
        return self.procurement.confirm_bookings(dict(event_id=event_id, proposal_id=ctx['proposal_id'],
            quotations=[selected[i] for i in ctx['selected_quotation_ids']], approval=ctx['approval'],
            budget={**deepcopy(ctx['budget']), 'deposit_due_cents': deposit['amount_cents']}, deposit=deposit))

    @operation
    def get_customer_balance(self, event_id):
        return self._call(event_id, 'get_customer_balance')

    @operation
    def prepare_final(self, event_id):
        return self._call(event_id, 'prepare_final_payment_request')

    @operation
    def pay_final(self, event_id, final_request_id, amount_cents):
        return self._call(event_id, 'simulate_final_payment', simulate=True,
                          final_request_id=final_request_id, amount_cents=amount_cents)

    @operation
    def create_operations_stub(self, event_id):
        return self.operations.create(event_id)

    def _evidence(self, event_id, booking_id):
        saved = self.operations.get(event_id)
        if not saved or booking_id not in saved['evidence']:
            raise ValueError('Generate explicit Operations STUB evidence first')
        return saved['evidence'][booking_id]

    @operation
    def prepare_vendor_payment(self, event_id, booking_id):
        return self._call(event_id, 'prepare_vendor_payment_request', **self._evidence(event_id, booking_id))

    @operation
    def pay_vendor(self, event_id, payment_id, amount_cents):
        saved = next((r for r in self.vendor_records.get_for_event(event_id) if r['payment_id'] == payment_id), None)
        if saved is None:
            raise ValueError('Unknown vendor payment')
        evidence = self._evidence(event_id, saved['vendor_booking_id'])
        if saved['status'] == 'pending':
            require_int(amount_cents, 'amount_cents', minimum=1)
            if amount_cents != saved['amount_cents']:
                raise ValueError('Supplier payment amount mismatch')
            ctx = self.contexts.load(event_id)
            attempts = ctx.setdefault('vendor_execution_attempts', {})
            if payment_id in attempts:
                raise ValueError('Supplier execution already attempted; manual review required before any retry')
            checked = self._call(event_id, 'prepare_vendor_payment_request', **evidence)
            if checked['status'] != 'success':
                return checked
            # The legacy vendor service has no durable execution claim. This demo-only
            # marker conservatively blocks a second call after interruption/save failure.
            attempts[payment_id] = now()
            self.contexts.save(ctx, ctx['revision'])
        return self._call(event_id, 'simulate_vendor_payment', simulate=True, payment_id=payment_id,
                          amount_cents=amount_cents, **evidence)

    @operation
    def reconcile(self, event_id):
        return self._call(event_id, 'reconcile_payments')

    @operation
    def get_history(self, event_id):
        return self._call(event_id, 'get_event_financial_records')
