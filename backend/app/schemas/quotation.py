from decimal import Decimal

from pydantic import Field, field_validator

from app.schemas.common import AgentActivity, ApiModel


class VendorCostItem(ApiModel):
    description: str = Field(min_length=1, max_length=200)
    quantity: int = Field(default=1, ge=1)
    unit_price: Decimal = Field(ge=Decimal("0"))


class QuotationRequest(ApiModel):
    event_id: str = Field(min_length=1, max_length=50)
    customer_budget: Decimal = Field(gt=Decimal("0"))
    currency: str = Field(default="AUD", min_length=3, max_length=3)
    vendor_costs: list[VendorCostItem] = Field(default_factory=list)
    contingency_rate: Decimal = Field(default=Decimal("0.05"), ge=0, le=1)
    tax_rate: Decimal = Field(default=Decimal("0.10"), ge=0, le=1)
    service_fee_rate: Decimal = Field(default=Decimal("0.10"), ge=0, le=1)

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()


class QuotationResponse(ApiModel):
    event_id: str
    currency: str
    vendor_subtotal: Decimal
    contingency_amount: Decimal
    tax_amount: Decimal
    estimated_event_cost: Decimal
    service_fee: Decimal
    total_quotation: Decimal
    within_budget: bool
    budget_difference: Decimal
    activity: AgentActivity

