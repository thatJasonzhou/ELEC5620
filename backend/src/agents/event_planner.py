"""Event Planner Agent for natural-language requirement collection."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
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
                "services_confirmed": {"type": ["boolean", "null"]},
                "vendor_budget_cents": {"type": ["integer", "null"]},
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
                "services_confirmed",
                "vendor_budget_cents",
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
- Dates use YYYY-MM-DD, times use HH:MM, and budgets use integer AUD cents. For example, AUD 30,000, $30000 and 30000 dollars must all be returned as 3000000 cents, never 30000.
- Services are an optional vendor filter, but the customer's preference must be confirmed once. If the customer names a service, return it in required_services and set services_confirmed to true. If the customer explicitly says no extra services are needed, return an empty required_services list and set services_confirmed to true. If services have not been discussed, return null for both fields.
- Supported vendor service values are catering, photography, venue, sound, decoration, videography, lighting, entertainment, transport and event_staff. Normalise ordinary phrases such as "event staff" to event_staff and return these exact lowercase values. An activity may use at most five distinct service categories.
- When the total budget is known, propose vendor_budget_cents as the total amount available across all selected vendors. It must be positive and must not exceed budget_limit_cents. Recalculate it when the total budget changes. Do not ask the customer to provide this internal allocation.
- Ask one concise follow-up question for the most important missing or ambiguous item.
- Exact event date, start time and end time are required before vendor matching.
- Keep reply to one or two short sentences. Do not repeat a field-by-field summary, JSON field names, internal budget fields or agent hand-off details.
- decision_summary contains short user-visible facts such as "Resolved next Friday to 2026-10-23". Do not expose hidden chain-of-thought.
"""

_EXPLICIT_BUDGET_RE = re.compile(
    r"(?:\bbudget\b[^\d$]{0,24}(?:AUD\s*)?\$?\s*|\$\s*)"
    r"(?P<amount>\d[\d,]*(?:\.\d{1,2})?)\s*(?P<thousands>k)?"
    r"(?:\s*(?:AUD|Australian\s+dollars?|dollars?))?\b",
    re.IGNORECASE,
)

_FOLLOW_UPS = {
    "event_type": "What type of event would you like to organise?",
    "date_time": "What is the exact event date, start time and finish time?",
    "location": "Which city or venue area should the event be held in?",
    "guest_count": "Approximately how many guests will attend?",
    "budget": "What is your total budget in Australian dollars?",
    "services": "Do you need any services, such as a venue, catering, photography or lighting? You can also say that no extra services are needed.",
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
            self._normalise_explicit_budget(message, saved, result["updates"])
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
        if missing:
            question = _FOLLOW_UPS[missing[0]]
            reply = f"Thanks — I’ve saved those details.\n\n{question}"
            status = "needs_input"
        else:
            reply = (
                "Thanks — your event requirements are complete.\n\n"
                "I’ll now find suitable vendors for each requested service."
            )
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
    def _extract_explicit_budget_cents(message: str) -> int | None:
        """Read an explicitly stated AUD budget without trusting LLM unit conversion."""
        match = _EXPLICIT_BUDGET_RE.search(message)
        if match is None:
            return None
        try:
            dollars = Decimal(match.group("amount").replace(",", ""))
        except InvalidOperation:
            return None
        if match.group("thousands"):
            dollars *= 1000
        cents = int((dollars * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return cents if cents > 0 else None

    @classmethod
    def _normalise_explicit_budget(
        cls,
        message: str,
        saved: dict[str, Any],
        updates: dict[str, Any],
    ) -> None:
        """Correct dollar-as-cents model output and keep the vendor allocation ratio."""
        explicit_total = cls._extract_explicit_budget_cents(message)
        if explicit_total is None:
            return

        model_total = updates.get("budget_limit_cents")
        model_vendor = updates.get("vendor_budget_cents")
        updates["budget_limit_cents"] = explicit_total

        # A correctly converted model total should still pass through the normal
        # validation below, including rejection of an over-budget allocation.
        if model_total == explicit_total and model_vendor is not None:
            return

        ratio_total = model_total
        ratio_vendor = model_vendor
        if not (
            type(ratio_total) is int
            and ratio_total > 0
            and type(ratio_vendor) is int
            and ratio_vendor > 0
        ):
            ratio_total = saved.get("budget_limit_cents")
            ratio_vendor = saved.get("vendor_budget_cents")

        if (
            type(ratio_total) is int
            and ratio_total > 0
            and type(ratio_vendor) is int
            and ratio_vendor > 0
        ):
            scaled_vendor = (
                explicit_total * ratio_vendor + ratio_total // 2
            ) // ratio_total
            updates["vendor_budget_cents"] = min(
                explicit_total, max(1, scaled_vendor)
            )
        else:
            updates["vendor_budget_cents"] = explicit_total

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
            "services_confirmed": saved.get("services_confirmed") is True,
            "vendor_budget_cents": saved.get("vendor_budget_cents"),
            "customer_preferences": saved.get("customer_preferences") or "",
        }
        services_were_updated = False
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
                if not isinstance(value, list):
                    raise ValueError("required_services must be a list")
                cleaned = [require_non_empty_str(item, "required_services item").strip().lower() for item in value]
                unique_services = list(dict.fromkeys(cleaned))
                if len(unique_services) > 5:
                    raise ValueError(
                        "required_services supports at most five service categories"
                    )
                result[field] = unique_services
                services_were_updated = True
            elif field == "services_confirmed":
                if not isinstance(value, bool):
                    raise ValueError("services_confirmed must be a boolean")
                result[field] = value
            elif field == "vendor_budget_cents":
                result[field] = require_int(value, field, minimum=1)
            elif field == "customer_preferences":
                if not isinstance(value, str):
                    raise ValueError("customer_preferences must be a string")
                result[field] = value.strip()
        if services_were_updated:
            result["services_confirmed"] = True
        total_budget = result.get("budget_limit_cents")
        vendor_budget = result.get("vendor_budget_cents")
        if vendor_budget is not None and total_budget is not None and vendor_budget > total_budget:
            raise ValueError("vendor_budget_cents must not exceed budget_limit_cents")
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
        if requirements.get("services_confirmed") is not True:
            missing.append("services")
        return missing
