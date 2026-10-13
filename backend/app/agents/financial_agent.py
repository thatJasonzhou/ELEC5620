from uuid import uuid4

from app.models.enums import AgentName
from app.schemas.common import AgentActivity
from app.schemas.quotation import QuotationRequest, QuotationResponse
from app.services.quotation_service import QuotationService


class FinancialManagerAgent:
    def __init__(self, quotation_service: QuotationService) -> None:
        self._quotation_service = quotation_service

    def prepare_customer_quotation(self, request: QuotationRequest) -> QuotationResponse:
        calculation = self._quotation_service.calculate(request)
        budget_decision = (
            "The quotation is within the recorded customer budget."
            if calculation.within_budget
            else "The quotation exceeds the recorded customer budget and requires revision."
        )
        activity = AgentActivity(
            event_id=request.event_id,
            request_id=f"REQ-{uuid4().hex[:8].upper()}",
            agent=AgentName.FINANCIAL_MANAGER,
            perception=f"Received {len(request.vendor_costs)} accepted vendor cost item(s).",
            decision=budget_decision,
            action="Calculated the event budget, service fee, and customer quotation.",
            result=f"Total {request.currency} {calculation.total_quotation:.2f}",
        )
        return QuotationResponse(
            event_id=request.event_id,
            currency=request.currency,
            vendor_subtotal=calculation.vendor_subtotal,
            contingency_amount=calculation.contingency_amount,
            tax_amount=calculation.tax_amount,
            estimated_event_cost=calculation.estimated_event_cost,
            service_fee=calculation.service_fee,
            total_quotation=calculation.total_quotation,
            within_budget=calculation.within_budget,
            budget_difference=calculation.budget_difference,
            activity=activity,
        )

