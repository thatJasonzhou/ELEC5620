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


class DemoLLMClient(LLMClient):
    """Extract common demo phrases and rank verified vendor candidates."""

    def complete(self, messages: list[dict[str, str]]) -> str:
        system = messages[0].get("content", "") if messages else ""
        if "Vendor Procurement Manager" in system:
            return json.dumps(self._vendor_response(messages), ensure_ascii=False)
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
            "vendor_budget_cents": None,
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

        total_budget = updates["budget_limit_cents"] or (
            payload.get("saved_requirements", {}).get("budget_limit_cents")
        )
        saved_vendor_budget = payload.get("saved_requirements", {}).get(
            "vendor_budget_cents"
        )
        if total_budget and (updates["budget_limit_cents"] is not None or not saved_vendor_budget):
            updates["vendor_budget_cents"] = max(1, int(total_budget * 0.7))

        services = [name for name in ("catering", "photography") if name in lower]
        no_services = bool(
            re.search(
                r"(?:no|without|do not need|don't need)\s+(?:any\s+)?(?:extra\s+|additional\s+)?services?",
                lower,
            )
        )
        if no_services:
            updates["required_services"] = []
            updates["services_confirmed"] = True
        elif services:
            updates["required_services"] = services
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
