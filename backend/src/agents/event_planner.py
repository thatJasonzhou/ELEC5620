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
- A venue is required for every event. required_services must include venue once the customer confirms their service choices. If the customer explicitly says no extra services are needed, return ["venue"] and set services_confirmed to true. If services have not been discussed, return null for both fields.
- When saved services already exist, understand requests to add, remove or replace a service. Return the complete updated required_services list and preserve every unaffected service. Never remove venue.
- Supported vendor service values are catering, photography, venue, sound, decoration, videography, lighting, entertainment, transport and event_staff. Normalise ordinary phrases such as "event staff" to event_staff and return these exact lowercase values. An activity may use at most five distinct service categories.
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

_SERVICE_ALIASES = {
    "catering": ("catering", "caterer", "food"),
    "photography": ("photography", "photographer", "photos"),
    "venue": ("venue", "function room", "event hall"),
    "sound": ("sound", "audio", "pa system"),
    "decoration": ("decoration", "decor", "event styling"),
    "videography": ("videography", "videographer", "video"),
    "lighting": ("lighting", "stage lights"),
    "entertainment": ("entertainment", "performer", "dj"),
    "transport": ("transport", "shuttle", "guest transfer"),
    "event_staff": ("event staff", "staffing", "waitstaff"),
}

_FOLLOW_UPS = {
    "event_type": "What type of event would you like to organise?",
    "date_time": "What is the exact event date, start time and finish time?",
    "location": "Which city or venue area should the event be held in?",
    "guest_count": "Approximately how many guests will attend?",
    "budget": "What is your total budget in Australian dollars?",
    "services": "Do you need any services, such as a venue, catering, photography or lighting? You can also say that no extra services are needed.",
}


SERVICE_SCHEDULE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "service_schedule": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "service_type": {"type": "string"},
                    "arrival_time": {"type": "string"},
                    "start_time": {"type": "string"},
                    "end_time": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": [
                    "service_type", "arrival_time", "start_time", "end_time", "notes"
                ],
                "additionalProperties": False,
            },
        },
        "decision_summary": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["reply", "service_schedule", "decision_summary"],
    "additionalProperties": False,
}

_SCHEDULE_PROMPT = """You are the Event Planner Agent preparing a service schedule.
Return one schedule item for every required service and no other services.
The venue is mandatory. Use the confirmed event date and event start/end times.
For an initial plan, choose practical arrival/setup times and service times.
For a revision, preserve unaffected schedule items and apply only the customer's requested changes.
Do not change services, event requirements, prices or suppliers.
Times use HH:MM. arrival_time must not be after start_time; start_time must be before end_time.
Service execution must remain within the confirmed event start/end window, although arrival/setup may be earlier.
Keep the reply concise and ask the customer to confirm or request a change.
decision_summary contains short user-visible scheduling changes, not hidden reasoning.
"""


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
            self._normalise_explicit_services(message, saved, result["updates"])
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
                "I’ll now prepare a timed service plan for you to review."
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

    def plan_services(self, request: dict[str, Any]) -> dict[str, Any]:
        """Create or revise a complete, validated service schedule."""
        if not isinstance(request, dict):
            return self.envelope(None, "error", "request must be a dict")
        event_id = request.get("event_id")
        try:
            event_id = require_non_empty_str(event_id, "event_id")
            requirements = request.get("requirements")
            if not isinstance(requirements, dict):
                raise ValueError("requirements must be an object")
            event_start = self._time(requirements.get("start_time"), "start_time")
            event_end = self._time(requirements.get("end_time"), "end_time")
            if event_start >= event_end:
                raise ValueError("event start_time must be before end_time")
            services = requirements.get("required_services")
            if not isinstance(services, list) or not services:
                raise ValueError("required_services must be a non-empty list")
            services = [require_non_empty_str(item, "service_type") for item in services]
            if "venue" not in services:
                raise ValueError("venue is required for every event")
            current = request.get("current_schedule") or []
            if not isinstance(current, list):
                raise ValueError("current_schedule must be a list")
            # A plan revision may remove a service. Do not send stale schedule
            # entries for that removed service back to the model.
            current = [
                item
                for item in current
                if not isinstance(item, dict)
                or item.get("service_type") in services
            ]
            message = request.get("message") or "Create the initial service schedule."
            message = require_non_empty_str(message, "message")
        except ValueError as exc:
            return self.envelope(event_id, "needs_input", str(exc))

        payload = {
            "event_date": requirements.get("event_date"),
            "event_start_time": requirements.get("start_time"),
            "event_end_time": requirements.get("end_time"),
            "required_services": services,
            "current_schedule": current,
            "customer_request": message,
        }
        try:
            raw = self.llm.complete_json(
                [
                    {"role": "system", "content": _SCHEDULE_PROMPT},
                    {"role": "user", "content": self._json(payload)},
                ],
                schema=SERVICE_SCHEDULE_SCHEMA,
                schema_name="event_service_schedule",
            )
            reply = require_non_empty_str(raw.get("reply"), "reply")
            summaries = raw.get("decision_summary")
            if not isinstance(summaries, list) or not all(
                isinstance(item, str) and item.strip() for item in summaries
            ):
                raise ValueError("decision_summary must contain non-empty strings")
            candidate_schedule = raw.get("service_schedule")
            if isinstance(candidate_schedule, list):
                # Structured model output can repeat an entry from the previous
                # plan after the customer removes that service. Drop only those
                # verified stale extras; all required entries are still checked
                # strictly by _validate_schedule below.
                candidate_schedule = [
                    item
                    for item in candidate_schedule
                    if not isinstance(item, dict)
                    or item.get("service_type") in services
                ]
            schedule = self._validate_schedule(
                candidate_schedule, services, event_start, event_end
            )
        except (LLMError, ValueError, TypeError) as exc:
            return self.envelope(
                event_id,
                "error",
                f"The Event Planner could not prepare the service schedule: {exc}",
            )
        return self.envelope(
            event_id,
            "success",
            reply,
            {"service_schedule": schedule, "decision_summary": summaries},
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
        """Correct dollar-as-cents model output for the customer's total budget."""
        explicit_total = cls._extract_explicit_budget_cents(message)
        if explicit_total is None:
            return

        updates["budget_limit_cents"] = explicit_total

    @classmethod
    def _normalise_explicit_services(
        cls, message: str, saved: dict[str, Any], updates: dict[str, Any]
    ) -> None:
        """Apply explicit add/remove/replace intent without losing saved services."""
        lower = message.lower()
        detected = cls._detect_services(lower)
        saved_services = list(saved.get("required_services") or [])
        services_confirmed = saved.get("services_confirmed") is True
        no_extras = bool(
            re.search(
                r"\b(?:no|without|do not need|don't need)\s+(?:any\s+)?(?:extra\s+|additional\s+)?services?\b",
                lower,
            )
        )

        if not services_confirmed:
            if no_extras:
                updates["required_services"] = ["venue"]
                updates["services_confirmed"] = True
            elif detected and updates.get("required_services") is None:
                updates["required_services"] = list(
                    dict.fromkeys(["venue", *detected])
                )
                updates["services_confirmed"] = True
            return

        current = list(dict.fromkeys(["venue", *saved_services]))
        replacement = re.search(r"\breplace\s+(.+?)\s+with\s+(.+)", lower)
        remove_intent = bool(
            re.search(
                r"\b(?:remove|delete|drop|cancel|without|do not need|don't need)\b",
                lower,
            )
        )
        add_intent = bool(
            re.search(
                r"\b(?:add|include|also|too|as well|need|want|would like|have|new service|additional service)\b",
                lower,
            )
        )
        only_intent = bool(re.search(r"\b(?:only need|only want|keep only)\b", lower))

        if no_extras:
            updated = ["venue"]
        elif replacement:
            removed = cls._detect_services(replacement.group(1))
            added = cls._detect_services(replacement.group(2))
            if "venue" in removed:
                raise ValueError("venue is required and cannot be removed")
            updated = [item for item in current if item not in removed or item == "venue"]
            updated = list(dict.fromkeys([*updated, *added]))
        elif remove_intent and detected:
            if "venue" in detected:
                raise ValueError("venue is required and cannot be removed")
            updated = [item for item in current if item not in detected or item == "venue"]
        elif only_intent:
            updated = list(dict.fromkeys(["venue", *detected]))
        elif add_intent and detected:
            updated = list(dict.fromkeys([*current, *detected]))
        else:
            # Mentioning an existing service to change its time is not a request
            # to replace the complete saved service list.
            updates["required_services"] = None
            return

        updates["required_services"] = list(dict.fromkeys(["venue", *updated]))
        updates["services_confirmed"] = True

    @staticmethod
    def _detect_services(text: str) -> list[str]:
        return [
            service_type
            for service_type, aliases in _SERVICE_ALIASES.items()
            if any(
                re.search(rf"\b{re.escape(alias)}\b", text)
                for alias in aliases
            )
        ]

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
            elif field == "customer_preferences":
                if not isinstance(value, str):
                    raise ValueError("customer_preferences must be a string")
                result[field] = value.strip()
        if services_were_updated:
            result["services_confirmed"] = True
        if result["services_confirmed"]:
            result["required_services"] = list(
                dict.fromkeys(["venue", *result["required_services"]])
            )
            if len(result["required_services"]) > 5:
                raise ValueError("required_services supports venue plus at most four extras")
        return result

    @staticmethod
    def _time(value: Any, name: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(
            r"(?:[01]\d|2[0-3]):[0-5]\d", value
        ):
            raise ValueError(f"{name} must use HH:MM")
        return value

    @classmethod
    def _validate_schedule(
        cls,
        value: Any,
        services: list[str],
        event_start: str,
        event_end: str,
    ) -> list[dict[str, str]]:
        if not isinstance(value, list) or len(value) != len(services):
            raise ValueError("service_schedule must contain one item per required service")
        result: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("service_schedule items must be objects")
            service = require_non_empty_str(item.get("service_type"), "service_type")
            if service not in services or service in seen:
                raise ValueError("service_schedule must use each required service exactly once")
            arrival = cls._time(item.get("arrival_time"), "arrival_time")
            start = cls._time(item.get("start_time"), "start_time")
            end = cls._time(item.get("end_time"), "end_time")
            notes = item.get("notes")
            if not isinstance(notes, str):
                raise ValueError("schedule notes must be text")
            if arrival > start or start >= end:
                raise ValueError("schedule times must satisfy arrival <= start < end")
            if start < event_start or end > event_end:
                raise ValueError("service execution must stay within the event time")
            seen.add(service)
            result.append(
                {
                    "service_type": service,
                    "arrival_time": arrival,
                    "start_time": start,
                    "end_time": end,
                    "notes": notes.strip(),
                }
            )
        if seen != set(services):
            raise ValueError("service_schedule does not cover every required service")
        order = {service: index for index, service in enumerate(services)}
        return sorted(result, key=lambda item: order[item["service_type"]])

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
