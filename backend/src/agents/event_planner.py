"""Event Planner Agent for natural-language requirement collection."""
from __future__ import annotations

import re
from typing import Any

from src.agents.base import AIAgent
from src.llm import LLMClient, LLMError
from src.shared.schemas import require_int, require_non_empty_str, require_valid_date


REQUIREMENT_GROUPS = (
    "event_type",
    "date_time",
    "location",
    "guest_count",
    "budget",
    "services",
)

PLANNER_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "updates": {
            "type": "object",
            "properties": {
                "event_type": {"type": ["string", "null"]},
                "event_date": {"type": ["string", "null"]},
                "start_time": {"type": ["string", "null"]},
                "end_time": {"type": ["string", "null"]},
                "location": {"type": ["string", "null"]},
                "guest_count": {"type": ["integer", "null"]},
                "budget_limit_cents": {"type": ["integer", "null"]},
                "required_services": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                },
                "customer_preferences": {"type": ["string", "null"]},
            },
            "required": [
                "event_type",
                "event_date",
                "start_time",
                "end_time",
                "location",
                "guest_count",
                "budget_limit_cents",
                "required_services",
                "customer_preferences",
            ],
            "additionalProperties": False,
        },
        "decision_summary": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["reply", "updates", "decision_summary"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = """You are the Event Planner Agent for an event management prototype.
Analyse the customer's latest message together with the saved event requirements.

Responsibilities:
- Extract only information the customer stated or dates that can be safely resolved using the supplied current date and timezone.
- Preserve saved information unless the customer clearly corrects it.
- Never invent a date, time, location, guest count, budget or service.
- Return null for an unchanged or unknown field.
- Dates use YYYY-MM-DD, times use HH:MM, and budgets use integer AUD cents.
- Supported mock vendor services are catering and photography. Other requested services may still be recorded but can return no vendor match.
- Ask one concise follow-up question for the most important missing or ambiguous item.
- Exact event date, start time and end time are required before vendor matching.
- decision_summary contains short user-visible facts such as "Resolved next Friday to 2026-10-23". Do not expose hidden chain-of-thought.
"""

_FOLLOW_UPS = {
    "event_type": "What type of event would you like to organise?",
    "date_time": "What is the exact event date, start time and finish time?",
    "location": "Which city or venue area should the event be held in?",
    "guest_count": "Approximately how many guests will attend?",
    "budget": "What is your total budget in Australian dollars?",
    "services": "Which services do you need, such as catering or photography?",
}


class EventPlannerAgent(AIAgent):
    """Collect and validate event requirements from a conversation."""

    agent_name = "planning"

    def __init__(self, llm: LLMClient) -> None:
        super().__init__(llm)

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict):
            return self.envelope(None, "error", "request must be a dict")
        event_id = request.get("event_id")
        message = request.get("message")
        try:
            event_id = require_non_empty_str(event_id, "event_id")
            message = require_non_empty_str(message, "message")
        except ValueError as exc:
            return self.envelope(None, "needs_input", str(exc))

        saved = request.get("saved_requirements") or {}
        if not isinstance(saved, dict):
            return self.envelope(event_id, "error", "saved_requirements must be an object")

        model_payload = {
            "current_date": request.get("current_date"),
            "timezone": request.get("timezone"),
            "saved_requirements": saved,
            "recent_conversation": request.get("history", [])[-8:],
            "latest_message": message,
        }
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": self._json(model_payload)},
        ]
        try:
            raw = self.llm.complete_json(
                messages,
                schema=PLANNER_OUTPUT_SCHEMA,
                schema_name="event_planner_analysis",
            )
            result = self._validate_model_result(raw)
            requirements = self._merge_requirements(saved, result["updates"])
        except (LLMError, ValueError, TypeError) as exc:
            return self.envelope(
                event_id,
                "error",
                f"The Event Planner could not analyse that message: {exc}",
            )

        missing = self.missing_groups(requirements)
        progress = {
            "completed": len(REQUIREMENT_GROUPS) - len(missing),
            "total": len(REQUIREMENT_GROUPS),
            "missing_fields": missing,
        }
        reply = result["reply"].strip()
        if missing:
            question = _FOLLOW_UPS[missing[0]]
            if "?" not in reply:
                reply = f"{reply} {question}".strip()
            status = "needs_input"
        else:
            reply = (
                f"{reply} Your requirements are complete. "
                "I’ll now ask the Vendor Procurement Manager Agent to find suitable options."
            ).strip()
            status = "success"

        return self.envelope(
            event_id,
            status,
            reply,
            {
                "requirements": requirements,
                "progress": progress,
                "decision_summary": result["decision_summary"],
                "ready_for_vendor_matching": not missing,
            },
        )

    @staticmethod
    def _json(value: dict[str, Any]) -> str:
        import json

        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _validate_model_result(raw: dict[str, Any]) -> dict[str, Any]:
        reply = require_non_empty_str(raw.get("reply"), "reply")
        updates = raw.get("updates")
        if not isinstance(updates, dict):
            raise ValueError("updates must be an object")
        summaries = raw.get("decision_summary")
        if not isinstance(summaries, list) or not all(
            isinstance(item, str) and item.strip() for item in summaries
        ):
            raise ValueError("decision_summary must be a list of non-empty strings")
        return {"reply": reply, "updates": updates, "decision_summary": summaries}

    @staticmethod
    def _merge_requirements(saved: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
        result = {
            "event_type": saved.get("event_type"),
            "event_date": saved.get("event_date"),
            "start_time": saved.get("start_time"),
            "end_time": saved.get("end_time"),
            "location": saved.get("location"),
            "guest_count": saved.get("guest_count"),
            "budget_limit_cents": saved.get("budget_limit_cents"),
            "required_services": list(saved.get("required_services") or []),
            "customer_preferences": saved.get("customer_preferences") or "",
        }
        for field, value in updates.items():
            if field not in result or value is None:
                continue
            if field in {"event_type", "location"}:
                result[field] = require_non_empty_str(value, field).strip()
            elif field == "event_date":
                result[field] = require_valid_date(value, field)
            elif field in {"start_time", "end_time"}:
                if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
                    raise ValueError(f"{field} must use HH:MM")
                result[field] = value
            elif field == "guest_count":
                result[field] = require_int(value, field, minimum=1)
            elif field == "budget_limit_cents":
                result[field] = require_int(value, field, minimum=1)
            elif field == "required_services":
                if not isinstance(value, list) or not value:
                    raise ValueError("required_services must be a non-empty list")
                cleaned = [require_non_empty_str(item, "required_services item").strip().lower() for item in value]
                result[field] = list(dict.fromkeys(cleaned))
            elif field == "customer_preferences":
                if not isinstance(value, str):
                    raise ValueError("customer_preferences must be a string")
                result[field] = value.strip()
        return result

    @staticmethod
    def missing_groups(requirements: dict[str, Any]) -> list[str]:
        missing = []
        if not requirements.get("event_type"):
            missing.append("event_type")
        if not all(requirements.get(key) for key in ("event_date", "start_time", "end_time")):
            missing.append("date_time")
        if not requirements.get("location"):
            missing.append("location")
        if not requirements.get("guest_count"):
            missing.append("guest_count")
        if not requirements.get("budget_limit_cents"):
            missing.append("budget")
        if not requirements.get("required_services"):
            missing.append("services")
        return missing
