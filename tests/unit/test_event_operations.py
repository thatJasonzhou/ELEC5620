from copy import deepcopy
import pytest

from examples.operations_example import build_demo_request
from src.agents.base import AIAgent
from src.agents.event_operations import EventOperationsAgent
from src.llm import MockLLMClient
from src.services.event_operations_service import InMemoryEventOperationsService


@pytest.fixture
def request_data():
    return build_demo_request()


@pytest.fixture
def worker():
    llm = MockLLMClient()
    llm.set_exception(AssertionError("No LLM in deterministic MVP"))
    return EventOperationsAgent(llm, InMemoryEventOperationsService())


def test_creation_and_envelope(worker, request_data):
    original = deepcopy(request_data)
    result = worker.handle(request_data)
    assert isinstance(worker, AIAgent)
    assert result["status"] == "success"
    assert result["agent"] == "operations" and result["timestamp"]
    tasks = result["data"]["execution_plan"]["tasks"]
    assert [t["title"] for t in tasks] == [x["title"] for x in request_data["proposal"]["timeline"]]
    assert all(t["booking_id"] is None and t["status"] == "NOT_STARTED" for t in tasks)
    assert request_data == original and not worker.llm.calls
    tasks.clear()
    assert len(worker.handle(request_data)["data"]["execution_plan"]["tasks"]) == 2


@pytest.mark.parametrize("path,value,expected", [
    (("proposal", "status"), "Draft", "blocked"),
    (("proposal", "event_id"), "OTHER", "blocked"),
    (("proposal", "timeline"), [], "needs_input"),
    (("proposal", "required_services"), ["photography"], "blocked"),
    (("procurement_result", "status"), "blocked", "blocked"),
    (("procurement_result", "agent"), "finance", "blocked"),
    (("procurement_result", "data", "requires_attention"), True, "blocked"),
    (("procurement_result", "data", "bookings"), [], "blocked"),
    (("procurement_result", "data", "customer_payment", "status"), "pending", "blocked"),
    (("procurement_result", "data", "customer_payment", "amount_cents"), True, "needs_input"),
    (("proposal", "timeline", 0, "start_at"), "2026-12-05T18:00:00", "needs_input"),
    (("proposal", "timeline", 0, "end_at"), "2026-12-05T17:00:00+11:00", "needs_input"),
    (("procurement_result", "data", "bookings", 0, "status"), "Cancelled", "blocked"),
    (("procurement_result", "data", "bookings", 0, "proposal_id"), "OTHER", "blocked"),
    (("procurement_result", "data", "bookings", 0, "event_date"), "2026-12-06", "blocked"),
])
def test_handoff_gates(worker, request_data, path, value, expected):
    cursor = request_data
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    assert worker.handle(request_data)["status"] == expected
    assert not worker.llm.calls and not worker.service._records


def test_duplicates_and_bad_request(worker, request_data):
    bookings = request_data["procurement_result"]["data"]["bookings"]
    bookings.append(deepcopy(bookings[0]))
    assert worker.handle(request_data)["status"] == "needs_input"
    assert worker.handle(None)["status"] == "error"
    assert worker.handle({})["status"] == "needs_input"


def test_transitions_assignment_and_repeat(worker, request_data):
    result = worker.handle(request_data)
    tasks = result["data"]["execution_plan"]["tasks"]
    booking = result["data"]["bookings"][0]["booking_id"]
    base = dict(event_id="EV001", proposal_id="P1", task_id=tasks[1]["task_id"])
    assert worker.handle({**base, "action": "assign_task", "booking_id": booking})["status"] == "success"
    update = {**base, "action": "update_task_status"}
    assert worker.handle({**update, "status": "COMPLETED"})["status"] == "needs_input"
    assert worker.handle({**update, "status": "DELAYED"})["status"] == "needs_input"
    for status in ("DELAYED", "IN_PROGRESS", "COMPLETED"):
        assert worker.handle({**update, "status": status, "reason": "Vendor late"})["status"] == "success"
    repeated = worker.handle(request_data)
    assert repeated["data"]["execution_plan"]["tasks"][1]["status"] == "COMPLETED"
    assert repeated["data"]["execution_plan"]["execution_plan_id"] == result["data"]["execution_plan"]["execution_plan_id"]
    assert worker.handle({**update, "status": "IN_PROGRESS"})["status"] == "needs_input"
    assert worker.handle({**base, "action": "assign_task", "booking_id": None})["status"] == "blocked"
    request_data["proposal"]["summary"] = "Revised"
    assert worker.handle(request_data)["status"] == "blocked"


def test_task_addition_conflicts_and_isolation(worker, request_data):
    data = worker.handle(request_data)["data"]
    booking = data["bookings"][0]["booking_id"]
    base = dict(event_id="EV001", proposal_id="P1")
    add = {**base, "action": "add_task", "title": "Supplier arrival", "booking_id": booking,
           "start_at": "2026-12-05T16:00:00+11:00", "end_at": "2026-12-05T16:30:00+11:00"}
    assert worker.handle(add)["status"] == "success"
    assert worker.handle(add)["status"] == "blocked"
    assert worker.handle({**add, "booking_id": "unknown"})["status"] == "needs_input"
    assert worker.handle({**add, "event_id": "OTHER"})["status"] == "blocked"
    assert worker.handle({**add, "proposal_id": "P2"})["status"] == "blocked"
    assert worker.handle({**base, "action": "update_task_status", "task_id": "unknown", "status": "IN_PROGRESS"})["status"] == "needs_input"
    assert len(worker.handle({**base, "action": "monitor_execution"})["data"]["execution_plan"]["tasks"]) == 3


def test_complete_requires_vendor_coverage(worker, request_data):
    result = worker.handle(request_data)
    for task in result["data"]["execution_plan"]["tasks"]:
        for status in ("IN_PROGRESS", "COMPLETED"):
            result = worker.handle(dict(event_id="EV001", proposal_id="P1", action="update_task_status",
                                        task_id=task["task_id"], status=status))
    summary = result["data"]["summary"]
    assert summary["all_tasks_completed"] and not summary["execution_complete"]


def test_same_booking_cannot_overlap(worker, request_data):
    request_data["proposal"]["timeline"][0]["end_at"] = "2026-12-05T19:00:00+11:00"
    result = worker.handle(request_data)
    tasks = result["data"]["execution_plan"]["tasks"]
    base = dict(event_id="EV001", proposal_id="P1", action="assign_task",
                booking_id=result["data"]["bookings"][0]["booking_id"])
    assert worker.handle({**base, "task_id": tasks[0]["task_id"]})["status"] == "success"
    assert worker.handle({**base, "task_id": tasks[1]["task_id"]})["status"] == "blocked"
