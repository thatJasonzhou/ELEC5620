"""Operations worker for the minimal shared workflow (KAN-28).

All writes go through EventOperationsService. No Agent-to-Agent imports.
The injected LLM is reserved for a later advisory feature; this MVP does
not pretend deterministic scheduling is AI reasoning.
"""
from src.agents.base import AIAgent
from src.services.event_operations_service import EventOperationsService, OperationsBlocked, text


class EventOperationsAgent(AIAgent):
    agent_name = "operations"

    def __init__(self, llm, service: EventOperationsService):
        super().__init__(llm)
        if not isinstance(service, EventOperationsService):
            raise TypeError("service must implement EventOperationsService")
        self.service = service

    def handle(self, request):
        if not isinstance(request, dict):
            return self.envelope(None, "error", "request must be an object")
        event_id = request.get("event_id")
        if not isinstance(event_id, str) or not event_id.strip():
            event_id = None
        try:
            text(event_id, "event_id")
            action = text(request.get("action"), "action")
            if action == "generate_execution_plan":
                data = self.service.create_execution_plan(request)
            else:
                proposal_id = text(request.get("proposal_id"), "proposal_id")
                if action == "monitor_execution":
                    data = self.service.monitor_execution(event_id, proposal_id)
                elif action == "assign_task":
                    if "booking_id" not in request:
                        raise ValueError("booking_id is required (null means internal task)")
                    data = self.service.assign_task(event_id, proposal_id, request.get("task_id"), request["booking_id"])
                elif action == "update_task_status":
                    data = self.service.update_task_status(event_id, proposal_id, request.get("task_id"),
                                                           request.get("status"), request.get("reason"))
                elif action == "add_task":
                    data = self.service.add_task(event_id, proposal_id, request.get("title"),
                        request.get("start_at"), request.get("end_at"), request.get("booking_id"))
                else:
                    raise ValueError("Unsupported Operations action")
            return self.envelope(event_id, "success", "Operations request completed.", data)
        except OperationsBlocked as exc:
            return self.envelope(event_id, "blocked", str(exc))
        except (ValueError, TypeError) as exc:
            return self.envelope(event_id, "needs_input", str(exc))

    def generate_execution_plan(self, request):
        if not isinstance(request, dict):
            return self.handle(request)
        return self.handle({**request, "action": "generate_execution_plan"})
