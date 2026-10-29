from pathlib import Path

from src.agents import (
    EventPlannerAgent,
    FinancialManagerAgent,
    VendorProcurementManagerAgent,
)
from src.llm import DemoLLMClient
from src.services.event_session_service import EventSessionService
from src.services.financial_workflow_service import FinancialWorkflowService
from src.services.planner_workflow_service import PlannerWorkflowService
from src.services.supplier_portal_service import SupplierPortalService
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
            "It is on 16 December 2026 from 3 pm to 9 pm. "
            "My budget is 100000 dollars and I need catering and photography."
        ),
    )
    assert complete["stage"] == "plan_review"
    assert complete["progress"]["completed"] == 6
    assert "confirm" in complete["reply"].lower()
    assert "Event Type" not in complete["reply"]
    confirmed = workflow.confirm_plan(first["event_id"])
    assert {item["service_type"] for item in confirmed["vendor_recommendations"]} == {
        "venue",
        "catering",
        "photography",
    }
    assert [item["agent"] for item in confirmed["agent_trace"]] == [
        "procurement",
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
        for service in ("venue", "catering", "photography")
    ]
    customer_quote = workflow.confirm_quotation_selection(
        first["event_id"], selected
    )
    assert customer_quote["stage"] == "quotation"
    assert customer_quote["customer_quotation"]["estimated_total_cents"] <= 10_000_000

    payment = workflow.approve_customer_quotation(first["event_id"])
    assert payment["stage"] == "payment"
    assert payment["deposit"]["status"] == "pending"

    paid = workflow.pay_deposit(first["event_id"])
    assert paid["stage"] == "booking"
    assert paid["deposit"]["status"] == "paid"

    booked = workflow.confirm_bookings(first["event_id"])
    assert booked["stage"] == "booking_complete"
    assert len(booked["bookings"]) == 3


def test_complete_requirements_can_return_no_vendor_match() -> None:
    workflow = make_workflow()
    response = workflow.handle_message(
        event_id=None,
        message=(
            "I need a wedding in Sydney on 18 December 2026 from 3 pm to 9 pm "
            "for 80 guests, budget 30000 dollars and catering."
        ),
    )
    assert response["progress"]["completed"] == 6
    assert response["stage"] == "plan_review"
    checked = workflow.confirm_plan(response["event_id"])
    assert checked["vendor_recommendations"] == []
    assert "no suitable supplier" in checked["reply"]


def test_smaller_event_uses_vendor_max_capacity_for_quotations() -> None:
    workflow = make_workflow()
    response = workflow.handle_message(
        event_id=None,
        message=(
            "I need a birthday party in Sydney on 16 December 2026 from 3 pm "
            "to 8 pm for 50 guests, budget 100000 dollars, with catering and "
            "photography."
        ),
    )

    assert response["stage"] == "plan_review"
    workflow.confirm_plan(response["event_id"])
    quotations = workflow.request_vendor_quotations(response["event_id"])
    assert quotations["stage"] == "quotation_review"
    assert {
        (item["service_type"], item["guest_count"])
        for item in quotations["vendor_quotations"]
    } == {("venue", 50), ("catering", 50), ("photography", 50)}

    selected = [
        next(
            item["quotation_id"]
            for item in quotations["vendor_quotations"]
            if item["service_type"] == service
        )
        for service in ("venue", "catering", "photography")
    ]
    customer_quote = workflow.confirm_quotation_selection(response["event_id"], selected)
    assert customer_quote["stage"] == "quotation"
    assert workflow.approve_customer_quotation(response["event_id"])["stage"] == "payment"
    assert workflow.pay_deposit(response["event_id"])["stage"] == "booking"
    booked = workflow.confirm_bookings(response["event_id"])
    assert booked["stage"] == "booking_complete"
    assert {(item["service_type"], item["guest_count"]) for item in booked["bookings"]} == {
        ("venue", 50),
        ("catering", 50),
        ("photography", 50),
    }


def test_no_extra_services_still_runs_global_vendor_matching() -> None:
    workflow = make_workflow()
    first = workflow.handle_message(
        event_id=None,
        message=(
            "I need a birthday in Sydney on 16 December 2026 from 3 pm to 6 pm "
            "for 30 guests with a budget of 30000 dollars."
        ),
    )
    assert first["stage"] == "requirements"
    assert first["progress"]["completed"] == 5
    assert first["progress"]["missing_fields"] == ["services"]
    assert "vendor_budget_cents" not in first["requirements"]

    complete = workflow.handle_message(
        event_id=first["event_id"],
        message="I do not need any additional services.",
    )
    assert complete["stage"] == "plan_review"
    assert complete["progress"]["completed"] == 6
    assert complete["requirements"]["required_services"] == ["venue"]
    assert complete["requirements"]["services_confirmed"] is True
    assert complete["vendor_recommendations"] == []
    confirmed = workflow.confirm_plan(first["event_id"])
    assert {item["service_type"] for item in confirmed["vendor_recommendations"]} == {
        "venue"
    }


def test_customer_waits_for_interactive_supplier_quotes(tmp_path: Path) -> None:
    llm = DemoLLMClient()
    data = Path(__file__).resolve().parents[2] / "data"
    vendor_service = VendorProcurementService.from_json_file(
        data / "vendor_catalog.json"
    )
    portal = SupplierPortalService(tmp_path / "supplier.sqlite3", vendor_service)
    procurement = VendorProcurementManagerAgent(
        llm,
        vendor_service,
        MockVendorQuotationService.from_json_file(
            data / "mock_vendor_quotations.json"
        ),
        VendorBookingService(
            MockVendorBookingService.from_json_file(
                data / "mock_vendor_bookings.json"
            )
        ),
    )
    workflow = PlannerWorkflowService(
        EventPlannerAgent(llm),
        procurement,
        FinancialManagerAgent(llm, FinancialWorkflowService()),
        EventSessionService(),
        supplier_portal=portal,
        llm_mode="mock",
    )
    proposal = workflow.handle_message(
        event_id=None,
        message=(
            "I need a birthday party in Sydney on 16 December 2026 from 3 pm "
            "to 8 pm for 50 guests, budget 100000 dollars, with catering and "
            "photography."
        ),
    )

    workflow.confirm_plan(proposal["event_id"])
    waiting = workflow.request_vendor_quotations(proposal["event_id"])
    assert waiting["stage"] == "awaiting_vendor_quotes"
    assert waiting["vendor_quotations"] == []
    assert len(waiting["supplier_requests"]) == 3
    assert {item["service_type"] for item in waiting["supplier_requests"]} == {
        "venue"
    }

    for request in waiting["supplier_requests"]:
        portal.respond_to_quote_request(
            request["request_id"],
            available=True,
            quoted_total_cents=request["catalogue_estimate_cents"],
        )

    refreshed = workflow.get_event(proposal["event_id"])
    assert refreshed["stage"] == "quotation"
    assert refreshed["quotation_comparison_complete"] is True
    assert len(refreshed["recommended_quotation_ids"]) == 3
    assert {
        item["service_type"] for item in refreshed["vendor_quotations"]
        if item["recommended"]
    } == {"venue", "catering", "photography"}
    assert all(
        item["scenario_id"].startswith(("RFQ-", "MOCK-"))
        for item in refreshed["vendor_quotations"]
    )


def test_expanded_services_complete_the_interactive_booking_flow(
    tmp_path: Path,
) -> None:
    llm = DemoLLMClient()
    data = Path(__file__).resolve().parents[2] / "data"
    vendor_service = VendorProcurementService.from_json_file(
        data / "vendor_catalog.json"
    )
    portal = SupplierPortalService(tmp_path / "expanded.sqlite3", vendor_service)
    workflow = PlannerWorkflowService(
        EventPlannerAgent(llm),
        VendorProcurementManagerAgent(
            llm,
            vendor_service,
            MockVendorQuotationService.from_json_file(
                data / "mock_vendor_quotations.json"
            ),
            VendorBookingService(
                MockVendorBookingService.from_json_file(
                    data / "mock_vendor_bookings.json"
                )
            ),
        ),
        FinancialManagerAgent(llm, FinancialWorkflowService()),
        EventSessionService(),
        supplier_portal=portal,
        llm_mode="mock",
    )
    proposal = workflow.handle_message(
        event_id=None,
        message=(
            "I need a conference in Sydney on 16 December 2026 from 9 am "
            "to 5 pm for 50 guests, budget 100000 dollars, with a venue, "
            "lighting and event staff."
        ),
    )

    assert proposal["stage"] == "plan_review"
    assert proposal["requirements"]["required_services"] == [
        "venue", "lighting", "event_staff"
    ]
    workflow.confirm_plan(proposal["event_id"])
    waiting = workflow.request_vendor_quotations(proposal["event_id"])
    assert waiting["stage"] == "awaiting_vendor_quotes"
    assert len(waiting["supplier_requests"]) == 3
    assert {
        item["service_type"] for item in waiting["supplier_requests"]
    } == {"venue"}

    for request in waiting["supplier_requests"]:
        portal.respond_to_quote_request(
            request["request_id"],
            available=True,
            quoted_total_cents=request["catalogue_estimate_cents"],
        )

    compared = workflow.get_event(proposal["event_id"])
    assert compared["stage"] == "quotation"
    assert compared["quotation_comparison_complete"] is True
    assert len(compared["recommended_quotation_ids"]) == 3
    approved = workflow.approve_customer_quotation(proposal["event_id"])
    assert approved["stage"] == "awaiting_supplier_confirmation"
    manual = [
        item
        for item in approved["supplier_confirmations"]
        if item.get("response_mode") != "automatic_mock"
    ]
    assert len(manual) == 1
    portal.respond_to_confirmation(manual[0]["confirmation_id"], confirmed=True)
    assert workflow.get_event(proposal["event_id"])["stage"] == "payment"
    assert workflow.pay_deposit(proposal["event_id"])["stage"] == "booking"
    booked = workflow.confirm_bookings(proposal["event_id"])
    assert booked["stage"] == "booking_complete"
    assert {item["service_type"] for item in booked["bookings"]} == {
        "venue", "lighting", "event_staff"
    }
