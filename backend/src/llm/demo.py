"""Clearly marked deterministic local demo client.

This is not an AI model. It keeps the full UI and agent handoff runnable before
an OpenAI key is configured, while using the same request/response contracts.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import re
from typing import Any

from .base import LLMClient, LLMError


_SERVICE_ALIASES = {
    "photography": ("photography", "photographer", "photos"),
    "catering": ("catering", "caterer", "food"),
    "venue": ("venue", "function room", "event hall"),
    "sound": ("sound", "audio", "pa system"),
    "decoration": ("decoration", "decor", "event styling"),
    "videography": ("videography", "videographer", "video"),
    "lighting": ("lighting", "stage lights"),
    "entertainment": ("entertainment", "performer", "dj"),
    "transport": ("transport", "shuttle", "guest transfer"),
    "event_staff": ("event staff", "staffing", "waitstaff"),
}


class DemoLLMClient(LLMClient):
    """Extract common demo phrases and rank verified vendor candidates."""

    def complete(self, messages: list[dict[str, str]]) -> str:
        system = messages[0].get("content", "") if messages else ""
        if "Vendor Procurement Manager" in system:
            return json.dumps(self._vendor_response(messages), ensure_ascii=False)
        if "preparing a service schedule" in system:
            return json.dumps(self._schedule_response(messages), ensure_ascii=False)
        return json.dumps(self._planner_response(messages), ensure_ascii=False)

    @staticmethod
    def _payload(messages: list[dict[str, str]]) -> dict[str, Any]:
        if not messages:
            raise LLMError("demo client received no messages")
        try:
            payload = json.loads(messages[-1]["content"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise LLMError("demo planner expects a JSON user payload") from exc
        if not isinstance(payload, dict):
            raise LLMError("demo planner payload must be an object")
        return payload

    def _planner_response(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        payload = self._payload(messages)
        text = str(payload.get("latest_message", ""))
        lower = text.lower()
        updates: dict[str, Any] = {
            "event_type": None,
            "event_date": None,
            "start_time": None,
            "end_time": None,
            "location": None,
            "guest_count": None,
            "budget_limit_cents": None,
            "required_services": None,
            "services_confirmed": None,
            "customer_preferences": None,
        }

        event_types = {
            "wedding": "Wedding",
            "birthday": "Birthday party",
            "conference": "Conference",
            "corporate": "Corporate event",
            "party": "Party",
        }
        for key, value in event_types.items():
            if key in lower:
                updates["event_type"] = value
                break

        if "sydney" in lower:
            updates["location"] = "Sydney"
        elif "melbourne" in lower:
            updates["location"] = "Melbourne"

        iso_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
        long_match = re.search(
            r"\b(\d{1,2})\s+(january|february|march|april|may|june|july|august|"
            r"september|october|november|december)\s+(20\d{2})\b",
            lower,
        )
        if iso_match:
            updates["event_date"] = iso_match.group(1)
        elif long_match:
            updates["event_date"] = datetime.strptime(
                " ".join(long_match.groups()), "%d %B %Y"
            ).date().isoformat()
        elif "next friday" in lower:
            current = date.fromisoformat(str(payload.get("current_date")))
            days = (4 - current.weekday()) % 7
            updates["event_date"] = (current + timedelta(days=days or 7)).isoformat()

        time_match = re.search(
            r"(?:from\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:to|until|-)\s*"
            r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?",
            lower,
        )
        if time_match:
            updates["start_time"] = self._normalise_time(
                time_match.group(1), time_match.group(2), time_match.group(3)
            )
            updates["end_time"] = self._normalise_time(
                time_match.group(4), time_match.group(5), time_match.group(6)
            )

        guest_match = re.search(r"\b(\d{1,5})\s*(?:guests?|people|persons?)\b", lower)
        if guest_match:
            updates["guest_count"] = int(guest_match.group(1))

        budget_match = re.search(
            r"(?:budget(?:\s+is)?\s*(?:of\s*)?|\$)\$?\s*([\d,]+)(?:\s*(k))?",
            lower,
        )
        if budget_match:
            amount = int(budget_match.group(1).replace(",", ""))
            if budget_match.group(2):
                amount *= 1000
            updates["budget_limit_cents"] = amount * 100

        services = [
            service_type
            for service_type, aliases in _SERVICE_ALIASES.items()
            if any(
                re.search(rf"\b{re.escape(alias)}\b", lower)
                for alias in aliases
            )
        ]
        no_services = bool(
            re.search(
                r"(?:no|without|do not need|don't need)\s+(?:any\s+)?(?:extra\s+|additional\s+)?services?",
                lower,
            )
        )
        if no_services:
            updates["required_services"] = ["venue"]
            updates["services_confirmed"] = True
        elif services:
            updates["required_services"] = list(dict.fromkeys(["venue", *services]))
            updates["services_confirmed"] = True

        if any(word in lower for word in ("outdoor", "vegetarian", "modern", "casual")):
            updates["customer_preferences"] = text

        return {
            "reply": "Thanks — I have analysed the information you provided.",
            "updates": updates,
            "decision_summary": [
                f"Detected {key.replace('_', ' ')}"
                for key, value in updates.items()
                if value not in (None, [], "")
            ],
        }

    def _schedule_response(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        payload = self._payload(messages)
        services = payload.get("required_services") or []
        event_start = str(payload.get("event_start_time"))
        event_end = str(payload.get("event_end_time"))
        current = {
            item.get("service_type"): dict(item)
            for item in payload.get("current_schedule", [])
            if isinstance(item, dict) and isinstance(item.get("service_type"), str)
        }
        defaults = {
            "venue": (120, "Venue access and setup"),
            "catering": (60, "Food preparation and service setup"),
            "photography": (30, "Equipment setup before coverage"),
            "sound": (90, "Audio setup and sound check"),
            "decoration": (120, "Decoration installation"),
            "videography": (45, "Camera and audio setup"),
            "lighting": (90, "Lighting installation and testing"),
            "entertainment": (45, "Performer setup and sound check"),
            "transport": (30, "Vehicle arrival before guest movement"),
            "event_staff": (30, "Staff briefing before the event"),
        }
        schedule = []
        for service in services:
            if service in current:
                item = current[service]
            else:
                lead, note = defaults.get(service, (30, "Supplier setup"))
                item = {
                    "service_type": service,
                    "arrival_time": self._shift_time(event_start, -lead),
                    "start_time": event_start,
                    "end_time": event_end,
                    "notes": note,
                }
            schedule.append(item)

        request = str(payload.get("customer_request", "")).lower()
        service = next(
            (
                name
                for name, aliases in _SERVICE_ALIASES.items()
                if any(re.search(rf"\b{re.escape(alias)}\b", request) for alias in aliases)
            ),
            None,
        )
        time_match = re.search(r"\b(?:at|arrive(?:s|d)?\s+at|from)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", request)
        if service and time_match:
            new_time = self._normalise_time(
                time_match.group(1), time_match.group(2), time_match.group(3)
            )
            for item in schedule:
                if item["service_type"] == service:
                    item["arrival_time"] = new_time
                    item["start_time"] = max(new_time, event_start)
                    if item["start_time"] >= item["end_time"]:
                        item["end_time"] = event_end

        return {
            "reply": "I prepared the service schedule. Please confirm it or tell me what time you would like to change.",
            "service_schedule": schedule,
            "decision_summary": ["Prepared one arrival and service window for each requested service"],
        }

    @staticmethod
    def _shift_time(value: str, minutes: int) -> str:
        moment = datetime.strptime(value, "%H:%M")
        total_minutes = max(0, moment.hour * 60 + moment.minute + minutes)
        return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"

    @staticmethod
    def _normalise_time(hour_text: str, minute_text: str | None, suffix: str | None) -> str:
        hour = int(hour_text)
        minute = int(minute_text or "0")
        if suffix == "pm" and hour != 12:
            hour += 12
        elif suffix == "am" and hour == 12:
            hour = 0
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise LLMError("demo client detected an invalid time")
        return f"{hour:02d}:{minute:02d}"

    @staticmethod
    def _vendor_response(messages: list[dict[str, str]]) -> dict[str, Any]:
        prompt = messages[-1].get("content", "")
        marker = "Candidates (facts, already verified by code):\n"
        ending = "\n\nRespond with STRICT JSON"
        try:
            candidate_text = prompt.split(marker, 1)[1].split(ending, 1)[0]
            candidates = json.loads(candidate_text)
        except (IndexError, json.JSONDecodeError) as exc:
            raise LLMError("demo client could not read vendor candidates") from exc
        if not candidates:
            return {"recommendations": []}
        minimum_price = min(item["total_price_cents"] for item in candidates)
        maximum_rating = max(item["rating"] for item in candidates)
        maximum_capacity = max(item["guest_capacity"] for item in candidates)
        ranked = sorted(
            candidates,
            key=lambda item: (
                not item.get("within_target_budget", True),
                abs(item.get("budget_gap_cents", 0)),
                -item["rating"],
                item["total_price_cents"],
            ),
        )[:3]
        recommendations = []
        for item in ranked:
            codes = []
            if item["total_price_cents"] == minimum_price:
                codes.append("lowest_price")
            if item["rating"] == maximum_rating:
                codes.append("highest_rating")
            if item["guest_capacity"] == maximum_capacity:
                codes.append("highest_capacity")
            if item.get("within_target_budget", True):
                codes.append("within_budget")
            recommendations.append(
                {
                    "vendor_id": item["vendor_id"],
                    "offering_id": item["offering_id"],
                    "basis_codes": codes,
                    "reason": "A strong match based on the verified price, rating and capacity facts.",
                }
            )
        return {"recommendations": recommendations}
