"""Application workflow connecting Planning, Procurement and Financial Agents."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from src.agents.event_planner import EventPlannerAgent
from src.agents.financial_manager import FinancialManagerAgent
from src.agents.vendor_procurement_manager import VendorProcurementManagerAgent
from src.services.event_session_service import EventSessionService


class PlannerWorkflowService:
    """Coordinate business Agents without introducing a fifth Agent."""

    def __init__(
        self,
        planner: EventPlannerAgent,
        procurement: VendorProcurementManagerAgent,
        finance: FinancialManagerAgent,
        sessions: EventSessionService,
        *,
        timezone: str = "Australia/Sydney",
        llm_mode: str = "mock",
    ) -> None:
        self._planner = planner
        self._procurement = procurement
        self._finance = finance
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
            return self._response(session, planner_result["message"], trace)

        data = planner_result["data"]
        session["requirements"] = data["requirements"]
        session["progress"] = data["progress"]
        session["history"].extend(
            [
                {"role": "user", "content": message},
                {"role": "assistant", "content": planner_result["message"]},
            ]
        )
        session["stage"] = "requirements"
        reply = planner_result["message"]

        if data["ready_for_vendor_matching"]:
            self._clear_after_requirements(session)
            vendor_results = self._find_vendors(
                session["event_id"], session["requirements"]
            )
            trace.extend(self._trace(result) for result in vendor_results)
            recommendations = [
                item
                for result in vendor_results
                for item in result.get("data", {}).get("recommendations", [])
            ]
            session["vendor_recommendations"] = recommendations
            requested = session["requirements"].get("required_services") or []
            services = list(dict.fromkeys(requested))
            if not services:
                services = sorted({item["service_type"] for item in recommendations})
            if recommendations and services:
                session["proposal"] = self._build_proposal(session, services)
                session["stage"] = "proposal"
                reply += (
                    " I prepared a service plan and found catalogue candidates. "
                    "Review the plan, then request confirmed mock quotations."
                )
            else:
                session["stage"] = "vendor_attention"
                reply += (
                    " I could not find catalogue candidates for the current requirements. "
                    "Please change the date, location, guest count or services."
                )

        self._sessions.save(session)
        return self._response(
            session,
            reply,
            trace,
            decision_summary=data.get("decision_summary", []),
        )

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        session = self._sessions.get(event_id)
        return self._response(session, "Current event state.", []) if session else None

    def request_vendor_quotations(self, event_id: str) -> dict[str, Any]:
        session = self._require_session(event_id)
        proposal = session.get("proposal")
        if not isinstance(proposal, dict):
            raise ValueError("confirm complete requirements before requesting quotations")
        requirements = session["requirements"]
        quotations: list[dict[str, Any]] = []
        replies: list[dict[str, Any]] = []
        trace: list[dict[str, Any]] = []
        missing_services: list[str] = []
        for service in proposal["required_services"]:
            result = self._procurement.request_quotations(
                {
                    "event_id": event_id,
                    "proposal_id": proposal["proposal_id"],
                    "service_type": service,
                    "event_date": requirements["event_date"],
                    "guest_count": requirements["guest_count"],
                    "location": requirements["location"],
                }
            )
            trace.append(self._trace(result))
            service_quotes = result.get("data", {}).get("quotations", [])
            quotations.extend(service_quotes)
            replies.extend(result.get("data", {}).get("supplier_replies", []))
            if not service_quotes:
                missing_services.append(service)
        session["vendor_quotations"] = quotations
        session["supplier_replies"] = replies
        if missing_services:
            session["stage"] = "quotation_attention"
            reply = (
                "Some suppliers did not return an available quotation for: "
                + ", ".join(missing_services)
                + ". Review the supplier replies or revise the plan."
            )
        else:
            session["stage"] = "quotation_review"
            reply = (
                f"I received {len(quotations)} confirmed mock quotation"
                f"{'s' if len(quotations) != 1 else ''}. "
                "Select one quotation for each service."
            )
        self._sessions.save(session)
        return self._response(session, reply, trace)

    def confirm_quotation_selection(
        self, event_id: str, quotation_ids: list[str]
    ) -> dict[str, Any]:
        session = self._require_session(event_id)
        proposal = session.get("proposal")
        if not isinstance(proposal, dict):
            raise ValueError("proposal is missing")
        result = self._finance.handle(
            {
                "event_id": event_id,
                "action": "prepare_budget",
                "proposal": proposal,
                "quotations": session.get("vendor_quotations", []),
                "selected_quotation_ids": quotation_ids,
                "budget_limit_cents": session["requirements"].get(
                    "budget_limit_cents"
                ),
            }
        )
        trace = [self._trace(result)]
        data = result.get("data", {})
        session["selected_quotation_ids"] = list(quotation_ids)
        session["budget"] = data.get("budget")
        if result["status"] != "success":
            session["customer_quotation"] = None
            session["stage"] = "quotation_review"
            self._sessions.save(session)
            return self._response(session, result["message"], trace)

        quotation_result = self._finance.handle(
            {
                "event_id": event_id,
                "action": "generate_customer_quotation",
                "budget": data["budget"],
                "selected_quotations": data["selected_quotations"],
            }
        )
        trace.append(self._trace(quotation_result))
        if quotation_result["status"] != "success":
            raise ValueError(quotation_result["message"])
        session["customer_quotation"] = quotation_result["data"][
            "customer_quotation"
        ]
        session["stage"] = "quotation"
        self._sessions.save(session)
        return self._response(
            session,
            "Your customer quotation is ready. Review the full cost before approving it.",
            trace,
        )

    def approve_customer_quotation(self, event_id: str) -> dict[str, Any]:
        session = self._require_session(event_id)
        quotation = session.get("customer_quotation")
        if not isinstance(quotation, dict):
            raise ValueError("customer quotation is not ready")
        approval = {
            "event_id": event_id,
            "proposal_id": quotation["proposal_id"],
            "customer_quotation_id": quotation["customer_quotation_id"],
            "quotation_fingerprint": quotation["quotation_fingerprint"],
            "approved": True,
            "approved_quotation_ids": list(quotation["selected_quotation_ids"]),
            "approved_at": datetime.now(ZoneInfo(self._timezone)).isoformat(),
        }
        result = self._finance.handle(
            {
                "event_id": event_id,
                "action": "prepare_deposit",
                "customer_quotation": quotation,
                "approval": approval,
            }
        )
        if result["status"] != "success":
            raise ValueError(result["message"])
        session["approval"] = approval
        session["deposit"] = result["data"]["deposit"]
        session["stage"] = "payment"
        self._sessions.save(session)
        return self._response(
            session,
            "Quotation approved. Complete the simulated deposit payment before booking suppliers.",
            [self._trace(result)],
        )

    def pay_deposit(self, event_id: str) -> dict[str, Any]:
        session = self._require_session(event_id)
        deposit = session.get("deposit")
        if not isinstance(deposit, dict):
            raise ValueError("deposit request is not ready")
        if deposit.get("status") == "paid":
            return self._response(
                session, "The simulated deposit has already been paid.", []
            )
        result = self._finance.handle(
            {
                "event_id": event_id,
                "action": "simulate_deposit_payment",
                "deposit": deposit,
            }
        )
        if result["status"] != "success":
            raise ValueError(result["message"])
        session["deposit"] = result["data"]["deposit"]
        session["stage"] = "booking"
        self._sessions.save(session)
        return self._response(
            session,
            "The simulated deposit was paid successfully. You can now confirm the supplier bookings.",
            [self._trace(result)],
        )

    def confirm_bookings(self, event_id: str) -> dict[str, Any]:
        session = self._require_session(event_id)
        selected = set(session.get("selected_quotation_ids", []))
        quotations = [
            item
            for item in session.get("vendor_quotations", [])
            if item.get("quotation_id") in selected
        ]
        budget = dict(session.get("budget") or {})
        deposit = session.get("deposit")
        approval = session.get("approval")
        if not isinstance(deposit, dict) or deposit.get("status") != "paid":
            raise ValueError("simulated deposit must be paid before booking")
        budget["deposit_due_cents"] = deposit["amount_cents"]
        result = self._procurement.confirm_bookings(
            {
                "event_id": event_id,
                "proposal_id": session["proposal"]["proposal_id"],
                "quotations": quotations,
                "approval": approval,
                "budget": budget,
                "deposit": deposit,
            }
        )
        session["bookings"] = result.get("data", {}).get("bookings", [])
        session["booking_replies"] = result.get("data", {}).get(
            "supplier_replies", []
        )
        session["stage"] = (
            "booking_complete" if result["status"] == "success" else "booking_attention"
        )
        self._sessions.save(session)
        return self._response(session, result["message"], [self._trace(result)])

    def _build_proposal(
        self, session: dict[str, Any], services: list[str]
    ) -> dict[str, Any]:
        requirements = session["requirements"]
        total = requirements.get("vendor_budget_cents") or requirements[
            "budget_limit_cents"
        ]
        base, remainder = divmod(total, len(services))
        allocations = {
            service: base + (1 if index < remainder else 0)
            for index, service in enumerate(services)
        }
        return {
            "event_id": session["event_id"],
            "proposal_id": "P-" + uuid4().hex[:12].upper(),
            "summary": f"{requirements['event_type']} in {requirements['location']}",
            "required_services": list(services),
            "service_budget_cents": allocations,
            "status": "Draft",
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
                    "target_vendor_budget_cents": requirements.get(
                        "vendor_budget_cents"
                    ),
                    "customer_preferences": requirements.get(
                        "customer_preferences", ""
                    ),
                }
            )
            results.append(result)
        return results

    @staticmethod
    def _clear_after_requirements(session: dict[str, Any]) -> None:
        session.update(
            proposal=None,
            vendor_recommendations=[],
            vendor_quotations=[],
            supplier_replies=[],
            selected_quotation_ids=[],
            budget=None,
            customer_quotation=None,
            approval=None,
            deposit=None,
            bookings=[],
            booking_replies=[],
        )

    def _require_session(self, event_id: str) -> dict[str, Any]:
        session = self._sessions.get(event_id)
        if session is None:
            raise KeyError("event not found")
        return session

    def _response(
        self,
        session: dict[str, Any],
        reply: str,
        trace: list[dict[str, Any]],
        *,
        decision_summary: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "event_id": session["event_id"],
            "reply": reply,
            "stage": session.get("stage", "requirements"),
            "requirements": session.get("requirements", {}),
            "progress": session.get("progress", {}),
            "decision_summary": decision_summary or [],
            "proposal": session.get("proposal"),
            "vendor_recommendations": session.get("vendor_recommendations", []),
            "vendor_quotations": session.get("vendor_quotations", []),
            "supplier_replies": session.get("supplier_replies", []),
            "selected_quotation_ids": session.get("selected_quotation_ids", []),
            "budget": session.get("budget"),
            "customer_quotation": session.get("customer_quotation"),
            "approval": session.get("approval"),
            "deposit": session.get("deposit"),
            "bookings": session.get("bookings", []),
            "booking_replies": session.get("booking_replies", []),
            "agent_trace": trace,
            "llm_mode": self._llm_mode,
        }

    @staticmethod
    def _trace(result: dict[str, Any]) -> dict[str, Any]:
        return {
            "agent": result.get("agent", "workflow"),
            "status": result.get("status", "error"),
            "message": result.get("message", "No message"),
            "timestamp": result.get("timestamp"),
        }
