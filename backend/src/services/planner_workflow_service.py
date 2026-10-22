"""Application workflow connecting Planning and Procurement."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.agents.event_planner import EventPlannerAgent
from src.agents.vendor_procurement_manager import VendorProcurementManagerAgent
from src.services.event_session_service import EventSessionService


class PlannerWorkflowService:
    """Coordinate existing Agents without introducing a fifth Agent."""

    def __init__(
        self,
        planner: EventPlannerAgent,
        procurement: VendorProcurementManagerAgent,
        sessions: EventSessionService,
        *,
        timezone: str = "Australia/Sydney",
        llm_mode: str = "mock",
    ) -> None:
        self._planner = planner
        self._procurement = procurement
        self._sessions = sessions
        self._timezone = timezone
        self._llm_mode = llm_mode

    def handle_message(self, *, event_id: str | None, message: str) -> dict[str, Any]:
        session = self._sessions.get_or_create(event_id)
        now = datetime.now(ZoneInfo(self._timezone))
        planner_result = self._planner.handle(
            {
                "event_id": session["event_id"],
                "message": message,
                "current_date": now.date().isoformat(),
                "timezone": self._timezone,
                "saved_requirements": session["requirements"],
                "history": session["history"],
            }
        )
        trace = [self._trace(planner_result)]
        if planner_result["status"] == "error":
            return self._response(session, planner_result["message"], trace, [])

        data = planner_result["data"]
        session["requirements"] = data["requirements"]
        session["history"].extend(
            [
                {"role": "user", "content": message},
                {"role": "assistant", "content": planner_result["message"]},
            ]
        )
        session["stage"] = "requirements"
        reply = planner_result["message"]
        vendor_results: list[dict[str, Any]] = []

        if data["ready_for_vendor_matching"]:
            session["stage"] = "vendors"
            vendor_results = self._find_vendors(session["event_id"], session["requirements"])
            trace.extend(self._trace(result) for result in vendor_results)
            recommendations = [
                item
                for result in vendor_results
                for item in result.get("data", {}).get("recommendations", [])
            ]
            session["vendor_recommendations"] = recommendations
            if recommendations:
                session["stage"] = "vendor_review"
                service_count = len({item["service_type"] for item in recommendations})
                reply += (
                    f"\n\nI found vendor options for {service_count} service"
                    f"{'s' if service_count != 1 else ''}. "
                    "Please select one vendor for each service."
                )
            else:
                blocked_services = [
                    result.get("requested_service", "requested service")
                    for result in vendor_results
                    if result.get("status") != "success"
                ]
                reply += (
                    " I could not find a catalogue match for "
                    + ", ".join(blocked_services)
                    + ". You can change the date, location, guest count or requested services."
                )

        self._sessions.save(session)
        return self._response(session, reply, trace, vendor_results, data)

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        return self._sessions.get(event_id)

    def confirm_vendor_selection(
        self, event_id: str, selected_offering_ids: list[str]
    ) -> dict[str, Any]:
        session = self._sessions.get(event_id)
        if session is None:
            raise KeyError("event not found")
        available = {
            item["offering_id"]: item
            for item in session.get("vendor_recommendations", [])
        }
        selected = list(dict.fromkeys(selected_offering_ids))
        if not selected:
            raise ValueError("select at least one vendor option")
        unknown = [item for item in selected if item not in available]
        if unknown:
            raise ValueError(f"unknown offering ids: {', '.join(unknown)}")
        selected_services = [available[item]["service_type"] for item in selected]
        if len(selected_services) != len(set(selected_services)):
            raise ValueError("select only one vendor for each service")
        expected_services = {item["service_type"] for item in available.values()}
        missing_services = expected_services - set(selected_services)
        if missing_services:
            raise ValueError(
                "select one vendor for each service: "
                + ", ".join(sorted(missing_services))
            )
        session["selected_offering_ids"] = selected
        session["stage"] = "proposal"
        session["history"].append(
            {
                "role": "assistant",
                "content": "The customer confirmed one vendor for each service.",
            }
        )
        self._sessions.save(session)
        return {
            "event_id": event_id,
            "stage": session["stage"],
            "selected_offering_ids": selected,
            "message": "Vendor choices confirmed. The selected services can now be combined into the event proposal.",
        }
    def _find_vendors(
        self, event_id: str, requirements: dict[str, Any]
    ) -> list[dict[str, Any]]:
        results = []
        service_types = requirements.get("required_services") or ["any"]
        for service_type in service_types:
            result = self._procurement.handle(
                {
                    "event_id": event_id,
                    "service_type": service_type,
                    "event_date": requirements["event_date"],
                    "guest_count": requirements["guest_count"],
                    "location": requirements["location"],
                    "target_vendor_budget_cents": requirements.get("vendor_budget_cents"),
                    "customer_preferences": requirements.get("customer_preferences", ""),
                }
            )
            result["requested_service"] = (
                service_type if service_type != "any" else "available vendor"
            )
            results.append(result)
        return results

    def _response(
        self,
        session: dict[str, Any],
        reply: str,
        trace: list[dict[str, Any]],
        vendor_results: list[dict[str, Any]],
        planner_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        requirements = session.get("requirements", {})
        progress = (planner_data or {}).get(
            "progress",
            {"completed": 0, "total": 6, "missing_fields": []},
        )
        return {
            "event_id": session["event_id"],
            "reply": reply,
            "stage": session.get("stage", "requirements"),
            "requirements": requirements,
            "progress": progress,
            "decision_summary": (planner_data or {}).get("decision_summary", []),
            "vendor_recommendations": session.get("vendor_recommendations", []),
            "vendor_results": vendor_results,
            "agent_trace": trace,
            "llm_mode": self._llm_mode,
        }

    @staticmethod
    def _trace(result: dict[str, Any]) -> dict[str, Any]:
        return {
            "agent": result.get("agent", "unknown"),
            "status": result.get("status", "error"),
            "message": result.get("message", "No message"),
            "timestamp": result.get("timestamp"),
        }
