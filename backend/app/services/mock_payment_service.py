from dataclasses import dataclass
from decimal import Decimal

from app.models.enums import PaymentStatus


class DuplicatePaymentError(ValueError):
    pass


@dataclass(frozen=True)
class MockPayment:
    payment_id: str
    event_id: str
    amount: Decimal
    status: PaymentStatus


class MockPaymentService:
    def __init__(self) -> None:
        self._payments: dict[str, MockPayment] = {}

    def record(self, payment: MockPayment) -> MockPayment:
        if payment.payment_id in self._payments:
            raise DuplicatePaymentError(f"Payment {payment.payment_id} already exists.")
        self._payments[payment.payment_id] = payment
        return payment

