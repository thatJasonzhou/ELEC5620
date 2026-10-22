"""KAN-32: read-only financial checks over a trusted Operations scope."""
from copy import deepcopy
from datetime import datetime

from src.services.customer_quotation_service import CustomerQuotationService
from src.services.financial_record_service import FinancialStorageError, canonical
from src.services.procurement_record_service import ProcurementStorageError
from src.services.vendor_payment_record_service import VendorPaymentStorageError, read_vendor_payment_history
from src.services.vendor_booking_service import quotation_fingerprint
from src.shared.schemas import require_non_empty_str, require_int, validate_vendor_evidence


class FinancialReconciliationService:
    """Providers are trusted internal callables(event_id); never browser payloads.

    Missing providers block. They must supply current context and the complete
    Operations settlement scope. No payment provider is needed or invoked.
    """

    def __init__(self, financial_records, procurement_records, vendor_records, *,
                 context_provider=None, scope_provider=None):
        paths = {s.database_path for s in (financial_records, procurement_records, vendor_records)}
        if len(paths) != 1:
            raise ValueError('Reconciliation requires the same database')
        self.financial = financial_records
        self.procurement = procurement_records
        self.context_provider = context_provider
        self.scope_provider = scope_provider

    def reconcile(self, event_id):
        require_non_empty_str(event_id, 'event_id')
        data = dict(financial_check_passed=False, summary_complete=False,
                    customer=None, vendors=None, reason_codes=[])
        def result(status, message, code=None):
            if code:
                data['reason_codes'].append(code)
            return dict(status=status, message=message, data=data)
        if self.scope_provider is None or self.context_provider is None:
            return result('blocked', 'Current context and Operations scope required', 'RECONCILIATION_INPUT_MISSING')
        try:
            scope = deepcopy(self.scope_provider(event_id))
            context = deepcopy(self.context_provider(event_id))
            if not isinstance(scope, dict) or scope.get('scope_complete') is not True:
                return result('blocked', 'Complete Operations scope required', 'SETTLEMENT_SCOPE_MISSING')
            if scope.get('event_id') != event_id or not isinstance(scope.get('bookings'), list):
                raise ValueError('Invalid scope identity or bookings')
            data['settlement_scope_id'] = require_non_empty_str(scope.get('settlement_scope_id'), 'settlement_scope_id')
            if not isinstance(context, dict) or context.get('event_id') != event_id:
                raise ValueError('Current context event mismatch')
            projected = CustomerQuotationService.quotation_content(context)
            if projected['status'] != 'success':
                raise ValueError(projected['message'])
            quote = context['customer_quotation']
            expected = projected['data']['customer_quotation']
            if any(quote.get(k) != v for k, v in expected.items()
                   if k not in ('customer_quotation_id', 'generated_at')):
                raise ValueError('Current customer quotation mismatch')
            customer = require_non_empty_str(context.get('customer_id'), 'customer_id')
            approval = context['approval']
            if (approval.get('approved') is not True or any(approval.get(k) != quote[k]
                    for k in ('event_id', 'proposal_id', 'customer_quotation_id', 'quotation_fingerprint'))
                    or sorted(approval['approved_quotation_ids']) != sorted(quote['selected_quotation_ids'])):
                raise ValueError('Current approval mismatch')
            with self.financial.reconciliation_snapshot() as db:
                saved = [self.financial._decode(row) for row in db.execute(
                    "SELECT schema_version,payload FROM financial_snapshots WHERE event_id=? AND kind='customer_quotation'",
                    (event_id,))]
                if not any(canonical(q) == canonical(quote) for q in saved):
                    raise ValueError('Persisted current customer quotation missing')
                budgets = [self.financial._decode(row) for row in db.execute(
                    "SELECT schema_version,payload FROM financial_snapshots WHERE event_id=? AND kind='budget'", (event_id,))]
                if not any(canonical(b) == canonical(context['budget']) for b in budgets):
                    raise ValueError('Persisted current budget missing')
                collections = self.financial._collections(db, event_id, customer)
                for payment, state, record in collections:
                    if payment.get('event_id') != event_id or record.get('customer_id') != customer:
                        raise ValueError('Customer payment identity mismatch')
                    if payment.get('proposal_id') != record['quote']['proposal_id'] or payment.get('customer_quotation_id') != record['quote']['customer_quotation_id']:
                        raise ValueError('Customer payment quotation mismatch')
                    if record['quote']['event_id'] != event_id or payment.get('quotation_fingerprint') != record['quote']['quotation_fingerprint']:
                        raise ValueError('Customer payment source mismatch')
                    require_int(payment.get('amount_cents'), 'amount_cents', minimum=1)
                    if state in ('execution_started', 'executing', 'requires_reconciliation'):
                        data['reason_codes'].append('CUSTOMER_PAYMENT_UNCERTAIN')
                data['customer'] = self.financial._balance(db, quote, customer)
                if db.execute('SELECT 1 FROM customer_collection_claims WHERE event_id=? AND customer_id=?', (event_id, customer)).fetchone():
                    data['reason_codes'].append('CUSTOMER_PAYMENT_UNCERTAIN')
                data['customer']['payment_ids'] = sorted({p['payment_id'] for p, _, _ in collections if p['status'] == 'paid'})
                if data['customer']['balance_cents'] != 0:
                    data['reason_codes'].append('CUSTOMER_BALANCE_OUTSTANDING')
                payments = read_vendor_payment_history(self.financial.database_path, event_id, connection=db)
                due = paid = 0
                items, seen = [], set()
                for ref in sorted(scope['bookings'], key=lambda r: r['vendor_booking_id']):
                    identity = require_non_empty_str(ref.get('vendor_booking_id'), 'vendor_booking_id')
                    if identity in seen:
                        raise ValueError('Duplicate scope booking')
                    seen.add(identity)
                    proposal = require_non_empty_str(ref.get('proposal_id'), 'proposal_id')
                    bookings = self.procurement._read('procurement_bookings', (event_id, proposal), connection=db)
                    quotes = self.procurement._read('procurement_quotations', (event_id, proposal), connection=db)
                    booking = next((b for b in bookings if b['booking_id'] == identity), None)
                    q = next((q for q in quotes if q['quotation_id'] == ref['quotation_id']), None)
                    if booking is None or q is None:
                        raise ValueError('Required booking or quotation missing')
                    if (any(booking[k] != q[k] for k in ('event_id', 'proposal_id', 'quotation_id', 'vendor_id', 'offering_id', 'service_type', 'event_date', 'guest_count', 'quoted_total_cents'))
                            or ref['vendor_id'] != booking['vendor_id']
                            or booking['source_quotation_fingerprint'] != quotation_fingerprint([q])):
                        raise ValueError('Booking identity or amount mismatch')
                    amount = require_int(q['quoted_total_cents'], 'quoted_total_cents')
                    due += amount
                    matches = [p for p in payments if p.get('vendor_booking_id') == identity]
                    reason = None
                    if not matches:
                        reason = 'VENDOR_PAYMENT_MISSING'
                    elif len(matches) != 1:
                        reason = 'VENDOR_PAYMENT_MISMATCH'
                    else:
                        p = matches[0]
                        if (any(p.get(k) != v for k, v in dict(event_id=event_id, proposal_id=proposal,
                            vendor_booking_id=identity, quotation_id=q['quotation_id'], vendor_id=q['vendor_id']).items())
                            or type(p.get('amount_cents')) is not int or p['amount_cents'] != amount):
                            reason = 'VENDOR_PAYMENT_MISMATCH'
                        elif p.get('status') != 'paid':
                            reason = 'VENDOR_PAYMENT_FAILED' if p.get('status') == 'failed' else 'VENDOR_PAYMENT_UNPAID'
                        else:
                            invoice, completion = validate_vendor_evidence(dict(event_id=event_id, proposal_id=proposal,
                                invoice=p['invoice_snapshot'], completion=p['completion_snapshot']))
                            if (any(invoice[k] != p[k] for k in ('event_id', 'proposal_id', 'vendor_booking_id', 'quotation_id', 'vendor_id', 'amount_cents', 'invoice_number', 'currency'))
                                    or p.get('mock') is not True or p.get('currency') != 'AUD'
                                    or p.get('source_quotation_fingerprint') != quotation_fingerprint([q])
                                    or p.get('transaction_reference') != 'MOCK-' + p['payment_id']
                                    or datetime.fromisoformat(p['paid_at']).utcoffset() is None):
                                reason = 'VENDOR_PAYMENT_MISMATCH'
                            else:
                                paid += amount
                    items.append(dict(vendor_booking_id=identity, amount_due_cents=amount,
                        payment_id=matches[0].get('payment_id') if len(matches) == 1 else None,
                        reason_code=reason))
                    if reason:
                        data['reason_codes'].append(reason)
                data['vendors'] = dict(amount_due_cents=due, amount_paid_cents=paid,
                    balance_cents=due-paid, items=items,
                    outstanding_items=[i for i in items if i['reason_code']])
            data['summary_complete'] = True
            data['reason_codes'] = sorted(set(data['reason_codes']))
            data['financial_check_passed'] = not data['reason_codes']
            return result('success' if data['financial_check_passed'] else 'blocked', 'Financial reconciliation checked')
        except (FinancialStorageError, ProcurementStorageError, VendorPaymentStorageError, OSError, RuntimeError):
            return result('error', 'Reconciliation data read failed', 'DATA_READ_FAILED')
        except (ValueError, KeyError, TypeError, AttributeError):
            return result('blocked', 'Required evidence missing or inconsistent', 'EVIDENCE_INVALID')
