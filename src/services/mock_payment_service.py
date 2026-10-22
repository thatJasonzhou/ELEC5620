"""Offline PaymentService implementation. No gateway, LLM or refunds."""
from copy import deepcopy
from src.services.payment_service import PaymentService
from src.shared.schemas import CustomerPayment


class MockPaymentService(PaymentService):
    def __init__(self):
        self._payments = {}

    def process_payment(self, payment):
        if not isinstance(payment, CustomerPayment) or payment.status != "pending":
            raise ValueError("Mock payment requires a pending CustomerPayment")
        identity = (payment.event_id, payment.amount_cents, payment.customer_id)
        existing = self._payments.get(payment.payment_id)
        if existing and existing[0] != identity:
            raise ValueError("Payment identity conflict")
        if existing is None:
            self._payments[payment.payment_id] = (identity, {
                "payment_id": payment.payment_id, "amount_cents": payment.amount_cents,
                "status": "paid", "mock": True,
                "transaction_reference": "MOCK-" + payment.payment_id,
            })
        return deepcopy(self._payments[payment.payment_id][1])

    def verify_payment(self, transaction_reference):
        return any(r[1]["transaction_reference"] == transaction_reference
                   for r in self._payments.values())

    def refund_payment(self, transaction_reference, amount_cents):
        raise NotImplementedError("Mock refunds are outside the deposit story")
