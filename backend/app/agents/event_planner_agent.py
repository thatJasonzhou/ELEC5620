from uuid import uuid4

from app.models.enums import AgentName
from app.schemas.common import AgentActivity
from app.services.ai_service import AIService


class EventPlannerAgent:
    def __init__(self, ai_service: AIService) -> None:
        self._ai_service = ai_service

    async def draft_proposal(self, event_id: str, requirements: str) -> AgentActivity:
        result = await self._ai_service.generate(
            "Draft a concise event proposal from these requirements:\n" + requirements
        )
        return AgentActivity(
            event_id=event_id,
            request_id=f"REQ-{uuid4().hex[:8].upper()}",
            agent=AgentName.EVENT_PLANNER,
            perception="Received the customer's confirmed event requirements.",
            decision="The requirements are sufficient to draft an event proposal.",
            action="Generated a draft event proposal.",
            result=result,
        )

