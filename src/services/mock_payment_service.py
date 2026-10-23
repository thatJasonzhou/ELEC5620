"""Offline PaymentService implementation. No gateway, LLM or refunds."""
from copy import deepcopy
from src.services.payment_service import PaymentService
from src.shared.schemas import CustomerPayment, VendorPayment


class MockPaymentService(PaymentService):
    def __init__(self, *, vendor_outcome="success", customer_outcome="success"):
        if customer_outcome not in ("success", "failure"):
            raise ValueError("customer_outcome must be success or failure")
        self.customer_outcome = customer_outcome
        if vendor_outcome not in ("success", "failure"):
            raise ValueError("vendor_outcome must be success or failure")
        self.vendor_outcome = vendor_outcome
        self._payments = {}

    def process_payment(self, payment):
        if not isinstance(payment, (CustomerPayment, VendorPayment)) or payment.status != "pending":
            raise ValueError("Mock payment requires a pending CustomerPayment or VendorPayment")
        vendor = isinstance(payment, VendorPayment)
        identity = (type(payment).__name__, payment.event_id, payment.amount_cents,
                    (payment.vendor_id, payment.vendor_booking_id, payment.invoice_number)
                    if vendor else payment.customer_id)
        existing = self._payments.get(payment.payment_id)
        if existing and existing[0] != identity:
            raise ValueError("Payment identity conflict")
        if existing is None:
            self._payments[payment.payment_id] = (identity, {
                "payment_id": payment.payment_id, "amount_cents": payment.amount_cents,
                "status": "paid", "mock": True,
                "transaction_reference": "MOCK-" + payment.payment_id,
            })
            if (vendor and self.vendor_outcome == "failure") or (not vendor and self.customer_outcome == "failure"):
                self._payments[payment.payment_id][1].update(
                    status="failed", transaction_reference=None,
                    failure_reason="Explicit mock payment failure")
        return deepcopy(self._payments[payment.payment_id][1])

    def verify_payment(self, transaction_reference):
        return any(r[1]["status"] == "paid" and r[1]["transaction_reference"] == transaction_reference
                   for r in self._payments.values())

    def refund_payment(self, transaction_reference, amount_cents):
        raise NotImplementedError("Mock refunds are outside the deposit story")
