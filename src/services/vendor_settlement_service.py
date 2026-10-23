"""Single mock full-settlement workflow; serialized calls, no automatic retries."""
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from src.services.mock_payment_service import MockPaymentService
from src.services.financial_record_service import FinancialRecordService, FinancialStorageError, canonical
from src.services.deposit_service import DepositService
from src.services.procurement_record_service import ProcurementRecordService, ProcurementStorageError
from src.services.vendor_booking_service import quotation_fingerprint
from src.services.vendor_payment_record_service import VendorPaymentRecordService, VendorPaymentStorageError
from src.shared.schemas import (VendorPayment, validate_vendor_evidence,
                                require_non_empty_str, require_int)


class VendorSettlementService:
    def __init__(self, payment_service, procurement_records, payment_records):
        if not isinstance(payment_service, MockPaymentService):
            raise TypeError("Vendor settlement requires MockPaymentService")
        if not isinstance(procurement_records, ProcurementRecordService):
            raise TypeError("Persisted Procurement records are required")
        if not isinstance(payment_records, VendorPaymentRecordService):
            raise TypeError("Persisted vendor payment records are required")
        self._payments = payment_service
        self._procurement = procurement_records
        self._records = payment_records
        self._financial = FinancialRecordService(payment_records.database_path)
        if procurement_records.database_path != payment_records.database_path:
            raise ValueError('Procurement and Financial must use the same database')

    def _conditions(self, request, invoice):
        # Current snapshots/approval are trusted Integration handoffs, never Owner approval.
        quote = DepositService(self._payments)._validate(request)
        if quote['proposal_id'] != request['proposal_id']:
            raise ValueError('Current proposal mismatch')
        history = self._financial.get_event_records(request['event_id'], request['proposal_id'])
        budget = request['budget']
        if not any(canonical(b) == canonical(budget) for b in history['budgets']):
            raise ValueError('Current persisted budget required')
        if not any(canonical(q) == canonical(quote) for q in history['customer_quotations']):
            raise ValueError('Current persisted customer quotation required')
        current = next((q for q in request['quotations']
                        if q['quotation_id'] == invoice['quotation_id']), None)
        persisted = next((q for q in self._procurement.get_quotations(
            request['event_id'], request['proposal_id'])
            if q['quotation_id'] == invoice['quotation_id']), None)
        if (invoice['quotation_id'] not in quote['selected_quotation_ids']
                or current is None or current != persisted):
            raise ValueError('Invoice quotation is not in current approved selection')
        funds = self._financial.event_funds(request['event_id'])
        limit = budget['vendor_total_cents']
        funds.update(vendor_limit_cents=limit,
            budget_shortfall_cents=max(0, funds['vendor_paid_total_cents'] + invoice['amount_cents'] - limit),
            funds_shortfall_cents=max(0, invoice['amount_cents'] - funds['available_funds_cents']))
        return funds

    def _eligible(self, request):
        invoice, completion = validate_vendor_evidence(request)
        event, proposal = invoice["event_id"], invoice["proposal_id"]
        booking = next((b for b in self._procurement.get_bookings(event, proposal)
                        if b["booking_id"] == invoice["vendor_booking_id"]), None)
        quote = next((q for q in self._procurement.get_quotations(event, proposal)
                      if q["quotation_id"] == invoice["quotation_id"]), None)
        if booking is None or quote is None:
            raise ValueError("Persisted booking and quotation are required")
        if booking["status"] != "Confirmed" or booking["mock"] is not True:
            raise ValueError("Confirmed mock booking required")
        for key in ("event_id", "proposal_id", "quotation_id", "vendor_id", "offering_id",
                    "service_type", "event_date", "guest_count", "quoted_total_cents"):
            if booking[key] != quote[key]:
                raise ValueError("Booking/quotation mismatch: " + key)
        if (booking["vendor_id"] != invoice["vendor_id"] or
                booking["source_quotation_fingerprint"] != quotation_fingerprint([quote])):
            raise ValueError("Invoice vendor or source quotation mismatch")
        if invoice["amount_cents"] != quote["quoted_total_cents"]:
            raise ValueError("Invoice must equal full agreed quotation amount")
        return invoice, completion, booking["source_quotation_fingerprint"]

    def prepare(self, request):
        return self._run(request, False)

    def simulate_payment(self, request):
        return self._run(request, True)

    @staticmethod
    def _result(record):
        return dict(status="blocked" if record["status"] == "failed" else "success",
                    message="Mock vendor payment " + record["status"],
                    data={"vendor_payment": deepcopy(record)})

    def _run(self, request, execute):
        try:
            if not isinstance(request, dict):
                raise ValueError("request must be an object")
            event = require_non_empty_str(request.get("event_id"), "event_id")
            proposal = require_non_empty_str(request.get("proposal_id"), "proposal_id")
            if execute:
                if request.get("simulate") is not True:
                    raise ValueError("Explicit simulate=true instruction required")
                token = require_non_empty_str(request.get("payment_id"), "payment_id")
                saved = self._records.get(token)
                if saved is None or saved["event_id"] != event or saved["proposal_id"] != proposal:
                    raise ValueError("Unknown payment for event/proposal")
                amount = require_int(request.get("amount_cents"), "amount_cents", minimum=1)
                if amount != saved["amount_cents"]:
                    raise ValueError("Payment amount mismatch")
                # Durable terminal status is checked before eligibility or provider calls.
                if saved["status"] in ("paid", "failed"):
                    return self._result(saved)
            invoice, completion, fingerprint = self._eligible(request)
            conditions = self._conditions(request, invoice)
            if conditions['budget_shortfall_cents'] or conditions['funds_shortfall_cents']:
                return dict(status='blocked', message='Insufficient approved budget or available funds',
                            data={'settlement_check': conditions})
            if not execute:
                saved = self._records.get_for_booking(invoice["vendor_booking_id"])
            if saved is not None:
                if (saved["invoice_snapshot"] != invoice or saved["completion_snapshot"] != completion
                        or saved["source_quotation_fingerprint"] != fingerprint):
                    raise ValueError("Existing settlement evidence conflicts; review required")
                if not execute:
                    return self._result(saved)
            else:
                now = datetime.now(timezone.utc).isoformat()
                saved = {k: invoice[k] for k in ("event_id", "proposal_id", "vendor_id",
                    "vendor_booking_id", "quotation_id", "invoice_number", "amount_cents", "currency")}
                saved.update(payment_id="VP-" + uuid4().hex, status="pending", mock=True,
                    created_at=now, approved_at=None, paid_at=None, transaction_reference=None,
                    failed_at=None, failure_reason=None, source_quotation_fingerprint=fingerprint,
                    invoice_snapshot=invoice, completion_snapshot=completion)
                return self._result(self._records.create(saved))
            payment = VendorPayment(**{k: saved[k] for k in ("payment_id", "event_id", "vendor_id",
                "vendor_booking_id", "invoice_number", "amount_cents", "status")},
                created_at=datetime.fromisoformat(saved["created_at"]))
            try:
                reply = self._payments.process_payment(payment)
                if (not isinstance(reply, dict) or reply.get("mock") is not True
                        or reply.get("payment_id") != payment.payment_id
                        or type(reply.get("amount_cents")) is not int
                        or reply["amount_cents"] != payment.amount_cents
                        or reply.get("status") not in ("paid", "failed")):
                    raise ValueError("Invalid mock payment result")
                if reply["status"] == "paid":
                    reference = require_non_empty_str(reply.get("transaction_reference"), "transaction_reference")
                    if not reference.startswith("MOCK-"):
                        raise ValueError("Expected MOCK transaction reference")
                    saved.update(status="paid", paid_at=datetime.now(timezone.utc).isoformat(),
                                 transaction_reference=reference)
                else:
                    saved.update(status="failed", failed_at=datetime.now(timezone.utc).isoformat(),
                        failure_reason=require_non_empty_str(reply.get("failure_reason"), "failure_reason"))
            except (ValueError, TypeError, OSError, RuntimeError):
                saved.update(status="failed", failed_at=datetime.now(timezone.utc).isoformat(),
                             failure_reason="Mock execution error; manual review required")
            return self._result(self._records.finish(saved))
        except (ProcurementStorageError, VendorPaymentStorageError, FinancialStorageError):
            return dict(status="error", message="Settlement storage failure; manual review required", data={})
        except (ValueError, TypeError, KeyError) as exc:
            return dict(status="blocked", message=str(exc), data={})
