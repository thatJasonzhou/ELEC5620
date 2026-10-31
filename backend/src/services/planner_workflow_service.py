"""Application workflow connecting Planning, Procurement and Financial Agents."""
from __future__ import annotations

from copy import deepcopy
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime
from hashlib import sha256
from itertools import product
import re
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from src.agents.event_planner import EventPlannerAgent
from src.agents.event_operations import EventOperationsAgent
from src.agents.financial_manager import FinancialManagerAgent
from src.agents.vendor_procurement_manager import VendorProcurementManagerAgent
from src.services.event_session_service import EventSessionService
from src.services.supplier_portal_service import SupplierPortalService
from src.shared.costing import calculate_event_costs


class PlannerWorkflowService:
    """Coordinate business Agents without introducing a fifth Agent."""

    def __init__(
        self,
        planner: EventPlannerAgent,
        procurement: VendorProcurementManagerAgent,
        finance: FinancialManagerAgent,
        sessions: EventSessionService,
        *,
        operations: EventOperationsAgent | None = None,
        supplier_portal: SupplierPortalService | None = None,
        timezone: str = "Australia/Sydney",
        llm_mode: str = "mock",
    ) -> None:
        self._planner = planner
        self._procurement = procurement
        self._finance = finance
        self._sessions = sessions
        self._operations = operations
        self._supplier_portal = supplier_portal
        self._timezone = timezone
        self._llm_mode = llm_mode
        self._demo_checkpoints: dict[str, list[dict[str, Any]]] = {}

    @property
    def supplier_portal(self) -> SupplierPortalService | None:
        return self._supplier_portal

    @staticmethod
    def _demo_stage_label(stage: str) -> str:
        return {
            "requirements": "Requirements",
            "plan_review": "Plan review",
            "proposal": "Plan confirmed",
            "awaiting_vendor_quotes": "Supplier quotations",
            "quotation_review": "Quotation review",
            "quotation": "Customer quotation",
            "awaiting_supplier_confirmation": "Supplier confirmation",
            "payment": "Deposit payment",
            "booking": "Booking",
            "operations": "Operations",
            "final_payment": "Final payment",
            "completed": "Completed",
        }.get(stage, stage.replace("_", " ").title())

    def capture_demo_checkpoint(
        self, event_id: str, label: str | None = None
    ) -> dict[str, Any]:
        """Capture the complete current state used by the classroom demo."""
        session = self._require_session(event_id)
        stage = str(session.get("stage", "requirements"))
        checkpoint = {
            "checkpoint_id": "DCP-" + uuid4().hex[:12].upper(),
            "stage": stage,
            "label": label or self._demo_stage_label(stage),
            "created_at": datetime.now(ZoneInfo(self._timezone)).isoformat(),
            "session": deepcopy(session),
            "procurement": self._procurement.snapshot_event(event_id),
            "supplier_portal": (
                self._supplier_portal.snapshot_event(event_id)
                if self._supplier_portal is not None
                else None
            ),
            "operations": (
                self._operations.snapshot_event(event_id)
                if self._operations is not None
                else None
            ),
        }
        checkpoints = self._demo_checkpoints.setdefault(event_id, [])
        checkpoints.append(checkpoint)
        if len(checkpoints) > 40:
            del checkpoints[:-40]
        return self._checkpoint_metadata(checkpoint)

    @staticmethod
    def _checkpoint_metadata(checkpoint: dict[str, Any]) -> dict[str, Any]:
        return {
            key: checkpoint[key]
            for key in ("checkpoint_id", "stage", "label", "created_at")
        }

    def list_demo_checkpoints(self, event_id: str) -> list[dict[str, Any]]:
        self._require_session(event_id)
        return [
            self._checkpoint_metadata(item)
            for item in self._demo_checkpoints.get(event_id, [])
        ]

    def _restore_demo_snapshot(
        self, event_id: str, checkpoint: dict[str, Any], reply: str
    ) -> dict[str, Any]:
        self._procurement.restore_event(event_id, deepcopy(checkpoint.get("procurement")))
        if self._supplier_portal is not None:
            self._supplier_portal.restore_event(
                event_id, deepcopy(checkpoint.get("supplier_portal"))
            )
        if self._operations is not None:
            self._operations.restore_event(
                event_id, deepcopy(checkpoint.get("operations"))
            )
        session = deepcopy(checkpoint["session"])
        self._sessions.save(session)
        # Returning to an earlier point creates a new demo branch. Discard the
        # abandoned future so repeated Undo cannot jump forwards into it.
        checkpoints = self._demo_checkpoints.get(event_id, [])
        index = next(i for i, item in enumerate(checkpoints)
                     if item["checkpoint_id"] == checkpoint["checkpoint_id"])
        self._demo_checkpoints[event_id] = checkpoints[:index + 1]
        response = self._response(session, reply, [])
        response["conversation_history"] = deepcopy(session.get("history", []))
        return response

    def restore_previous_demo_checkpoint(self, event_id: str) -> dict[str, Any]:
        session = self._require_session(event_id)
        checkpoints = self._demo_checkpoints.get(event_id, [])
        if not checkpoints:
            raise ValueError("No previous demo checkpoint is available")
        supplier_state = (
            self._supplier_portal.snapshot_event(event_id)
            if self._supplier_portal is not None
            else None
        )
        operations_state = (
            self._operations.snapshot_event(event_id)
            if self._operations is not None
            else None
        )
        procurement_state = self._procurement.snapshot_event(event_id)
        checkpoint = next(
            (
                item
                for item in reversed(checkpoints)
                if item.get("session") != session
                or item.get("supplier_portal") != supplier_state
                or item.get("operations") != operations_state
                or item.get("procurement") != procurement_state
            ),
            None,
        )
        if checkpoint is None:
            raise ValueError("The demo is already at its earliest checkpoint")
        return self._restore_demo_snapshot(
            event_id,
            checkpoint,
            f"Demo restored to {checkpoint['label']}.",
        )

    def restart_demo_stage(self, event_id: str) -> dict[str, Any]:
        session = self._require_session(event_id)
        current_stage = session.get("stage", "requirements")
        checkpoint = next(
            (
                item
                for item in self._demo_checkpoints.get(event_id, [])
                if item.get("stage") == current_stage
            ),
            None,
        )
        if checkpoint is None:
            raise ValueError("No checkpoint is available for the current stage")
        return self._restore_demo_snapshot(
            event_id,
            checkpoint,
            f"The {self._demo_stage_label(str(current_stage))} stage was restarted.",
        )

    def restore_demo_checkpoint(
        self, event_id: str, checkpoint_id: str
    ) -> dict[str, Any]:
        identity = checkpoint_id.strip() if isinstance(checkpoint_id, str) else ""
        checkpoint = next(
            (
                item
                for item in self._demo_checkpoints.get(event_id, [])
                if item.get("checkpoint_id") == identity
            ),
            None,
        )
        if checkpoint is None:
            raise ValueError("Demo checkpoint was not found")
        return self._restore_demo_snapshot(
            event_id,
            checkpoint,
            f"Demo loaded at {checkpoint['label']}.",
        )

    def reset_demo_event(self, event_id: str) -> dict[str, Any]:
        self._require_session(event_id)
        self._procurement.restore_event(event_id, None)
        if self._supplier_portal is not None:
            self._supplier_portal.restore_event(event_id, None)
        if self._operations is not None:
            self._operations.restore_event(event_id, None)
        session = self._sessions.reset(event_id)
        self._demo_checkpoints[event_id] = []
        return self._response(
            session,
            "The demo was reset. Tell me what kind of event you would like to plan.",
            [],
        )

    def handle_message(self, *, event_id: str | None, message: str) -> dict[str, Any]:
        session = self._sessions.get_or_create(event_id)
        budget_update = self._extract_budget_update(
            message,
            current_budget_cents=session.get("requirements", {}).get(
                "budget_limit_cents"
            ),
            required_total_cents=(session.get("budget") or {}).get(
                "estimated_total_cents"
            ),
        )
        if isinstance(session.get("proposal"), dict) and budget_update is not None:
            return self._apply_budget_update(session, message, budget_update)
        if session.get("stage") == "plan_review" and isinstance(
            session.get("proposal"), dict
        ):
            now = datetime.now(ZoneInfo(self._timezone))
            requirements_result = self._planner.handle(
                {
                    "event_id": session["event_id"],
                    "message": message,
                    "current_date": now.date().isoformat(),
                    "timezone": self._timezone,
                    "saved_requirements": session["requirements"],
                    "history": session["history"],
                }
            )
            trace = [self._trace(requirements_result)]
            if requirements_result["status"] == "error":
                return self._response(session, requirements_result["message"], trace)
            requirement_data = requirements_result["data"]
            if not requirement_data.get("ready_for_vendor_matching"):
                return self._response(
                    session,
                    requirements_result["message"],
                    trace,
                    decision_summary=requirement_data.get("decision_summary", []),
                )
            session["requirements"] = requirement_data["requirements"]
            session["progress"] = requirement_data["progress"]
            schedule_result = self._planner.plan_services(
                {
                    "event_id": session["event_id"],
                    "requirements": session["requirements"],
                    "current_schedule": session["proposal"].get(
                        "service_schedule", []
                    ),
                    "message": message,
                }
            )
            trace.append(self._trace(schedule_result))
            if schedule_result["status"] == "success":
                session["plan_version"] = int(session.get("plan_version", 0)) + 1
                session["proposal"] = self._build_proposal(
                    session,
                    session["requirements"]["required_services"],
                    schedule_result["data"]["service_schedule"],
                )
                session["history"].extend(
                    [
                        {"role": "user", "content": message},
                        {"role": "assistant", "content": schedule_result["message"]},
                    ]
                )
                self._sessions.save(session)
            return self._response(
                session,
                schedule_result["message"],
                trace,
                decision_summary=schedule_result.get("data", {}).get(
                    "decision_summary", []
                ),
            )
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
            current_schedule = []
            if isinstance(session.get("proposal"), dict):
                current_schedule = session["proposal"].get("service_schedule", [])
            self._clear_after_requirements(session)
            schedule_result = self._planner.plan_services(
                {
                    "event_id": session["event_id"],
                    "requirements": session["requirements"],
                    "current_schedule": current_schedule,
                    "message": message,
                }
            )
            trace.append(self._trace(schedule_result))
            requested = session["requirements"].get("required_services") or []
            services = list(dict.fromkeys(requested))
            if schedule_result["status"] == "success" and services:
                session["plan_version"] = int(session.get("plan_version", 0)) + 1
                session["proposal"] = self._build_proposal(
                    session,
                    services,
                    schedule_result["data"]["service_schedule"],
                )
                session["plan_confirmed"] = False
                session["stage"] = "plan_review"
                reply = schedule_result["message"]
            else:
                session["stage"] = "planner_attention"
                reply = schedule_result["message"]

        self._sessions.save(session)
        return self._response(
            session,
            reply,
            trace,
            decision_summary=data.get("decision_summary", []),
        )

    @staticmethod
    def _extract_budget_update(
        message: str,
        *,
        current_budget_cents: int | None,
        required_total_cents: int | None,
    ) -> int | None:
        """Read a total or relative budget change without touching supplier state."""
        if not isinstance(message, str):
            return None
        lower = message.lower()
        budget_words = r"budget|cost|price|spend|预算|成本|费用|花费"
        increase_words = r"increase|raise|add|more|higher|增加|提高|追加|多加|加"
        # Adding a service, guests or a time is not a financial instruction.
        # Require a budget term or an explicit currency amount before taking
        # this shortcut around the Planner's normal requirement analysis.
        budget_context = re.search(budget_words, lower)
        amount_pattern = r"(?P<amount>\d[\d,]*(?:\.\d{1,2})?)\s*(?P<unit>k|万)?"
        number = re.search(
            r"(?:\baud\s*|a?\$\s*)" + amount_pattern,
            lower,
        ) or re.search(
            amount_pattern + r"\s*(?:\baud\b|\bdollars?\b|澳元|元|预算|成本|费用|花费)",
            lower,
        )
        if budget_context is None and number is None:
            return None
        if number is None and budget_context is not None:
            # Bind a bare amount to the financial clause, rather than taking
            # the first number in a message (which may be a time or headcount).
            number = re.match(
                r"[^\d.!?;\n]{0,24}" + amount_pattern,
                lower[budget_context.end():],
            )
            if number is not None:
                suffix = lower[budget_context.end() + number.end():]
                if re.match(r"\s*(?::|am\b|pm\b|guests?\b|people\b|staff\b|hours?\b)", suffix):
                    return None
        if number is None:
            consent = re.search(
                r"can increase|okay with|accept|agree|可以增加|接受|同意",
                lower,
            )
            return required_total_cents if consent and required_total_cents else None
        try:
            dollars = Decimal(number.group("amount").replace(",", ""))
        except InvalidOperation:
            return None
        if number.group("unit") == "k":
            dollars *= 1000
        elif number.group("unit") == "万":
            dollars *= 10000
        amount_cents = int(
            (dollars * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        if amount_cents <= 0:
            return None
        relative = re.search(increase_words, lower) is not None
        explicit_total = re.search(
            r"(?:increase|raise)\s+(?:(?:my|the|total)\s+)*(?:budget\s+|it\s+)?to|new\s+budget|total\s+budget|预算.{0,6}(?:改为|提高到|增加到)|总预算",
            lower,
        ) is not None
        if relative and not explicit_total and current_budget_cents:
            return current_budget_cents + amount_cents
        return amount_cents

    def _apply_budget_update(
        self, session: dict[str, Any], message: str, budget_limit_cents: int
    ) -> dict[str, Any]:
        """Recalculate Finance from stored quotes without contacting suppliers again."""
        session["requirements"]["budget_limit_cents"] = budget_limit_cents
        session["history"].append({"role": "user", "content": message})
        quotations = list(session.get("vendor_quotations", []))
        selected_ids = list(
            session.get("selected_quotation_ids")
            or session.get("recommended_quotation_ids")
            or []
        )
        amount = f"AUD {budget_limit_cents / 100:,.0f}"
        if not quotations or not selected_ids:
            reply = (
                f"Your total budget is now {amount}. The existing supplier requests "
                "are unchanged, and Finance will check the same replies when they arrive."
            )
            session["history"].append({"role": "assistant", "content": reply})
            self._sessions.save(session)
            return self._response(
                session,
                reply,
                [],
                decision_summary=[f"Updated total budget to {amount}"],
            )

        result = self._finance.handle(
            {
                "event_id": session["event_id"],
                "action": "prepare_budget",
                "proposal": session["proposal"],
                "quotations": quotations,
                "selected_quotation_ids": selected_ids,
                "budget_limit_cents": budget_limit_cents,
            }
        )
        trace = [self._trace(result)]
        session["budget"] = result.get("data", {}).get("budget")
        if result["status"] == "success":
            quotation_result = self._finance.handle(
                {
                    "event_id": session["event_id"],
                    "action": "generate_customer_quotation",
                    "budget": result["data"]["budget"],
                    "selected_quotations": result["data"]["selected_quotations"],
                }
            )
            trace.append(self._trace(quotation_result))
            if quotation_result["status"] != "success":
                raise ValueError(quotation_result["message"])
            session["customer_quotation"] = quotation_result["data"][
                "customer_quotation"
            ]
            session["finance_feedback"] = {
                "message": "Finance recalculated the existing supplier quotations after the customer increased the total budget."
            }
            session["stage"] = "quotation"
            reply = (
                f"Your total budget is now {amount}. Finance recalculated the existing "
                "supplier bundle and it is within budget; no supplier was asked to quote again."
            )
        else:
            budget = result.get("data", {}).get("budget") or {}
            over = int(budget.get("over_budget_cents") or 0)
            session["customer_quotation"] = None
            session["finance_feedback"] = {
                "message": result["message"],
                "over_budget_cents": over,
                "supplier_budget_limit_cents": budget.get(
                    "supplier_budget_limit_cents"
                ),
            }
            session["stage"] = "planner_adjustment"
            reply = (
                f"Your total budget is now {amount}, but the same supplier bundle is still "
                f"over budget by AUD {over / 100:,.0f}. Existing quotations were retained."
            )
        session["history"].append({"role": "assistant", "content": reply})
        self._sessions.save(session)
        return self._response(
            session,
            reply,
            trace,
            decision_summary=[
                f"Updated total budget to {amount}",
                "Reused the existing supplier quotations",
            ],
        )

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        session = self._sessions.get(event_id)
        if session is not None and self._supplier_portal is not None:
            session = self._sync_supplier_quotations(session)
            session = self._sync_supplier_confirmations(session)
        if session is not None:
            session = self._sync_operations(session)
        return self._response(session, "Current event state.", []) if session else None

    def _sync_operations(self, session: dict[str, Any]) -> dict[str, Any]:
        if self._operations is None or not session.get("operations_plan"):
            return session
        result = self._operations.handle(
            {
                "action": "monitor_execution",
                "event_id": session["event_id"],
                "proposal_id": session["proposal"]["proposal_id"],
            }
        )
        if result["status"] == "success":
            session["operations_plan"] = result["data"]["execution_plan"]
            self._sessions.save(session)
        return session

    def list_operations(self) -> list[dict[str, Any]]:
        if self._operations is None:
            return []
        result = self._operations.handle({"action": "list_operations"})
        if result["status"] != "success":
            raise ValueError(result["message"])
        return result["data"]["plans"]

    def clear_operations(self) -> int:
        if self._operations is None:
            return 0
        result = self._operations.handle({"action": "clear_operations"})
        if result["status"] != "success":
            raise ValueError(result["message"])
        return int(result["data"]["cleared_cases"])

    def perform_operations_action(
        self, event_id: str, action: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        session = self._require_session(event_id)
        if self._operations is None or not session.get("operations_plan"):
            raise ValueError("Operations is not ready for this event")
        result = self._operations.handle(
            {
                "action": action,
                "event_id": event_id,
                "proposal_id": session["proposal"]["proposal_id"],
                **fields,
            }
        )
        if result["status"] != "success":
            raise ValueError(result["message"])
        session["operations_plan"] = result["data"]["execution_plan"]
        trace = [self._trace(result)]
        reply = "Operations status updated."
        if action in {"finalize_execution", "confirm_event_completion"} and session["operations_plan"].get("finalized"):
            payment_result = self._finance.handle(
                {
                    "event_id": event_id,
                    "action": "prepare_final_payment",
                    "customer_quotation": session.get("customer_quotation"),
                    "deposit": session.get("deposit"),
                    "operations_plan": session["operations_plan"],
                }
            )
            if payment_result["status"] != "success":
                raise ValueError(payment_result["message"])
            session["final_payment"] = payment_result["data"]["final_payment"]
            session["stage"] = (
                "completed"
                if session["final_payment"]["status"] == "paid"
                else "final_payment"
            )
            trace.append(self._trace(payment_result))
            reply = (
                "You confirmed that the event is complete. Operations is now closed, and Finance prepared the remaining balance for simulated payment."
                if session["stage"] == "final_payment"
                else "You confirmed that the event is complete. Operations is closed and no remaining balance is due."
            )
        self._sessions.save(session)
        return self._response(session, reply, trace)

    def pay_final_payment(self, event_id: str) -> dict[str, Any]:
        session = self._require_session(event_id)
        operations = session.get("operations_plan")
        if not isinstance(operations, dict) or operations.get("finalized") is not True:
            raise ValueError("Operations must be finalized before paying the balance")
        final_payment = session.get("final_payment")
        if not isinstance(final_payment, dict):
            raise ValueError("final payment request is not ready")
        if final_payment.get("status") == "paid":
            session["stage"] = "completed"
            self._sessions.save(session)
            return self._response(
                session, "The simulated final balance has already been paid.", []
            )
        result = self._finance.handle(
            {
                "event_id": event_id,
                "action": "simulate_final_payment",
                "final_payment": final_payment,
            }
        )
        if result["status"] != "success":
            raise ValueError(result["message"])
        session["final_payment"] = result["data"]["final_payment"]
        session["stage"] = "completed"
        self._sessions.save(session)
        return self._response(
            session,
            "The remaining balance was paid successfully. The event is now paid in full and closed.",
            [self._trace(result)],
        )

    def submit_feedback(
        self, event_id: str, rating: int, comments: str
    ) -> dict[str, Any]:
        session = self._require_session(event_id)
        final_payment = session.get("final_payment")
        if not isinstance(final_payment, dict) or final_payment.get("status") != "paid":
            raise ValueError("pay the final balance before submitting feedback")
        if self._operations is None or not session.get("operations_plan"):
            raise ValueError("Operations is not ready for this event")
        result = self._operations.handle(
            {
                "action": "record_feedback",
                "event_id": event_id,
                "proposal_id": session["proposal"]["proposal_id"],
                "rating": rating,
                "comments": comments,
            }
        )
        if result["status"] != "success":
            raise ValueError(result["message"])
        session["operations_plan"] = result["data"]["execution_plan"]
        session["stage"] = "completed"
        self._sessions.save(session)
        return self._response(
            session,
            "Thank you for your feedback. We’ve recorded your suggestions and will use them to improve our service.",
            [self._trace(result)],
        )

    def confirm_plan(self, event_id: str) -> dict[str, Any]:
        """Lock the Planner schedule before any supplier enquiry is created."""
        session = self._require_session(event_id)
        proposal = session.get("proposal")
        if not isinstance(proposal, dict) or session.get("stage") != "plan_review":
            raise ValueError("a service schedule must be ready for review")
        vendor_results = self._find_vendors(event_id, session["requirements"])
        recommendations = [
            item
            for result in vendor_results
            for item in result.get("data", {}).get("recommendations", [])
        ]
        services = proposal["required_services"]
        matched = {item["service_type"] for item in recommendations}
        trace = [self._trace(result) for result in vendor_results]
        if not set(services).issubset(matched):
            session["stage"] = "vendor_attention"
            self._sessions.save(session)
            return self._response(
                session,
                "The schedule is saved, but the catalogue has no suitable supplier for every service. Please revise the date, location, guests or services.",
                trace,
            )
        proposal["status"] = "Approved"
        session["proposal"] = proposal
        session["plan_confirmed"] = True
        session["vendor_recommendations"] = recommendations
        session["stage"] = "proposal"
        self._sessions.save(session)
        return self._response(
            session,
            "The service schedule is confirmed. You can now send the approved times to Procurement.",
            trace,
        )

    def request_vendor_quotations(self, event_id: str) -> dict[str, Any]:
        session = self._require_session(event_id)
        proposal = session.get("proposal")
        if not isinstance(proposal, dict) or proposal.get("status") != "Approved":
            raise ValueError("confirm the service schedule before requesting quotations")
        if self._supplier_portal is not None:
            return self._create_supplier_portal_requests(session)
        requirements = session["requirements"]
        quotations: list[dict[str, Any]] = list(
            session.get("automatic_quotations", [])
        )
        replies: list[dict[str, Any]] = [
            dict(item) for item in session.get("supplier_replies", [])
            if item.get("response_mode") == "automatic_mock"
        ]
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
                f"I received {len(quotations)} confirmed supplier quotation"
                f"{'s' if len(quotations) != 1 else ''}. "
                "Select one quotation for each service."
            )
        self._sessions.save(session)
        return self._response(session, reply, trace)

    def confirm_quotation_selection(
        self, event_id: str, quotation_ids: list[str]
    ) -> dict[str, Any]:
        session = self._require_session(event_id)
        if self._supplier_portal is not None:
            session = self._sync_supplier_quotations(session)
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
        session["approval"] = approval
        selected = {
            item["quotation_id"]: item
            for item in session.get("vendor_quotations", [])
            if item.get("quotation_id") in quotation["selected_quotation_ids"]
        }
        schedules = {
            item["service_type"]: item
            for item in session["proposal"]["service_schedule"]
        }
        manual_requests = []
        automatic_confirmations = []
        for quotation_id in quotation["selected_quotation_ids"]:
            item = selected.get(quotation_id)
            if item is None:
                raise ValueError("approved quotation is no longer available")
            schedule = schedules[item["service_type"]]
            if item["service_type"] == "venue":
                manual_requests.append(
                    {
                        "event_id": event_id,
                        "proposal_id": quotation["proposal_id"],
                        "customer_quotation_id": quotation[
                            "customer_quotation_id"
                        ],
                        "quotation_id": quotation_id,
                        "vendor_id": item["vendor_id"],
                        "vendor_name": item.get("vendor_name", item["vendor_id"]),
                        "offering_id": item["offering_id"],
                        "service_type": item["service_type"],
                        "event_date": session["requirements"]["event_date"],
                        "arrival_time": schedule["arrival_time"],
                        "service_start_time": schedule["start_time"],
                        "service_end_time": schedule["end_time"],
                        "quoted_total_cents": item["quoted_total_cents"],
                    }
                )
            else:
                automatic_confirmations.append(
                    {
                        "confirmation_id": "AUTO-" + quotation_id,
                        "quotation_id": quotation_id,
                        "vendor_id": item["vendor_id"],
                        "offering_id": item["offering_id"],
                        "service_type": item["service_type"],
                        "status": "confirmed",
                        "confirmed": True,
                        "response_mode": "automatic_mock",
                    }
                )
        if self._supplier_portal is None:
            manual = []
            automatic_confirmations.extend(
                {
                    "confirmation_id": "AUTO-" + item["quotation_id"],
                    "quotation_id": item["quotation_id"],
                    "vendor_id": item["vendor_id"],
                    "offering_id": item["offering_id"],
                    "service_type": item["service_type"],
                    "status": "confirmed",
                    "confirmed": True,
                    "response_mode": "automatic_mock",
                }
                for item in selected.values()
                if item["service_type"] == "venue"
            )
        else:
            if not manual_requests:
                raise ValueError(
                    "the selected venue requires a manual supplier confirmation"
                )
            manual = self._supplier_portal.create_confirmation_requests(
                manual_requests
            )
            requested_ids = {item["quotation_id"] for item in manual_requests}
            manual = [
                item
                for item in manual
                if item.get("quotation_id") in requested_ids
            ]
        session["supplier_confirmations"] = [*manual, *automatic_confirmations]
        session["deposit"] = None
        if self._supplier_portal is None:
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
            session["deposit"] = result["data"]["deposit"]
            session["stage"] = "payment"
        else:
            session["stage"] = "awaiting_supplier_confirmation"
        self._sessions.save(session)
        return self._response(
            session,
            (
                "Quotation approved. The selected venue supplier must confirm the exact time and price before the deposit is requested; other services are Mock-confirmed."
                if self._supplier_portal is not None
                else "Quotation approved and all suppliers are Mock-confirmed. The simulated deposit is ready."
            ),
            [
                {
                    "agent": "procurement",
                    "status": "success",
                    "message": "Created the venue supplier's conditional pre-deposit confirmation.",
                    "timestamp": datetime.now(ZoneInfo(self._timezone)).isoformat(),
                }
            ],
        )

    def _sync_supplier_confirmations(
        self, session: dict[str, Any]
    ) -> dict[str, Any]:
        if session.get("stage") != "awaiting_supplier_confirmation":
            return session
        proposal = session.get("proposal")
        if not isinstance(proposal, dict):
            return session
        manual = self._supplier_portal.list_confirmation_requests(
            event_id=session["event_id"], proposal_id=proposal["proposal_id"]
        )
        selected_ids = set(
            (session.get("customer_quotation") or {}).get(
                "selected_quotation_ids", []
            )
        )
        manual = [
            item for item in manual if item.get("quotation_id") in selected_ids
        ]
        automatic = [
            item for item in session.get("supplier_confirmations", [])
            if item.get("response_mode") == "automatic_mock"
        ]
        session["supplier_confirmations"] = [*manual, *automatic]
        if any(item["status"] == "pending" for item in manual):
            self._sessions.save(session)
            return session
        declined = next(
            (item for item in manual if item["status"] == "declined"), None
        )
        if declined is not None:
            self._replace_declined_venue(session, declined["quotation_id"])
            self._sessions.save(session)
            return session

        quotation = session.get("customer_quotation")
        approval = session.get("approval")
        if not isinstance(quotation, dict) or not isinstance(approval, dict):
            session["stage"] = "quotation_attention"
            self._sessions.save(session)
            return session
        result = self._finance.handle(
            {
                "event_id": session["event_id"],
                "action": "prepare_deposit",
                "customer_quotation": quotation,
                "approval": approval,
            }
        )
        if result["status"] == "success":
            session["deposit"] = result["data"]["deposit"]
            session["stage"] = "payment"
        else:
            session["stage"] = "quotation_attention"
        self._sessions.save(session)
        return session

    def _replace_declined_venue(
        self, session: dict[str, Any], declined_quotation_id: str
    ) -> None:
        selected = list(session.get("selected_quotation_ids", []))
        declined_ids = set(session.get("declined_quotation_ids", []))
        declined_ids.add(declined_quotation_id)
        session["declined_quotation_ids"] = sorted(declined_ids)
        alternatives = sorted(
            [
                item for item in session.get("vendor_quotations", [])
                if item.get("service_type") == "venue"
                and item.get("quotation_id") not in selected
                and item.get("quotation_id") not in declined_ids
            ],
            key=lambda item: (
                int(item.get("rank", 99)),
                item["quoted_total_cents"],
                item["quotation_id"],
            ),
        )
        for alternative in alternatives:
            revised = [
                alternative["quotation_id"] if identity == declined_quotation_id else identity
                for identity in selected
            ]
            result = self._finance.handle(
                {
                    "event_id": session["event_id"],
                    "action": "prepare_budget",
                    "proposal": session["proposal"],
                    "quotations": session["vendor_quotations"],
                    "selected_quotation_ids": revised,
                    "budget_limit_cents": session["requirements"][
                        "budget_limit_cents"
                    ],
                }
            )
            if result["status"] != "success":
                continue
            quotation_result = self._finance.handle(
                {
                    "event_id": session["event_id"],
                    "action": "generate_customer_quotation",
                    "budget": result["data"]["budget"],
                    "selected_quotations": result["data"]["selected_quotations"],
                }
            )
            if quotation_result["status"] != "success":
                continue
            session["selected_quotation_ids"] = revised
            session["recommended_quotation_ids"] = revised
            session["budget"] = result["data"]["budget"]
            session["customer_quotation"] = quotation_result["data"][
                "customer_quotation"
            ]
            session["approval"] = None
            session["supplier_confirmations"] = []
            session["deposit"] = None
            session["stage"] = "quotation"
            session["finance_feedback"] = {
                "message": "The selected venue declined. Procurement chose the next eligible quoted venue and Finance recalculated the total. Customer approval is required again."
            }
            return
        session["approval"] = None
        session["supplier_confirmations"] = []
        session["customer_quotation"] = None
        session["stage"] = "planner_adjustment"
        session["finance_feedback"] = {
            "reason_code": "no_available_suppliers",
            "message": "The venue declined and no remaining quoted venue can satisfy the approved proposal. Planner review is required."
        }

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
        trace = [self._trace(result)]
        if result["status"] == "success" and self._operations is not None:
            operations_result = self._operations.handle(
                {
                    "event_id": event_id,
                    "action": "generate_execution_plan",
                    "event_date": session["requirements"]["event_date"],
                    "proposal": session["proposal"],
                    "bookings": session["bookings"],
                }
            )
            trace.append(self._trace(operations_result))
            if operations_result["status"] == "success":
                session["operations_plan"] = operations_result["data"][
                    "execution_plan"
                ]
                session["stage"] = "operations"
            else:
                session["stage"] = "booking_attention"
        else:
            session["stage"] = (
                "booking_complete"
                if result["status"] == "success"
                else "booking_attention"
            )
        self._sessions.save(session)
        reply = (
            "All selected suppliers are booked and Operations has created the execution plan."
            if session["stage"] == "operations"
            else result["message"]
        )
        return self._response(session, reply, trace)

    def _create_supplier_portal_requests(
        self, session: dict[str, Any]
    ) -> dict[str, Any]:
        """Create three manual venue RFQs and mock every other service."""
        proposal = session["proposal"]
        requirements = session["requirements"]
        recommendations = session.get("vendor_recommendations", [])
        services = proposal["required_services"]
        missing = [
            service for service in services
            if not any(item.get("service_type") == service for item in recommendations)
        ]
        if missing:
            raise ValueError(
                "no supplier candidates are available for: " + ", ".join(missing)
            )
        schedules = {
            item["service_type"]: item for item in proposal["service_schedule"]
        }
        manual_service = "venue"
        requests = []
        venue_candidates = [
            item for item in recommendations if item["service_type"] == manual_service
        ][:3]
        for candidate in venue_candidates:
            service = candidate["service_type"]
            schedule = schedules[service]
            requests.append(
                {
                    "event_id": session["event_id"],
                    "proposal_id": proposal["proposal_id"],
                    "vendor_id": candidate["vendor_id"],
                    "vendor_name": candidate["vendor_name"],
                    "offering_id": candidate["offering_id"],
                    "service_type": service,
                    "event_summary": proposal["summary"],
                    "event_type": requirements["event_type"],
                    "event_date": requirements["event_date"],
                    "arrival_time": schedule["arrival_time"],
                    "service_start_time": schedule["start_time"],
                    "service_end_time": schedule["end_time"],
                    "location": requirements["location"],
                    "guest_count": requirements["guest_count"],
                    "catalogue_estimate_cents": candidate["total_price_cents"],
                }
            )
        if not requests:
            raise ValueError("no venue candidates are available for the manual demo")
        created = self._supplier_portal.create_quote_requests(requests)

        automatic_quotations: list[dict[str, Any]] = []
        automatic_replies: list[dict[str, Any]] = []
        traces: list[dict[str, Any]] = []
        for service in services:
            if service == manual_service:
                continue
            result = self._procurement.request_quotations(
                {
                    "event_id": session["event_id"],
                    "proposal_id": proposal["proposal_id"],
                    "service_type": service,
                    "event_date": requirements["event_date"],
                    "guest_count": requirements["guest_count"],
                    "location": requirements["location"],
                }
            )
            traces.append(self._trace(result))
            shortlisted = {
                (item["vendor_id"], item["offering_id"])
                for item in recommendations
                if item["service_type"] == service
            }
            for quotation in result.get("data", {}).get("quotations", []):
                if (quotation["vendor_id"], quotation["offering_id"]) in shortlisted:
                    automatic_quotations.append(
                        {**quotation, "response_mode": "automatic_mock"}
                    )
            for reply in result.get("data", {}).get("supplier_replies", []):
                if (reply.get("vendor_id"), reply.get("offering_id")) in shortlisted:
                    automatic_replies.append(
                        {**reply, "response_mode": "automatic_mock"}
                    )

        session["supplier_requests"] = created
        session["automatic_quotations"] = automatic_quotations
        session["procurement_batch_id"] = "PB-" + uuid4().hex[:16].upper()
        session["vendor_quotations"] = []
        session["supplier_replies"] = automatic_replies
        session["quotation_rankings"] = []
        session["recommended_quotation_ids"] = []
        session["quotation_comparison_complete"] = False
        session["quotation_comparison_fingerprint"] = None
        session["selected_quotation_ids"] = []
        session["stage"] = "awaiting_vendor_quotes"
        self._sessions.save(session)
        return self._response(
            session,
            "Your confirmed plan has been sent to suitable suppliers. "
            "I’ll let you know when their quotations are ready.",
            [
                {
                    "agent": "procurement",
                    "status": "success",
                    "message": f"Created {len(created)} manual venue RFQ(s); other services use Mock replies.",
                    "timestamp": datetime.now(ZoneInfo(self._timezone)).isoformat(),
                },
                *traces,
            ],
        )

    def _sync_supplier_quotations(
        self, session: dict[str, Any]
    ) -> dict[str, Any]:
        """Validate supplier portal replies and update the customer workflow."""
        proposal = session.get("proposal")
        if not isinstance(proposal, dict):
            return session
        requests = self._supplier_portal.list_quote_requests(
            event_id=session["event_id"], proposal_id=proposal["proposal_id"]
        )
        if not requests:
            return session
        quotations: list[dict[str, Any]] = [
            dict(item) for item in session.get("automatic_quotations", [])
        ]
        replies: list[dict[str, Any]] = [
            dict(item)
            for item in session.get("supplier_replies", [])
            if item.get("response_mode") == "automatic_mock"
        ]
        pending = False
        for request in requests:
            response = request.get("response")
            if response is None:
                pending = True
                replies.append(
                    {
                        "vendor_id": request["vendor_id"],
                        "offering_id": request["offering_id"],
                        "status": "pending",
                        "available": None,
                        "quoted_total_cents": None,
                        "reason": "Waiting for the supplier to respond.",
                    }
                )
                continue
            replies.append(response)
            if response["status"] != "accepted":
                continue
            quotations.append(
                {
                    "event_id": response["event_id"],
                    "proposal_id": response["proposal_id"],
                    "quotation_id": response["quotation_id"],
                    "vendor_id": response["vendor_id"],
                    "offering_id": response["offering_id"],
                    "service_type": request["service_type"],
                    "vendor_name": request["vendor_name"],
                    "event_date": response["event_date"],
                    "guest_count": response["guest_count"],
                    "quoted_total_cents": response["quoted_total_cents"],
                    "available": True,
                    "mock": True,
                    "scenario_id": response["scenario_id"],
                    "arrival_time": request["arrival_time"],
                    "service_start_time": request["service_start_time"],
                    "service_end_time": request["service_end_time"],
                    "response_mode": "manual_demo",
                    "recommendation_reason": (
                        f"{request['vendor_name']} entered this confirmed simulated "
                        "quotation through the supplier portal."
                    ),
                }
            )
        quotations.sort(
            key=lambda item: (
                item["service_type"], item["quoted_total_cents"], item["vendor_id"]
            )
        )
        session["supplier_requests"] = requests
        session["supplier_replies"] = replies
        if session.get("stage") in {
            "awaiting_vendor_quotes", "quotation_attention", "quotation_review"
        }:
            services = set(proposal["required_services"])
            quoted_services = {item["service_type"] for item in quotations}
            if pending:
                session["stage"] = "awaiting_vendor_quotes"
            elif services.issubset(quoted_services):
                quotations = self._compare_supplier_quotations(
                    session, quotations
                )
                session["stage"] = (
                    "quotation_review"
                    if session.get("quotation_comparison_complete")
                    else "quotation_attention"
                )
                if session.get("quotation_comparison_complete"):
                    session["vendor_quotations"] = quotations
                    self._prepare_recommended_customer_quote(session)
            else:
                session["stage"] = "quotation_attention"
                session["quotation_comparison_complete"] = False
                session["recommended_quotation_ids"] = []
            session["vendor_quotations"] = quotations
        self._sessions.save(session)
        return session

    def _compare_supplier_quotations(
        self,
        session: dict[str, Any],
        quotations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Run the Procurement Agent's second decision once per quote set."""
        proposal = session["proposal"]
        fingerprint_payload = [
            {
                "quotation_id": item["quotation_id"],
                "service_type": item["service_type"],
                "quoted_total_cents": item["quoted_total_cents"],
            }
            for item in sorted(quotations, key=lambda value: value["quotation_id"])
        ]
        fingerprint = sha256(
            json.dumps(
                fingerprint_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if (
            session.get("quotation_comparison_complete") is True
            and session.get("quotation_comparison_fingerprint") == fingerprint
        ):
            return list(session.get("vendor_quotations", quotations))

        requirements = session["requirements"]
        schedules = {
            item["service_type"]: item
            for item in proposal.get("service_schedule", [])
        }
        facts = {
            (item["vendor_id"], item["offering_id"]): item
            for item in session.get("vendor_recommendations", [])
        }
        service_order = {
            name: index
            for index, name in enumerate(proposal["required_services"])
        }
        ranked: list[dict[str, Any]] = []
        recommended_ids: list[str] = []
        comparisons: list[dict[str, Any]] = []
        for service_type in proposal["required_services"]:
            service_quotes = []
            for quotation in quotations:
                if quotation["service_type"] != service_type:
                    continue
                candidate = facts.get(
                    (quotation["vendor_id"], quotation["offering_id"])
                )
                if candidate is None:
                    session["quotation_comparison_complete"] = False
                    session["quotation_rankings"] = []
                    session["recommended_quotation_ids"] = []
                    return quotations
                service_quotes.append(
                    {
                        **quotation,
                        "vendor_name": candidate["vendor_name"],
                        "service_location": candidate["service_location"],
                        "guest_capacity": candidate["guest_capacity"],
                        "rating": candidate["rating"],
                        "catalogue_estimate_cents": candidate[
                            "total_price_cents"
                        ],
                        "arrival_time": quotation.get("arrival_time")
                        or schedules[service_type]["arrival_time"],
                        "service_start_time": quotation.get("service_start_time")
                        or schedules[service_type]["start_time"],
                        "service_end_time": quotation.get("service_end_time")
                        or schedules[service_type]["end_time"],
                    }
                )
            result = self._procurement.compare_received_quotations(
                {
                    "event_id": session["event_id"],
                    "proposal_id": proposal["proposal_id"],
                    "service_type": service_type,
                    "event_date": requirements["event_date"],
                    "guest_count": requirements["guest_count"],
                    "location": requirements["location"],
                    "customer_preferences": requirements.get(
                        "customer_preferences", ""
                    ),
                    "service_budget_cents": None,
                    "selection_priority": requirements.get("service_priorities", {}).get(service_type, "balanced"),
                    "quotations": service_quotes,
                }
            )
            comparisons.append(result)
            if result.get("status") != "success":
                session["quotation_comparison_complete"] = False
                session["quotation_rankings"] = comparisons
                session["recommended_quotation_ids"] = []
                return quotations
            data = result["data"]
            ranked.extend(data["quotation_ranking"])
            recommended_ids.append(data["recommended_quotation_id"])

        ranked.sort(
            key=lambda item: (
                service_order[item["service_type"]],
                item["rank"],
            )
        )
        session["quotation_rankings"] = comparisons
        session["recommended_quotation_ids"] = recommended_ids
        session["quotation_comparison_complete"] = True
        session["quotation_comparison_fingerprint"] = fingerprint
        return ranked

    def _prepare_recommended_customer_quote(self, session: dict[str, Any]) -> None:
        """Run Finance and perform one bounded reselection from stored quotes."""
        selected_ids = list(session.get("recommended_quotation_ids", []))
        if not selected_ids:
            session["stage"] = "quotation_attention"
            return
        result = self._finance.handle(
            {
                "event_id": session["event_id"],
                "action": "prepare_budget",
                "proposal": session["proposal"],
                "quotations": session["vendor_quotations"],
                "selected_quotation_ids": selected_ids,
                "budget_limit_cents": session["requirements"]["budget_limit_cents"],
            }
        )
        session["selected_quotation_ids"] = selected_ids
        session["budget"] = result.get("data", {}).get("budget")
        session["finance_feedback"] = None

        if result["status"] != "success":
            budget = result.get("data", {}).get("budget") or {}
            session["finance_feedback"] = {
                "message": result["message"],
                "over_budget_cents": budget.get("over_budget_cents"),
                "supplier_budget_limit_cents": budget.get(
                    "supplier_budget_limit_cents"
                ),
            }
            if session.get("finance_revision_attempts", 0) < 1:
                session["finance_revision_attempts"] = 1
                replacement = self._select_affordable_bundle(
                    session["vendor_quotations"],
                    session["proposal"]["required_services"],
                    budget.get("supplier_budget_limit_cents"),
                    session["requirements"].get("service_priorities", {}),
                )
                if replacement:
                    selected_ids = [item["quotation_id"] for item in replacement]
                    result = self._finance.handle(
                        {
                            "event_id": session["event_id"],
                            "action": "prepare_budget",
                            "proposal": session["proposal"],
                            "quotations": session["vendor_quotations"],
                            "selected_quotation_ids": selected_ids,
                            "budget_limit_cents": session["requirements"][
                                "budget_limit_cents"
                            ],
                        }
                    )
                    session["recommended_quotation_ids"] = selected_ids
                    session["selected_quotation_ids"] = selected_ids
                    session["budget"] = result.get("data", {}).get("budget")
                    session["finance_feedback"] = {
                        "message": "Finance supplied an exact vendor ceiling and Procurement reselected once from the existing quotes.",
                        "attempt": 1,
                        "supplier_budget_limit_cents": budget.get(
                            "supplier_budget_limit_cents"
                        ),
                    }

        if result["status"] != "success":
            groups = [
                [
                    item for item in session["vendor_quotations"]
                    if item["service_type"] == service
                ]
                for service in session["proposal"]["required_services"]
            ]
            if all(groups):
                minimum_vendor = sum(
                    min(item["quoted_total_cents"] for item in group)
                    for group in groups
                )
                minimum_total = calculate_event_costs(minimum_vendor)[
                    "customer_price_cents"
                ]
                session["finance_feedback"].update(
                    minimum_vendor_total_cents=minimum_vendor,
                    minimum_customer_total_cents=minimum_total,
                    minimum_budget_shortfall_cents=max(
                        0,
                        minimum_total
                        - session["requirements"]["budget_limit_cents"],
                    ),
                )
            session["customer_quotation"] = None
            session["stage"] = "planner_adjustment"
            return

        quotation_result = self._finance.handle(
            {
                "event_id": session["event_id"],
                "action": "generate_customer_quotation",
                "budget": result["data"]["budget"],
                "selected_quotations": result["data"]["selected_quotations"],
            }
        )
        if quotation_result["status"] != "success":
            session["stage"] = "quotation_attention"
            return
        session["customer_quotation"] = quotation_result["data"][
            "customer_quotation"
        ]
        session["stage"] = "quotation"

    @staticmethod
    def _select_affordable_bundle(
        quotations: list[dict[str, Any]],
        services: list[str],
        supplier_ceiling_cents: int | None,
        priorities: dict[str, str] | None = None,
    ) -> list[dict[str, Any]] | None:
        if type(supplier_ceiling_cents) is not int:
            return None
        groups = [
            [item for item in quotations if item.get("service_type") == service]
            for service in services
        ]
        if not all(groups):
            return None
        feasible = [
            list(choice)
            for choice in product(*groups)
            if sum(item["quoted_total_cents"] for item in choice)
            <= supplier_ceiling_cents
        ]
        if not feasible:
            return None
        priorities = priorities or {}
        return min(
            feasible,
            key=lambda choice: (
                tuple(-float(item.get("rating", 0)) if priorities[item["service_type"]] == "highest_rating"
                      else item["quoted_total_cents"]
                      for item in choice if item["service_type"] in priorities),
                sum(int(item.get("rank", 99)) for item in choice),
                sum(item["quoted_total_cents"] for item in choice),
                tuple(item["quotation_id"] for item in choice),
            ),
        )

    def _build_proposal(
        self,
        session: dict[str, Any],
        services: list[str],
        service_schedule: list[dict[str, str]],
    ) -> dict[str, Any]:
        requirements = session["requirements"]
        return {
            "event_id": session["event_id"],
            "proposal_id": "P-" + uuid4().hex[:12].upper(),
            "version": session.get("plan_version", 1),
            "summary": f"{requirements['event_type']} in {requirements['location']}",
            "required_services": list(services),
            "service_schedule": list(service_schedule),
            "status": "PendingReview",
        }

    def _find_vendors(
        self, event_id: str, requirements: dict[str, Any]
    ) -> list[dict[str, Any]]:
        results = []
        service_types = requirements.get("required_services") or ["any"]
        if not 1 <= len(service_types) <= 5:
            return []
        for service_type in service_types:
            request = {
                "event_id": event_id,
                "service_type": service_type,
                "event_date": requirements["event_date"],
                "guest_count": requirements["guest_count"],
                "location": requirements["location"],
                "customer_preferences": requirements.get(
                    "customer_preferences", ""
                ),
                "selection_priority": requirements.get("service_priorities", {}).get(service_type, "balanced"),
            }
            result = self._procurement.handle(request)
            if result.get("status") == "error" and self._supplier_portal is not None:
                result = self._procurement.deterministic_fallback(request)
            results.append(result)
        return results

    @staticmethod
    def _clear_after_requirements(session: dict[str, Any]) -> None:
        session.update(
            proposal=None,
            plan_confirmed=False,
            vendor_recommendations=[],
            vendor_quotations=[],
            automatic_quotations=[],
            supplier_replies=[],
            supplier_requests=[],
            procurement_batch_id=None,
            quotation_rankings=[],
            recommended_quotation_ids=[],
            quotation_comparison_complete=False,
            quotation_comparison_fingerprint=None,
            selected_quotation_ids=[],
            finance_revision_attempts=0,
            finance_feedback=None,
            budget=None,
            customer_quotation=None,
            approval=None,
            supplier_confirmations=[],
            declined_quotation_ids=[],
            deposit=None,
            final_payment=None,
            bookings=[],
            booking_replies=[],
            operations_plan=None,
        )

    def _require_session(self, event_id: str) -> dict[str, Any]:
        session = self._sessions.get(event_id)
        if session is None:
            raise KeyError("event not found")
        return session

    def _selection_notes(self, session: dict[str, Any]) -> list[str]:
        notes = []
        priorities = session.get("requirements", {}).get("service_priorities", {})
        selected = set(session.get("selected_quotation_ids", []))
        declined = set(session.get("declined_quotation_ids", []))
        quotes = [q for q in session.get("vendor_quotations", [])
                  if q["quotation_id"] not in declined]
        for service, priority in priorities.items():
            if priority == "highest_rating":
                notes.append(f"{service.replace('_', ' ').title()} quality is measured by catalogue rating.")
                choices = [q for q in quotes if q["service_type"] == service]
                chosen = next((q for q in choices if q["quotation_id"] in selected), None)
                if chosen and chosen.get("rating", 0) < max(q.get("rating", 0) for q in choices):
                    notes.append(
                        f"Budget trade-off: the selected {service} has a {chosen.get('rating')}/5 "
                        "rating. A higher-rated received quote was not selected for this budget. "
                        "Review this trade-off before approving."
                    )
        if (session.get("finance_feedback") or {}).get("attempt"):
            notes.append("Finance required a budget adjustment. Code selected an affordable combination using your explicit priorities, then supplier ranks and price.")
        return notes

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
            "selection_notes": self._selection_notes(session),
            "reply": reply,
            "stage": session.get("stage", "requirements"),
            "requirements": session.get("requirements", {}),
            "progress": session.get("progress", {}),
            "decision_summary": decision_summary or [],
            "proposal": session.get("proposal"),
            "plan_confirmed": session.get("plan_confirmed", False),
            "vendor_recommendations": session.get("vendor_recommendations", []),
            "vendor_quotations": session.get("vendor_quotations", []),
            "supplier_replies": session.get("supplier_replies", []),
            "supplier_requests": session.get("supplier_requests", []),
            "procurement_batch_id": session.get("procurement_batch_id"),
            "quotation_rankings": session.get("quotation_rankings", []),
            "recommended_quotation_ids": session.get(
                "recommended_quotation_ids", []
            ),
            "quotation_comparison_complete": session.get(
                "quotation_comparison_complete", False
            ),
            "selected_quotation_ids": session.get("selected_quotation_ids", []),
            "budget": session.get("budget"),
            "finance_feedback": session.get("finance_feedback"),
            "customer_quotation": session.get("customer_quotation"),
            "approval": session.get("approval"),
            "supplier_confirmations": session.get("supplier_confirmations", []),
            "deposit": session.get("deposit"),
            "final_payment": session.get("final_payment"),
            "bookings": session.get("bookings", []),
            "booking_replies": session.get("booking_replies", []),
            "operations_plan": session.get("operations_plan"),
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
