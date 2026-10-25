from pathlib import Path

import pytest

from src.agents import (
    EventPlannerAgent,
    FinancialManagerAgent,
    VendorProcurementManagerAgent,
)
from src.llm import DemoLLMClient
from src.services.event_session_service import EventSessionService
from src.services.financial_workflow_service import FinancialWorkflowService
from src.services.planner_workflow_service import PlannerWorkflowService
from src.services.vendor_booking_service import (
    MockVendorBookingService,
    VendorBookingService,
)
from src.services.vendor_procurement_service import VendorProcurementService
from src.services.vendor_quotation_service import MockVendorQuotationService


def make_workflow() -> PlannerWorkflowService:
    llm = DemoLLMClient()
    data = Path(__file__).resolve().parents[2] / "data"
    procurement = VendorProcurementManagerAgent(
        llm,
        VendorProcurementService.from_json_file(data / "vendor_catalog.json"),
        MockVendorQuotationService.from_json_file(
            data / "mock_vendor_quotations.json"
        ),
        VendorBookingService(
            MockVendorBookingService.from_json_file(
                data / "mock_vendor_bookings.json"
            )
        ),
    )
    return PlannerWorkflowService(
        EventPlannerAgent(llm),
        procurement,
        FinancialManagerAgent(llm, FinancialWorkflowService()),
        EventSessionService(),
        llm_mode="mock",
    )


def test_multiturn_planner_to_vendor_flow() -> None:
    workflow = make_workflow()
    first = workflow.handle_message(
        event_id=None,
        message="I need a wedding in Sydney for 80 guests.",
    )
    assert first["stage"] == "requirements"
    assert first["progress"]["completed"] == 3

    complete = workflow.handle_message(
        event_id=first["event_id"],
        message=(
            "It is on 5 December 2026 from 3 pm to 9 pm. "
            "My budget is 30000 dollars and I need catering and photography."
        ),
    )
    assert complete["stage"] == "proposal"
    assert complete["progress"]["completed"] == 6
    assert "request confirmed mock quotations" in complete["reply"]
    assert "Event Type" not in complete["reply"]
    assert {item["service_type"] for item in complete["vendor_recommendations"]} == {
        "catering",
        "photography",
    }
    assert [item["agent"] for item in complete["agent_trace"]] == [
        "planning",
        "procurement",
        "procurement",
    ]

    quotations = workflow.request_vendor_quotations(first["event_id"])
    assert quotations["stage"] == "quotation_review"
    selected = [
        next(
            item["quotation_id"]
            for item in quotations["vendor_quotations"]
            if item["service_type"] == service
        )
        for service in ("catering", "photography")
    ]
    customer_quote = workflow.confirm_quotation_selection(
        first["event_id"], selected
    )
    assert customer_quote["stage"] == "quotation"
    assert customer_quote["customer_quotation"]["estimated_total_cents"] == 2_796_000

    payment = workflow.approve_customer_quotation(first["event_id"])
    assert payment["stage"] == "payment"
    assert payment["deposit"]["status"] == "pending"

    paid = workflow.pay_deposit(first["event_id"])
    assert paid["stage"] == "booking"
    assert paid["deposit"]["status"] == "paid"

    booked = workflow.confirm_bookings(first["event_id"])
    assert booked["stage"] == "booking_complete"
    assert len(booked["bookings"]) == 2


def test_complete_requirements_can_return_no_vendor_match() -> None:
    workflow = make_workflow()
    response = workflow.handle_message(
        event_id=None,
        message=(
            "I need a wedding in Sydney on 8 December 2026 from 3 pm to 9 pm "
            "for 80 guests, budget 30000 dollars and catering."
        ),
    )
    assert response["progress"]["completed"] == 6
    assert response["vendor_recommendations"] == []
    assert "could not find" in response["reply"]


def test_smaller_event_uses_vendor_max_capacity_for_quotations() -> None:
    workflow = make_workflow()
    response = workflow.handle_message(
        event_id=None,
        message=(
            "I need a birthday party in Sydney on 5 December 2026 from 3 pm "
            "to 8 pm for 50 guests, budget 30000 dollars, with catering and "
            "photography."
        ),
    )

    assert response["stage"] == "proposal"
    quotations = workflow.request_vendor_quotations(response["event_id"])
    assert quotations["stage"] == "quotation_review"
    assert {
        (item["service_type"], item["guest_count"])
        for item in quotations["vendor_quotations"]
    } == {("catering", 50), ("photography", 50)}

    selected = [item["quotation_id"] for item in quotations["vendor_quotations"]]
    customer_quote = workflow.confirm_quotation_selection(response["event_id"], selected)
    assert customer_quote["stage"] == "quotation"
    assert workflow.approve_customer_quotation(response["event_id"])["stage"] == "payment"
    assert workflow.pay_deposit(response["event_id"])["stage"] == "booking"
    booked = workflow.confirm_bookings(response["event_id"])
    assert booked["stage"] == "booking_complete"
    assert {(item["service_type"], item["guest_count"]) for item in booked["bookings"]} == {
        ("catering", 50),
        ("photography", 50),
    }


def test_no_extra_services_still_runs_global_vendor_matching() -> None:
    workflow = make_workflow()
    first = workflow.handle_message(
        event_id=None,
        message=(
            "I need a birthday in Sydney on 5 December 2026 from 3 pm to 6 pm "
            "for 30 guests with a budget of 30000 dollars."
        ),
    )
    assert first["stage"] == "requirements"
    assert first["progress"]["completed"] == 5
    assert first["progress"]["missing_fields"] == ["services"]
    assert first["requirements"]["vendor_budget_cents"] == 2_100_000

    complete = workflow.handle_message(
        event_id=first["event_id"],
        message="I do not need any additional services.",
    )
    assert complete["stage"] == "proposal"
    assert complete["progress"]["completed"] == 6
    assert complete["requirements"]["required_services"] == []
    assert complete["requirements"]["services_confirmed"] is True
    assert {item["service_type"] for item in complete["vendor_recommendations"]} == {
        "catering",
        "photography",
    }
    assert [item["agent"] for item in complete["agent_trace"]] == [
        "planning",
        "procurement",
    ]
