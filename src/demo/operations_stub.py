"""Explicit mock evidence with a fixed, activity-wide settlement scope."""
from uuid import uuid4

from src.demo.context_service import now


class DemoOperationsStub:
    def __init__(self, contexts, procurement):
        self.contexts = contexts
        self.procurement = procurement

    def _bookings(self, event_id):
        bookings = [b for b in self.procurement.all_bookings() if b['event_id'] == event_id]
        if not bookings or any(b['status'] != 'Confirmed' or b.get('mock') is not True for b in bookings):
            raise ValueError('Confirmed mock bookings required for the complete demo scope')
        return sorted(bookings, key=lambda b: b['booking_id'])

    def get(self, event_id):
        saved = self.contexts.evidence(event_id)
        if saved is not None and saved['booking_snapshots'] != self._bookings(event_id):
            raise ValueError('Booking scope changed; manual review required')
        return saved

    def get_scope(self, event_id):
        saved = self.get(event_id)
        return saved['scope'] if saved else None

    def create(self, event_id):
        previous = self.get(event_id)
        if previous:
            return previous
        bookings = self._bookings(event_id)
        scope = dict(event_id=event_id, settlement_scope_id='STUB-' + uuid4().hex,
                     scope_complete=True, bookings=[])
        evidence = {}
        for b in bookings:
            quote = next((q for q in self.procurement.get_quotations(event_id, b['proposal_id'])
                          if q['quotation_id'] == b['quotation_id']), None)
            if quote is None or any(quote[k] != b[k] for k in (
                    'vendor_id', 'quoted_total_cents', 'event_date', 'guest_count', 'offering_id', 'service_type')):
                raise ValueError('Booking quotation missing or changed')
            refs = dict(event_id=event_id, proposal_id=b['proposal_id'],
                        vendor_booking_id=b['booking_id'], quotation_id=b['quotation_id'], vendor_id=b['vendor_id'])
            timestamp = now()
            evidence[b['booking_id']] = dict(
                invoice={**refs, 'invoice_number': 'MOCK-INV-' + uuid4().hex,
                         'amount_cents': quote['quoted_total_cents'], 'currency': 'AUD',
                         'issued_date': timestamp[:10], 'mock': True},
                completion={**refs, 'completion_id': 'STUB-COMP-' + uuid4().hex,
                            'status': 'completed', 'completed_at': timestamp, 'mock': True})
            scope['bookings'].append({k: refs[k] for k in (
                'proposal_id', 'vendor_booking_id', 'quotation_id', 'vendor_id')})
        return self.contexts.save_evidence(event_id, dict(
            source='OPERATIONS_STUB', scope=scope, evidence=evidence, booking_snapshots=bookings))
