"""Stage 1 PaymentService interface only; no payment implementation.

processPayment(Payment):PaymentResult -> process_payment(Payment):Any because
PaymentResult has no defined structure yet. verifyPayment(String):Boolean keeps
the class diagram's reference-only signature; the sequence diagram's additional
amount argument is unresolved. refundPayment(String, Decimal):Boolean uses the
approved integer AUD amount_cents boundary, with no conversion or refund logic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.shared.schemas import Payment


class PaymentService(ABC):
    """Inject an implementation later; no default successful operations."""

    @abstractmethod
    def process_payment(self, payment: Payment) -> Any:
        """Return the not-yet-defined UML PaymentResult."""
        raise NotImplementedError("NOT_IMPLEMENTED: PaymentService.process_payment")

    @abstractmethod
    def verify_payment(self, transaction_reference: str) -> bool:
        raise NotImplementedError("NOT_IMPLEMENTED: PaymentService.verify_payment")

    @abstractmethod
    def refund_payment(self, transaction_reference: str, amount_cents: int) -> bool:
        raise NotImplementedError("NOT_IMPLEMENTED: PaymentService.refund_payment")
