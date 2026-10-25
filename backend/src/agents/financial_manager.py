"""Financial Manager Agent for deterministic Stage 2 prototype actions."""
from __future__ import annotations

from typing import Any

from src.agents.base import AIAgent
from src.llm import LLMClient
from src.services.financial_workflow_service import FinancialWorkflowService
from src.shared.schemas import require_non_empty_str


class FinancialManagerAgent(AIAgent):
    """Expose validated financial rules through the shared Agent envelope."""

    agent_name = "finance"

    def __init__(self, llm: LLMClient, service: FinancialWorkflowService) -> None:
        super().__init__(llm)
        if not isinstance(service, FinancialWorkflowService):
            raise TypeError("service must be a FinancialWorkflowService")
        self._service = service

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict):
            return self.envelope(None, "error", "request must be an object")
        event_id = request.get("event_id")
        try:
            event_id = require_non_empty_str(event_id, "event_id")
            action = require_non_empty_str(request.get("action"), "action")
            if action == "prepare_budget":
                data = self._service.prepare_budget(request)
                budget = data["budget"]
                status = "success" if budget["within_budget"] else "blocked"
                message = (
                    "The selected supplier quotations are within budget."
                    if budget["within_budget"]
                    else "The selected supplier quotations are over budget. Please choose different quotations or revise the plan."
                )
                return self.envelope(event_id, status, message, data)
            if action == "generate_customer_quotation":
                quotation = self._service.generate_customer_quotation(
                    request.get("budget"), request.get("selected_quotations")
                )
                return self.envelope(
                    event_id,
                    "success",
                    "Customer quotation generated for review.",
                    {"customer_quotation": quotation},
                )
            if action == "prepare_deposit":
                deposit = self._service.prepare_deposit(
                    request.get("customer_quotation"), request.get("approval")
                )
                return self.envelope(
                    event_id,
                    "success",
                    "Simulated deposit request prepared.",
                    {"deposit": deposit},
                )
            if action == "simulate_deposit_payment":
                deposit = self._service.simulate_deposit_payment(
                    request.get("deposit")
                )
                return self.envelope(
                    event_id,
                    "success",
                    "Simulated deposit payment completed.",
                    {"deposit": deposit},
                )
            raise ValueError("unsupported financial action")
        except (KeyError, TypeError, ValueError) as exc:
            return self.envelope(event_id, "blocked", str(exc))
