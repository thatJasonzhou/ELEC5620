from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.schemas.quotation import QuotationRequest

MONEY_PLACES = Decimal("0.01")


class MissingCostDataError(ValueError):
    pass


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class QuotationCalculation:
    vendor_subtotal: Decimal
    contingency_amount: Decimal
    tax_amount: Decimal
    estimated_event_cost: Decimal
    service_fee: Decimal
    total_quotation: Decimal
    within_budget: bool
    budget_difference: Decimal


class QuotationService:
    def calculate(self, request: QuotationRequest) -> QuotationCalculation:
        if not request.vendor_costs:
            raise MissingCostDataError("At least one vendor cost is required.")

        vendor_subtotal = money(
            sum(
                (item.unit_price * item.quantity for item in request.vendor_costs),
                start=Decimal("0"),
            )
        )
        contingency_amount = money(vendor_subtotal * request.contingency_rate)
        taxable_cost = vendor_subtotal + contingency_amount
        tax_amount = money(taxable_cost * request.tax_rate)
        estimated_event_cost = money(taxable_cost + tax_amount)
        service_fee = money(estimated_event_cost * request.service_fee_rate)
        total_quotation = money(estimated_event_cost + service_fee)
        budget_difference = money(request.customer_budget - total_quotation)

        return QuotationCalculation(
            vendor_subtotal=vendor_subtotal,
            contingency_amount=contingency_amount,
            tax_amount=tax_amount,
            estimated_event_cost=estimated_event_cost,
            service_fee=service_fee,
            total_quotation=total_quotation,
            within_budget=budget_difference >= 0,
            budget_difference=budget_difference,
        )

