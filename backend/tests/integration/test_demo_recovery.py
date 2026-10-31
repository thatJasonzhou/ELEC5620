"""Replay alternative supplier outcomes on the same event, with real local storage."""
from pathlib import Path

import pytest

from src.api.app import build_workflow


@pytest.fixture
def workflow(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLANNER_LLM_MODE", "mock")
    monkeypatch.setenv("ELEC5620_DB_PATH", str(tmp_path / "procurement.sqlite3"))
    monkeypatch.setenv("SUPPLIER_PORTAL_DB_PATH", str(tmp_path / "suppliers.sqlite3"))
    return build_workflow()


def plan(workflow):
    return workflow.handle_message(
        event_id=None,
        message=("I need a conference in Sydney on 16 December 2026 from 9 am to 5 pm "
                 "for 50 guests, budget 100000 dollars, with lighting and event staff."),
    )


def quoted(workflow):
    event = plan(workflow)
    identity = event["event_id"]
    workflow.confirm_plan(identity)
    waiting = workflow.request_vendor_quotations(identity)
    for request in waiting["supplier_requests"]:
        workflow.supplier_portal.respond_to_quote_request(
            request["request_id"], available=True,
            quoted_total_cents=request["catalogue_estimate_cents"],
        )
    return workflow.get_event(identity)


def book(workflow, event):
    identity = event["event_id"]
    approved = workflow.approve_customer_quotation(identity)
    for item in approved["supplier_confirmations"]:
        if item.get("response_mode") != "automatic_mock":
            workflow.supplier_portal.respond_to_confirmation(item["confirmation_id"], confirmed=True)
    assert workflow.get_event(identity)["stage"] == "payment"
    workflow.pay_deposit(identity)
    return workflow.confirm_bookings(identity)


def test_repeated_undo_never_jumps_forward_and_can_replay(workflow):
    event = plan(workflow)
    identity = event["event_id"]
    workflow.capture_demo_checkpoint(identity)
    workflow.confirm_plan(identity)
    workflow.capture_demo_checkpoint(identity)
    workflow.request_vendor_quotations(identity)

    assert workflow.restore_previous_demo_checkpoint(identity)["stage"] == "proposal"
    assert workflow.supplier_portal.list_quote_requests(event_id=identity) == []
    restored = workflow.restore_previous_demo_checkpoint(identity)
    assert restored["stage"] == "plan_review"
    assert restored["conversation_history"]
    with pytest.raises(ValueError, match="earliest checkpoint"):
        workflow.restore_previous_demo_checkpoint(identity)

    workflow.capture_demo_checkpoint(identity)
    workflow.confirm_plan(identity)
    workflow.capture_demo_checkpoint(identity)
    replay = workflow.request_vendor_quotations(identity)
    assert replay["event_id"] == identity
    assert len(replay["supplier_requests"]) == 3


def test_booking_rewind_restores_database_cache_and_keeps_other_events(workflow):
    event = quoted(workflow)
    identity = event["event_id"]
    # An unrelated event must survive the reset of the demonstration event.
    other = book(workflow, quoted(workflow))
    other_id = other["event_id"]
    checkpoint = workflow.capture_demo_checkpoint(identity)
    booked = book(workflow, event)
    booking_service = workflow._procurement._booking_service
    records = workflow._procurement._record_service
    assert len(records.get_bookings(identity, event["proposal"]["proposal_id"])) == 3

    restored = workflow.restore_demo_checkpoint(identity, checkpoint["checkpoint_id"])
    assert restored["stage"] == "quotation"
    assert restored["bookings"] == [] and restored["deposit"] is None
    assert workflow._operations.snapshot_event(identity) is None
    assert records.get_bookings(identity, event["proposal"]["proposal_id"]) == []
    assert not any(b["event_id"] == identity for b in booking_service.bookings)
    assert any(b["event_id"] == other_id for b in booking_service.bookings)
    assert workflow.supplier_portal.list_confirmation_requests(event_id=identity) == []

    replay = book(workflow, restored)
    assert replay["stage"] == "operations" and replay["event_id"] == identity
    workflow.reset_demo_event(identity)
    assert not any(b["event_id"] == identity for b in booking_service.bookings)
    assert not records.snapshot_event(identity)["quotations"]
    assert workflow._operations.snapshot_event(identity) is None
    assert workflow.supplier_portal.list_quote_requests(event_id=identity) == []
    assert any(b["event_id"] == other_id for b in records.all_bookings())
    assert workflow._operations.snapshot_event(other_id) is not None


def test_restore_before_supplier_acceptance_can_demo_rejection(workflow):
    event = quoted(workflow)
    identity = event["event_id"]
    approved = workflow.approve_customer_quotation(identity)
    confirmation = next(c for c in approved["supplier_confirmations"]
                        if c.get("response_mode") != "automatic_mock")
    checkpoint = workflow.capture_demo_checkpoint(identity)
    workflow.supplier_portal.respond_to_confirmation(confirmation["confirmation_id"], confirmed=True)
    assert workflow.get_event(identity)["stage"] == "payment"

    workflow.restore_demo_checkpoint(identity, checkpoint["checkpoint_id"])
    assert workflow.get_event(identity)["stage"] == "awaiting_supplier_confirmation"
    workflow.supplier_portal.respond_to_confirmation(confirmation["confirmation_id"], confirmed=False)
    replacement = workflow.get_event(identity)
    assert replacement["event_id"] == identity
    assert replacement["stage"] == "quotation"
    assert replacement["approval"] is None
    assert replacement["selected_quotation_ids"] != event["selected_quotation_ids"]


def test_delay_acceptance_can_be_undone_and_replayed(workflow):
    event = book(workflow, quoted(workflow))
    identity = event["event_id"]
    task = next(t for t in event["operations_plan"]["tasks"] if t["service_type"] == "venue")
    before_delay = workflow.capture_demo_checkpoint(identity)
    delayed = workflow.perform_operations_action(identity, "report_delay", {
        "task_id": task["task_id"], "expected_arrival_time": "09:30", "reason": "Traffic",
    })
    issue = delayed["operations_plan"]["issues"][0]
    workflow.capture_demo_checkpoint(identity)
    workflow.perform_operations_action(identity, "accept_delay_adjustment", {"issue_id": issue["issue_id"]})

    restored = workflow.restore_previous_demo_checkpoint(identity)
    assert restored["operations_plan"]["issues"][0]["adjustment"]["status"] == "PROPOSED"
    with pytest.raises(ValueError, match="customer to accept"):
        workflow.perform_operations_action(identity, "record_arrival", {"task_id": task["task_id"]})

    restored = workflow.restore_demo_checkpoint(identity, before_delay["checkpoint_id"])
    assert restored["operations_plan"]["issues"] == []
    replay = workflow.perform_operations_action(identity, "report_delay", {
        "task_id": task["task_id"], "expected_arrival_time": "09:45", "reason": "New delay scenario",
    })
    assert replay["operations_plan"]["issues"][0]["adjustment"]["expected_arrival_time"] == "09:45"


def test_event_completion_and_final_payment_can_be_replayed(workflow):
    event = book(workflow, quoted(workflow))
    identity = event["event_id"]
    task = next(t for t in event["operations_plan"]["tasks"] if t["service_type"] == "venue")
    for action in ("record_arrival", "start_service", "complete_service"):
        workflow.perform_operations_action(identity, action, {"task_id": task["task_id"]})
    checkpoint = workflow.capture_demo_checkpoint(identity)
    workflow.perform_operations_action(identity, "confirm_event_completion", {"confirm": True})
    assert workflow.pay_final_payment(identity)["stage"] == "completed"

    restored = workflow.restore_demo_checkpoint(identity, checkpoint["checkpoint_id"])
    assert restored["event_id"] == identity
    assert restored["stage"] == "operations"
    assert restored["final_payment"] is None
    assert restored["operations_plan"]["customer_completion_confirmation"] is None
    assert restored["operations_plan"]["finalized"] is False
    with pytest.raises(ValueError, match="Operations must be finalized"):
        workflow.pay_final_payment(identity)
    workflow.perform_operations_action(identity, "confirm_event_completion", {"confirm": True})
    assert workflow.pay_final_payment(identity)["stage"] == "completed"
