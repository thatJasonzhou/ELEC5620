from pathlib import Path

import pytest

from src.agents import EventPlannerAgent, VendorProcurementManagerAgent
from src.llm import DemoLLMClient
from src.services.event_session_service import EventSessionService
from src.services.planner_workflow_service import PlannerWorkflowService
from src.services.vendor_procurement_service import VendorProcurementService


def make_workflow() -> PlannerWorkflowService:
    llm = DemoLLMClient()
    catalog = Path(__file__).resolve().parents[2] / "data" / "vendor_catalog.json"
    return PlannerWorkflowService(
        EventPlannerAgent(llm),
        VendorProcurementManagerAgent(
            llm, VendorProcurementService.from_json_file(catalog)
        ),
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
    assert complete["stage"] == "vendor_review"
    assert complete["progress"]["completed"] == 6
    assert "Please select one vendor for each service." in complete["reply"]
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

    selected = [
        next(
            item["offering_id"]
            for item in complete["vendor_recommendations"]
            if item["service_type"] == service
        )
        for service in ("catering", "photography")
    ]
    confirmation = workflow.confirm_vendor_selection(first["event_id"], selected)
    assert confirmation["stage"] == "proposal"
    assert confirmation["selected_offering_ids"] == selected

    with pytest.raises(ValueError, match="one vendor for each service"):
        workflow.confirm_vendor_selection(
            first["event_id"],
            [selected[0]],
        )


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
    assert complete["stage"] == "vendor_review"
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
