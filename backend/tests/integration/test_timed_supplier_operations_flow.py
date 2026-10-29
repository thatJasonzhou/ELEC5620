from pathlib import Path

import pytest

from src.agents import (
    EventOperationsAgent,
    EventPlannerAgent,
    FinancialManagerAgent,
    VendorProcurementManagerAgent,
)
from src.llm import DemoLLMClient
from src.services.event_operations_service import EventOperationsService
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


DATA = Path(__file__).resolve().parents[2] / "data"


def make_workflow(tmp_path: Path) -> tuple[PlannerWorkflowService, SupplierPortalService]:
    llm = DemoLLMClient()
    catalogue = VendorProcurementService.from_json_file(DATA / "vendor_catalog.json")
    portal = SupplierPortalService(tmp_path / "supplier.sqlite3", catalogue)
    procurement = VendorProcurementManagerAgent(
        llm,
        catalogue,
        MockVendorQuotationService.from_json_file(DATA / "mock_vendor_quotations.json"),
        VendorBookingService(
            MockVendorBookingService.from_json_file(DATA / "mock_vendor_bookings.json")
        ),
    )
    workflow = PlannerWorkflowService(
        EventPlannerAgent(llm),
        procurement,
        FinancialManagerAgent(llm, FinancialWorkflowService()),
        EventSessionService(),
        operations=EventOperationsAgent(llm, EventOperationsService()),
        supplier_portal=portal,
        llm_mode="mock",
    )
    return workflow, portal


def test_timed_plan_manual_venue_and_operations_flow(tmp_path: Path) -> None:
    workflow, portal = make_workflow(tmp_path)
    planned = workflow.handle_message(
        event_id=None,
        message=(
            "I need a conference in Sydney on 16 December 2026 from 9 am "
            "to 5 pm for 50 guests, budget 100000 dollars, with lighting "
            "and event staff."
        ),
    )

    assert planned["stage"] == "plan_review"
    assert planned["proposal"]["status"] == "PendingReview"
    assert planned["proposal"]["required_services"] == [
        "venue",
        "lighting",
        "event_staff",
    ]
    assert len(planned["proposal"]["service_schedule"]) == 3

    revised = workflow.handle_message(
        event_id=planned["event_id"], message="Please have lighting arrive at 10 am."
    )
    lighting = next(
        item
        for item in revised["proposal"]["service_schedule"]
        if item["service_type"] == "lighting"
    )
    assert lighting["arrival_time"] == "10:00"
    assert revised["proposal"]["version"] == 2

    confirmed = workflow.confirm_plan(planned["event_id"])
    assert confirmed["stage"] == "proposal"
    assert confirmed["proposal"]["status"] == "Approved"

    waiting = workflow.request_vendor_quotations(planned["event_id"])
    assert waiting["stage"] == "awaiting_vendor_quotes"
    assert len(waiting["supplier_requests"]) == 3
    assert {item["service_type"] for item in waiting["supplier_requests"]} == {
        "venue"
    }
    assert all(
        item.get("response_mode") == "automatic_mock"
        for item in waiting["supplier_replies"]
    )

    for request in waiting["supplier_requests"]:
        portal.respond_to_quote_request(
            request["request_id"],
            available=True,
            quoted_total_cents=request["catalogue_estimate_cents"],
        )

    quoted = workflow.get_event(planned["event_id"])
    assert quoted["stage"] == "quotation"
    assert len(quoted["recommended_quotation_ids"]) == 3
    assert quoted["customer_quotation"]["estimated_total_cents"] <= 10_000_000

    confirmation = workflow.approve_customer_quotation(planned["event_id"])
    assert confirmation["stage"] == "awaiting_supplier_confirmation"
    manual = [
        item
        for item in confirmation["supplier_confirmations"]
        if item.get("response_mode") != "automatic_mock"
    ]
    assert len(manual) == 1
    portal.respond_to_confirmation(manual[0]["confirmation_id"], confirmed=False)
    replacement = workflow.get_event(planned["event_id"])
    assert replacement["stage"] == "quotation"
    assert replacement["customer_quotation"]["customer_quotation_id"] != quoted[
        "customer_quotation"
    ]["customer_quotation_id"]

    confirmation = workflow.approve_customer_quotation(planned["event_id"])
    manual = [
        item
        for item in confirmation["supplier_confirmations"]
        if item.get("response_mode") != "automatic_mock"
    ]
    assert len(manual) == 1
    portal.respond_to_confirmation(manual[0]["confirmation_id"], confirmed=True)

    payment = workflow.get_event(planned["event_id"])
    assert payment["stage"] == "payment"
    assert payment["deposit"]["status"] == "pending"
    assert workflow.pay_deposit(planned["event_id"])["stage"] == "booking"

    completed = workflow.confirm_bookings(planned["event_id"])
    assert completed["stage"] == "operations"
    assert completed["operations_plan"]["status"] == "READY"
    assert len(completed["operations_plan"]["tasks"]) == 3

    with pytest.raises(ValueError, match="Operations must be finalized"):
        workflow.pay_final_payment(planned["event_id"])

    venue_task = next(
        item
        for item in completed["operations_plan"]["tasks"]
        if item["service_type"] == "venue"
    )
    workflow.perform_operations_action(
        planned["event_id"], "record_arrival", {"task_id": venue_task["task_id"]}
    )
    workflow.perform_operations_action(
        planned["event_id"], "start_service", {"task_id": venue_task["task_id"]}
    )
    workflow.perform_operations_action(
        planned["event_id"], "complete_service", {"task_id": venue_task["task_id"]}
    )
    balance = workflow.perform_operations_action(
        planned["event_id"], "finalize_execution", {"confirm": True}
    )
    assert balance["stage"] == "final_payment"
    assert balance["operations_plan"]["finalized"] is True
    assert balance["final_payment"]["status"] == "pending"
    assert balance["final_payment"]["amount_cents"] == (
        balance["customer_quotation"]["estimated_total_cents"]
        - balance["deposit"]["amount_cents"]
    )

    closed = workflow.pay_final_payment(planned["event_id"])
    assert closed["stage"] == "completed"
    assert closed["final_payment"]["status"] == "paid"
    assert closed["final_payment"]["transaction_reference"].startswith("MOCK-FP-")


def test_finance_ceiling_triggers_one_procurement_reselection(tmp_path: Path) -> None:
    workflow, portal = make_workflow(tmp_path)
    planned = workflow.handle_message(
        event_id=None,
        message=(
            "I need a conference in Sydney on 16 December 2026 from 9 am "
            "to 5 pm for 50 guests, budget 7500 dollars, with lighting "
            "and event staff."
        ),
    )
    workflow.confirm_plan(planned["event_id"])
    waiting = workflow.request_vendor_quotations(planned["event_id"])
    for request in waiting["supplier_requests"]:
        portal.respond_to_quote_request(
            request["request_id"],
            available=True,
            quoted_total_cents=request["catalogue_estimate_cents"],
        )

    quoted = workflow.get_event(planned["event_id"])
    assert quoted["stage"] == "quotation"
    assert quoted["budget"]["within_budget"] is True
    assert quoted["budget"]["estimated_total_cents"] <= 750_000
    assert quoted["finance_feedback"]["attempt"] == 1
    assert quoted["finance_feedback"]["supplier_budget_limit_cents"] == 625_000


def test_budget_increase_reuses_existing_supplier_quotes(tmp_path: Path) -> None:
    workflow, portal = make_workflow(tmp_path)
    planned = workflow.handle_message(
        event_id=None,
        message=(
            "I need a conference in Sydney on 16 December 2026 from 9 am "
            "to 5 pm for 50 guests, budget 1000 dollars, with photography."
        ),
    )
    workflow.confirm_plan(planned["event_id"])
    waiting = workflow.request_vendor_quotations(planned["event_id"])
    request_ids = [item["request_id"] for item in waiting["supplier_requests"]]
    for request_item in waiting["supplier_requests"]:
        portal.respond_to_quote_request(
            request_item["request_id"],
            available=True,
            quoted_total_cents=request_item["catalogue_estimate_cents"],
        )

    over_budget = workflow.get_event(planned["event_id"])
    assert over_budget["stage"] == "planner_adjustment"
    quotation_ids = [
        item["quotation_id"] for item in over_budget["vendor_quotations"]
    ]

    revised = workflow.handle_message(
        event_id=planned["event_id"],
        message="Increase my total budget to 100000 AUD.",
    )

    assert revised["stage"] == "quotation"
    assert revised["requirements"]["budget_limit_cents"] == 10_000_000
    assert [item["quotation_id"] for item in revised["vendor_quotations"]] == quotation_ids
    assert [
        item["request_id"]
        for item in portal.list_quote_requests(event_id=planned["event_id"])
    ] == request_ids
    assert "no supplier was asked to quote again" in revised["reply"]


def test_relative_budget_increase_keeps_pending_supplier_requests(tmp_path: Path) -> None:
    workflow, portal = make_workflow(tmp_path)
    planned = workflow.handle_message(
        event_id=None,
        message=(
            "I need a conference in Sydney on 16 December 2026 from 9 am "
            "to 5 pm for 50 guests, budget 1000 dollars, with photography."
        ),
    )
    workflow.confirm_plan(planned["event_id"])
    waiting = workflow.request_vendor_quotations(planned["event_id"])
    request_ids = [item["request_id"] for item in waiting["supplier_requests"]]

    revised = workflow.handle_message(
        event_id=planned["event_id"], message="增加7072成本"
    )

    assert revised["stage"] == "awaiting_vendor_quotes"
    assert revised["requirements"]["budget_limit_cents"] == 807_200
    assert [item["request_id"] for item in revised["supplier_requests"]] == request_ids
    assert [
        item["request_id"]
        for item in portal.list_quote_requests(event_id=planned["event_id"])
    ] == request_ids
