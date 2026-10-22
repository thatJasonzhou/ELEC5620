"""Financial Manager UC4 GST-inclusive budget checks.

Structured requests select quotations for the current proposal. Budget owns
exact monetary calculation; this Agent validates inputs and returns envelopes.
Mock customer deposits require an explicit payment request.
"""
from __future__ import annotations

from typing import Any

from src.agents.base import AIAgent
from src.llm import LLMClient
from src.services.payment_service import PaymentService
from src.services.deposit_service import DepositService
from src.services.customer_quotation_service import (
    CustomerQuotationService, source_fingerprint, budget_fingerprint,
)
from src.services.vendor_booking_service import quotation_fingerprint
from src.shared.schemas import (
    Budget, CustomerPayment, VendorBooking, VendorPayment, require_non_empty_str,
    require_int, require_valid_date,
)


class FinancialManagerAgent(AIAgent):
    """Budget checks, customer quotations and explicit mock customer deposits."""

    agent_name = "finance"
    _ACTIONS = (
        "prepare_budget", "update_proposal_cost", "record_customer_payment",
        "settle_vendor_payment", "reconcile_payments", "generate_customer_quotation",
        "prepare_deposit_request", "simulate_deposit_payment",
    )

    def __init__(self, llm: LLMClient, payment_service: PaymentService) -> None:
        super().__init__(llm)
        if not isinstance(payment_service, PaymentService):
            raise TypeError("payment_service must be a PaymentService instance")
        self._payment_service = payment_service
        self._deposit_service = None

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
            if action in ("prepare_deposit_request", "simulate_deposit_payment"):
                if self._deposit_service is None:
                    try:
                        self._deposit_service = DepositService(self._payment_service)
                    except TypeError as exc:
                        return self.envelope(event_id, "error", str(exc))
                operation = (self._deposit_service.prepare if action == "prepare_deposit_request"
                             else self._deposit_service.simulate_payment)
                result = operation(request)
                return self.envelope(event_id, result["status"], result["message"], result["data"])
            # Existing financial workflows retain their contracts.
            if action == "generate_customer_quotation":
                result = CustomerQuotationService().generate(request)
                return self.envelope(event_id, result["status"], result["message"], result["data"])
            if action == "prepare_budget":
                result = self._check_budget(request)
                result["data"].setdefault("budget_valid", False)
                return result
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
        # Other financial workflows are not implemented.
        return self.envelope(event_id, "error", "NOT_IMPLEMENTED: Financial workflow")

    def prepare_budget(self, event: Any, quotations: list[Any]) -> Budget:
        """Prepare a Budget from the current event and selected quotations."""
        if not isinstance(event, dict):
            raise ValueError("event must be an object")
        fingerprint = quotation_fingerprint(quotations)
        budget = Budget(budget_id="B-" + fingerprint,
            event_id=require_non_empty_str(event.get("event_id"), "event_id"),
            vendor_cost_cents=0, contingency_amount_cents=0, tax_amount_cents=0,
            customer_price_cents=0, status="Calculated")
        for quote in quotations:
            budget.add_vendor_quotation(quote)
        budget.calculate_total()
        return budget

    def _check_budget(self, request: dict[str, Any]) -> dict[str, Any]:
        event_id = request["event_id"]
        try:
            event, proposal = request.get("event"), request.get("proposal")
            if not isinstance(event, dict) or not isinstance(proposal, dict):
                raise ValueError("event and proposal must be objects")
            proposal_id = require_non_empty_str(proposal.get("proposal_id"), "proposal_id")
            if event.get("event_id") != event_id or proposal.get("event_id") != event_id:
                raise ValueError("event_id mismatch")
            limit = require_int(event.get("budget_limit_cents"), "budget_limit_cents")
            date = require_valid_date(event.get("event_date"), "event_date")
            guests = require_int(event.get("guest_count"), "guest_count")
            required = proposal.get("required_services")
            if not isinstance(required, list) or not required:
                raise ValueError("required_services must be a non-empty list")
            for service in required:
                require_non_empty_str(service, "required_services item")
            if len(set(required)) != len(required):
                raise ValueError("duplicate required_services")
            source = source_fingerprint(event, proposal)
            quotes = request.get("quotations")
            selected = request.get("selected_quotation_ids")
            if not isinstance(quotes, list):
                raise ValueError("quotations must be a list")
            if not isinstance(selected, list) or not selected:
                raise ValueError("selected_quotation_ids must be a non-empty list")
            for identity in selected:
                require_non_empty_str(identity, "selected_quotation_ids item")
            if len(set(selected)) != len(selected):
                raise ValueError("duplicate selected quotation ID")
        except ValueError as exc:
            return self.envelope(event_id, "needs_input", str(exc))
        try:
            index = {}
            for quote in quotes:
                if not isinstance(quote, dict):
                    raise ValueError("quotation must be an object")
                identity = require_non_empty_str(quote.get("quotation_id"), "quotation_id")
                if identity in index:
                    raise ValueError("duplicate quotation_id")
                index[identity] = quote
            if any(identity not in index for identity in selected):
                return self.envelope(event_id, "blocked", "Selected quotation is missing; request current quotations.")
            chosen = [index[identity] for identity in selected]
            fingerprint = quotation_fingerprint(chosen)
            for quote in chosen:
                if quote["event_id"] != event_id or quote["proposal_id"] != proposal_id:
                    raise ValueError("selected quotation event_id/proposal_id mismatch")
                if quote["event_date"] != date or quote["guest_count"] != guests:
                    raise ValueError("selected quotation date/guest_count mismatch")
                if quote["service_type"] not in required:
                    raise ValueError("selected quotation service is not required")
            missing = set(required) - {q["service_type"] for q in chosen}
            if missing:
                return self.envelope(event_id, "blocked", "Missing required services: " + ", ".join(sorted(missing)))
            budget = self.prepare_budget(event, chosen)
        except (ValueError, KeyError, TypeError) as exc:
            return self.envelope(event_id, "error", str(exc))
        total = budget.customer_price_cents
        data = {
            "event_id": event_id, "proposal_id": proposal_id,
            "vendor_total_cents": budget.vendor_cost_cents,
            "service_fee_cents": budget.service_fee_cents,
            "contingency_cents": budget.contingency_amount_cents,
            "tax_amount_cents": budget.tax_amount_cents,
            "estimated_total_cents": total, "budget_limit_cents": limit,
            "within_budget": total <= limit, "over_budget_cents": max(0, total - limit),
            "quotation_fingerprint": fingerprint, "selected_quotation_ids": list(selected),
            "budget_valid": True, "price_basis": "GST-inclusive",
            "required_services": list(required),
            "source_fingerprint": source,
        }
        data["budget_fingerprint"] = budget_fingerprint(data)
        return self.envelope(event_id, "success" if total <= limit else "blocked",
                             "GST-inclusive budget check. "
                             + ("Within budget." if total <= limit else "Over budget; Supervisor must coordinate revision."), data)

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
