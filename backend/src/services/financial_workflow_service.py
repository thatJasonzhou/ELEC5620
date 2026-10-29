"""Deterministic financial rules for the Stage 2 customer journey.

The service adapts the teammate repository's quotation, budget, deposit and
booking handoffs to the FastAPI workflow.  It never calls an LLM or a real
payment gateway.  All amounts are integer AUD cents.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4
from typing import Any

from src.services.vendor_booking_service import quotation_fingerprint
from src.shared.costing import calculate_event_costs, supplier_budget_ceiling
from src.shared.schemas import require_int, require_non_empty_str


class FinancialWorkflowService:
    """Validate quotations and prepare customer-facing financial records."""

    def __init__(self, *, deposit_percent: int = 30) -> None:
        self._deposit_percent = require_int(
            deposit_percent, "deposit_percent", minimum=1
        )
        if self._deposit_percent > 100:
            raise ValueError("deposit_percent must not exceed 100")

    def prepare_budget(self, request: dict[str, Any]) -> dict[str, Any]:
        event_id = require_non_empty_str(request.get("event_id"), "event_id")
        proposal = self._record(request.get("proposal"), "proposal")
        if proposal.get("event_id") != event_id:
            raise ValueError("proposal event_id mismatch")
        proposal_id = require_non_empty_str(
            proposal.get("proposal_id"), "proposal_id"
        )
        required_services = proposal.get("required_services")
        if not isinstance(required_services, list) or not required_services:
            raise ValueError("proposal requires at least one service")
        if any(not isinstance(item, str) or not item.strip() for item in required_services):
            raise ValueError("required_services must contain non-empty strings")
        if len(required_services) != len(set(required_services)):
            raise ValueError("required_services contains duplicates")

        quotations = request.get("quotations")
        selected_ids = request.get("selected_quotation_ids")
        if not isinstance(quotations, list) or not quotations:
            raise ValueError("confirmed quotations are required")
        if not isinstance(selected_ids, list) or not selected_ids:
            raise ValueError("selected_quotation_ids are required")
        if len(selected_ids) != len(set(selected_ids)):
            raise ValueError("selected_quotation_ids contains duplicates")

        index: dict[str, dict[str, Any]] = {}
        for quotation in quotations:
            item = self._record(quotation, "quotation")
            quotation_id = require_non_empty_str(
                item.get("quotation_id"), "quotation_id"
            )
            if quotation_id in index:
                raise ValueError("duplicate quotation_id")
            index[quotation_id] = item
        if any(identity not in index for identity in selected_ids):
            raise ValueError("selected quotation is no longer available")

        selected = [deepcopy(index[identity]) for identity in selected_ids]
        selected_services = [item.get("service_type") for item in selected]
        if len(selected_services) != len(set(selected_services)):
            raise ValueError("select only one quotation for each service")
        if set(selected_services) != set(required_services):
            raise ValueError("select one quotation for every required service")
        for item in selected:
            if item.get("event_id") != event_id or item.get("proposal_id") != proposal_id:
                raise ValueError("quotation event/proposal mismatch")
            if item.get("available") is not True or item.get("mock") is not True:
                raise ValueError("quotation must be confirmed and explicitly mock")
            require_int(item.get("quoted_total_cents"), "quoted_total_cents", minimum=0)

        vendor_total = sum(item["quoted_total_cents"] for item in selected)
        costs = calculate_event_costs(vendor_total)
        service_fee = costs["service_fee_cents"]
        contingency = costs["contingency_amount_cents"]
        estimated_total = costs["customer_price_cents"]
        budget_limit = require_int(
            request.get("budget_limit_cents"), "budget_limit_cents", minimum=1
        )
        fingerprint = quotation_fingerprint(selected)
        budget = {
            "event_id": event_id,
            "proposal_id": proposal_id,
            "vendor_total_cents": vendor_total,
            "service_fee_cents": service_fee,
            "contingency_cents": contingency,
            "tax_amount_cents": 0,
            "estimated_total_cents": estimated_total,
            "budget_limit_cents": budget_limit,
            "within_budget": estimated_total <= budget_limit,
            "over_budget_cents": max(0, estimated_total - budget_limit),
            "supplier_budget_limit_cents": supplier_budget_ceiling(budget_limit),
            "quotation_fingerprint": fingerprint,
            "selected_quotation_ids": list(selected_ids),
            "required_services": list(required_services),
            "budget_valid": True,
            "price_basis": "GST-inclusive",
        }
        return {"budget": budget, "selected_quotations": selected}

    def generate_customer_quotation(
        self, budget: dict[str, Any], selected_quotations: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if budget.get("budget_valid") is not True:
            raise ValueError("a validated budget is required")
        if budget.get("within_budget") is not True:
            raise ValueError("the selected plan is over budget")
        return {
            "customer_quotation_id": "CQ-" + uuid4().hex.upper(),
            "event_id": budget["event_id"],
            "proposal_id": budget["proposal_id"],
            "selected_quotation_ids": list(budget["selected_quotation_ids"]),
            "vendor_cost_breakdown": deepcopy(selected_quotations),
            "vendor_total_cents": budget["vendor_total_cents"],
            "service_fee_cents": budget["service_fee_cents"],
            "contingency_cents": budget["contingency_cents"],
            "tax_amount_cents": budget["tax_amount_cents"],
            "estimated_total_cents": budget["estimated_total_cents"],
            "quotation_fingerprint": budget["quotation_fingerprint"],
            "currency": "AUD",
            "price_basis": "GST-inclusive",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def prepare_deposit(
        self, customer_quotation: dict[str, Any], approval: dict[str, Any]
    ) -> dict[str, Any]:
        quotation = self._record(customer_quotation, "customer_quotation")
        approval = self._record(approval, "approval")
        if approval.get("approved") is not True:
            raise ValueError("customer approval is required")
        for field in ("event_id", "proposal_id", "customer_quotation_id"):
            if approval.get(field) != quotation.get(field):
                raise ValueError(f"approval mismatch: {field}")
        if set(approval.get("approved_quotation_ids", [])) != set(
            quotation.get("selected_quotation_ids", [])
        ):
            raise ValueError("approval must cover the selected quotations")
        amount = (
            require_int(
                quotation.get("estimated_total_cents"),
                "estimated_total_cents",
                minimum=1,
            )
            * self._deposit_percent
            + 50
        ) // 100
        return {
            "event_id": quotation["event_id"],
            "proposal_id": quotation["proposal_id"],
            "customer_quotation_id": quotation["customer_quotation_id"],
            "quotation_fingerprint": quotation["quotation_fingerprint"],
            "deposit_request_id": "DR-" + uuid4().hex.upper(),
            "payment_id": "CP-" + uuid4().hex.upper(),
            "amount_cents": amount,
            "deposit_percent": self._deposit_percent,
            "status": "pending",
            "mock": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def simulate_deposit_payment(self, deposit: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(self._record(deposit, "deposit"))
        if result.get("mock") is not True or result.get("status") != "pending":
            raise ValueError("a pending simulated deposit is required")
        require_int(result.get("amount_cents"), "amount_cents", minimum=1)
        result.update(
            status="paid",
            transaction_reference="MOCK-" + result["payment_id"],
            paid_at=datetime.now(timezone.utc).isoformat(),
        )
        return result

    def prepare_final_payment(
        self,
        customer_quotation: dict[str, Any],
        deposit: dict[str, Any],
        operations_plan: dict[str, Any],
    ) -> dict[str, Any]:
        """Create the remaining-balance request after Operations is finalized."""
        quotation = self._record(customer_quotation, "customer_quotation")
        deposit_record = self._record(deposit, "deposit")
        operations = self._record(operations_plan, "operations_plan")

        if operations.get("finalized") is not True or operations.get("status") != "COMPLETED":
            raise ValueError("Operations must be finalized before the final payment")
        for field in ("event_id", "proposal_id"):
            expected = quotation.get(field)
            if deposit_record.get(field) != expected or operations.get(field) != expected:
                raise ValueError(f"final payment mismatch: {field}")
        if deposit_record.get("customer_quotation_id") != quotation.get(
            "customer_quotation_id"
        ):
            raise ValueError("final payment mismatch: customer_quotation_id")
        if deposit_record.get("mock") is not True or deposit_record.get("status") != "paid":
            raise ValueError("the simulated deposit must be paid first")

        total = require_int(
            quotation.get("estimated_total_cents"),
            "estimated_total_cents",
            minimum=1,
        )
        deposit_paid = require_int(
            deposit_record.get("amount_cents"), "deposit amount_cents", minimum=0
        )
        if deposit_paid > total:
            raise ValueError("the paid deposit exceeds the final total")
        remaining = total - deposit_paid
        now = datetime.now(timezone.utc).isoformat()
        payment = {
            "event_id": quotation["event_id"],
            "proposal_id": quotation["proposal_id"],
            "customer_quotation_id": quotation["customer_quotation_id"],
            "quotation_fingerprint": quotation["quotation_fingerprint"],
            "operations_execution_plan_id": require_non_empty_str(
                operations.get("execution_plan_id"), "execution_plan_id"
            ),
            "final_payment_request_id": "FPR-" + uuid4().hex.upper(),
            "payment_id": "FP-" + uuid4().hex.upper(),
            "total_amount_cents": total,
            "deposit_paid_cents": deposit_paid,
            "amount_cents": remaining,
            "status": "pending" if remaining else "paid",
            "mock": True,
            "created_at": now,
        }
        if remaining == 0:
            payment.update(
                transaction_reference="MOCK-NO-BALANCE-DUE",
                paid_at=now,
            )
        return payment

    def simulate_final_payment(self, final_payment: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(self._record(final_payment, "final_payment"))
        if result.get("mock") is not True or result.get("status") != "pending":
            raise ValueError("a pending simulated final payment is required")
        require_int(result.get("amount_cents"), "amount_cents", minimum=1)
        result.update(
            status="paid",
            transaction_reference="MOCK-" + result["payment_id"],
            paid_at=datetime.now(timezone.utc).isoformat(),
        )
        return result

    @staticmethod
    def _record(value: Any, name: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError(f"{name} must be an object")
        return value
