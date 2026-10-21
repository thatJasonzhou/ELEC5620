"""Financial foundation using the existing AIAgent and response envelope.

Temporary request contract: {"event_id": str, "action": str}; Supervisor
integration is pending. No business payload is validated or executed yet.
Stage 1 methods map to snake_case below. currentEventId:int is represented by
the request's string event_id, not a mutable current-event field. financeStatus
has no approved default/state rules and is not fabricated. The shared AIAgent
still lacks UML state/goal and perceive/reason/act/communicate; it is unchanged.
"""
from __future__ import annotations

from typing import Any

from src.agents.base import AIAgent
from src.llm import LLMClient
from src.services.payment_service import PaymentService
from src.shared.schemas import (
    Budget, CustomerPayment, VendorBooking, VendorPayment, require_non_empty_str,
)


class FinancialManagerAgent(AIAgent):
    """Financial entry point; every business operation is explicitly unfinished."""

    agent_name = "finance"
    _ACTIONS = (
        "prepare_budget", "update_proposal_cost", "record_customer_payment",
        "settle_vendor_payment", "reconcile_payments",
    )

    def __init__(self, llm: LLMClient, payment_service: PaymentService) -> None:
        super().__init__(llm)
        if not isinstance(payment_service, PaymentService):
            raise TypeError("payment_service must be a PaymentService instance")
        self._payment_service = payment_service

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict):
            return self.envelope(None, "error", "request must be a dict")
        event_id: str | None = None
        try:
            event_id = require_non_empty_str(request.get("event_id"), "event_id")
            action = require_non_empty_str(request.get("action"), "action")
            if action not in self._ACTIONS:
                raise ValueError(f"action must be one of {self._ACTIONS}")
        except ValueError as exc:
            return self.envelope(event_id, "needs_input", str(exc))

        try:
            # Validate only the temporary outer contract. Missing business
            # objects are not constructed or treated as validated input.
            if action == "prepare_budget":
                self.prepare_budget(request.get("event"), request.get("quotations"))
            elif action == "update_proposal_cost":
                self.update_proposal_cost(request.get("proposal"), request.get("budget"))
            elif action == "record_customer_payment":
                self.record_customer_payment(request.get("payment"))
            elif action == "settle_vendor_payment":
                self.settle_vendor_payment(request.get("booking"))
            else:
                self.reconcile_payments(event_id)
        except NotImplementedError as exc:
            return self.envelope(event_id, "error", str(exc))
        # Never release a successful workflow result from the foundation.
        return self.envelope(event_id, "error", "NOT_IMPLEMENTED: Financial workflow")

    def prepare_budget(self, event: Any, quotations: list[Any]) -> Budget:
        """UML prepareBudget(Event, List<VendorQuotation>):Budget."""
        raise NotImplementedError("NOT_IMPLEMENTED: FinancialManagerAgent.prepare_budget")

    def update_proposal_cost(self, proposal: Any, budget: Budget) -> None:
        """UML updateProposalCost(EventProposal, Budget):void."""
        raise NotImplementedError("NOT_IMPLEMENTED: FinancialManagerAgent.update_proposal_cost")

    def record_customer_payment(self, payment: CustomerPayment) -> None:
        raise NotImplementedError("NOT_IMPLEMENTED: FinancialManagerAgent.record_customer_payment")

    def settle_vendor_payment(self, booking: VendorBooking) -> VendorPayment:
        raise NotImplementedError("NOT_IMPLEMENTED: FinancialManagerAgent.settle_vendor_payment")

    def reconcile_payments(self, event_id: str) -> bool:
        """UML reconcilePayments(eventId:int):Boolean; IDs cross as strings."""
        raise NotImplementedError("NOT_IMPLEMENTED: FinancialManagerAgent.reconcile_payments")
