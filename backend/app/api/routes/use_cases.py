from fastapi import APIRouter

from app.models.enums import ImplementationStatus
from app.schemas.common import UseCaseEntry

router = APIRouter(tags=["use-cases"])

USE_CASES = [
    ("UC1", "Define Event Requirements", "Event Planning", "Xiaowen"),
    ("UC2", "Generate Event Proposal", "Event Planning", "Xiaowen"),
    ("UC3", "Procure Event Vendors", "Vendor Procurement", "Zhidong Zhou"),
    ("UC4", "Prepare Event Budget and Customer Quotation", "Financial Management", "Hetong Wang"),
    ("UC5", "Finalize Event Proposal", "Event Planning", "Xiaowen"),
    ("UC6", "Confirm Event Booking", "Event Planning", "Xiaowen"),
    ("UC7", "Confirm Vendor Bookings", "Vendor Procurement", "Zhidong Zhou"),
    ("UC8", "Manage Customer Payments", "Financial Management", "Hetong Wang"),
    ("UC9", "Plan and Coordinate Event Operations", "Event Operations", "Peng Dou"),
    ("UC10", "Manage Event Changes", "Change and Closure", "Clarissa Mo"),
    ("UC11", "Manage Event Execution", "Event Operations", "Peng Dou"),
    ("UC12", "Handle Operational Exceptions", "Event Operations", "Peng Dou"),
    ("UC13", "Manage Vendor Payments", "Financial Management", "Hetong Wang"),
    ("UC14", "Handle Customer Feedback and Complaints", "Change and Closure", "Clarissa Mo"),
    ("UC15", "Verify and Close Event", "Change and Closure", "Clarissa Mo"),
]


@router.get("/use-cases", response_model=list[UseCaseEntry], response_model_by_alias=True)
def list_use_cases() -> list[UseCaseEntry]:
    return [
        UseCaseEntry(
            use_case_id=use_case_id,
            name=name,
            module=module,
            owner=owner,
            implementation_status=(
                ImplementationStatus.IMPLEMENTED
                if use_case_id == "UC4"
                else ImplementationStatus.SCAFFOLDED
            ),
        )
        for use_case_id, name, module, owner in USE_CASES
    ]

