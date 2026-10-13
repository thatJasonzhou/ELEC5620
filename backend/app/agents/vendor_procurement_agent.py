from uuid import uuid4

from app.models.enums import AgentName
from app.schemas.common import AgentActivity
from app.services.mock_vendor_service import MockVendorService


class VendorProcurementManagerAgent:
    def __init__(self, vendor_service: MockVendorService) -> None:
        self._vendor_service = vendor_service

    def find_available_vendors(self, event_id: str) -> AgentActivity:
        vendors = self._vendor_service.list_available()
        result = ", ".join(vendor.name for vendor in vendors) or "No vendor is currently available."
        return AgentActivity(
            event_id=event_id,
            request_id=f"REQ-{uuid4().hex[:8].upper()}",
            agent=AgentName.VENDOR_PROCUREMENT_MANAGER,
            perception="Received the requested service arrangements.",
            decision=f"Found {len(vendors)} available mock vendors.",
            action="Returned available vendors for evaluation.",
            result=result,
        )

