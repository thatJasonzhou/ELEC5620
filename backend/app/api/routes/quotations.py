from fastapi import APIRouter, HTTPException, status

from app.agents.financial_agent import FinancialManagerAgent
from app.schemas.quotation import QuotationRequest, QuotationResponse
from app.services.quotation_service import MissingCostDataError, QuotationService

router = APIRouter(prefix="/quotations", tags=["financial-management"])


@router.post(
    "/calculate",
    response_model=QuotationResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_200_OK,
)
def calculate_quotation(request: QuotationRequest) -> QuotationResponse:
    agent = FinancialManagerAgent(QuotationService())
    try:
        return agent.prepare_customer_quotation(request)
    except MissingCostDataError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "MISSING_COST_DATA", "message": str(error)},
        ) from error

