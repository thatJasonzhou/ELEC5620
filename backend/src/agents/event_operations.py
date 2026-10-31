"""Event Operations Agent backed by deterministic execution rules."""
from __future__ import annotations

from typing import Any

from src.agents.base import AIAgent
from src.llm import LLMClient
from src.services.event_operations_service import EventOperationsService, OperationsBlocked
from src.shared.schemas import require_non_empty_str


class EventOperationsAgent(AIAgent):
    agent_name = "operations"

    def __init__(self, llm: LLMClient, service: EventOperationsService) -> None:
        super().__init__(llm)
        if not isinstance(service, EventOperationsService):
            raise TypeError("service must be an EventOperationsService")
        self._service = service

    def snapshot_event(self, event_id: str) -> dict[str, Any] | None:
        return self._service.snapshot_event(event_id)

    def restore_event(self, event_id: str, snapshot: dict[str, Any] | None) -> None:
        self._service.restore_event(event_id, snapshot)

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict):
            return self.envelope(None, "error", "request must be an object")
        event_id = request.get("event_id")
        try:
            action = require_non_empty_str(request.get("action"), "action")
            if action == "list_operations":
                plans = self._service.list_execution_plans()
                return self.envelope(
                    None,
                    "success",
                    "Operations plans loaded.",
                    {"plans": plans},
                )
            if action == "clear_operations":
                cleared = self._service.clear_all()
                return self.envelope(
                    None,
                    "success",
                    "Simulated Operations cases cleared.",
                    {"cleared_cases": cleared},
                )
            event_id = require_non_empty_str(event_id, "event_id")
            if action == "generate_execution_plan":
                plan = self._service.generate_execution_plan(request)
            elif action == "monitor_execution":
                plan = self._service.monitor_execution(
                    event_id, request.get("proposal_id")
                )
            else:
                proposal_id = require_non_empty_str(
                    request.get("proposal_id"), "proposal_id"
                )
                fields = {
                    key: value
                    for key, value in request.items()
                    if key not in {"action", "event_id", "proposal_id"}
                }
                plan = self._service.perform_action(
                    event_id, proposal_id, action, fields
                )
        except OperationsBlocked as exc:
            return self.envelope(event_id, "blocked", str(exc))
        except KeyError as exc:
            return self.envelope(event_id, "error", str(exc))
        except (TypeError, ValueError) as exc:
            return self.envelope(event_id, "blocked", str(exc))
        return self.envelope(
            event_id,
            "success",
            "Operations request completed.",
            {"execution_plan": plan},
        )
