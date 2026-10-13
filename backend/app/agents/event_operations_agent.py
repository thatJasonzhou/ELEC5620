from uuid import uuid4

from app.models.enums import AgentName
from app.schemas.common import AgentActivity
from app.services.ai_service import AIService


class EventOperationsManagerAgent:
    def __init__(self, ai_service: AIService) -> None:
        self._ai_service = ai_service

    async def suggest_recovery(self, event_id: str, issue: str) -> AgentActivity:
        result = await self._ai_service.generate(
            "Suggest a feasible event operations recovery action for this issue:\n" + issue
        )
        return AgentActivity(
            event_id=event_id,
            request_id=f"REQ-{uuid4().hex[:8].upper()}",
            agent=AgentName.EVENT_OPERATIONS_MANAGER,
            perception=f"Detected operational issue: {issue}",
            decision="The issue requires a recovery option before execution continues.",
            action="Suggested an operational recovery action.",
            result=result,
        )

