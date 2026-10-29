from pathlib import Path

import pytest

from src.services.event_operations_service import (
    EventOperationsService,
    OperationsBlocked,
)


def request() -> dict:
    return {
        "event_id": "EV-OPS-DEMO",
        "event_date": "2026-12-16",
        "proposal": {
            "event_id": "EV-OPS-DEMO",
            "proposal_id": "PP-OPS-DEMO",
            "status": "Approved",
            "required_services": ["venue"],
            "service_schedule": [
                {
                    "service_type": "venue",
                    "arrival_time": "14:00",
                    "start_time": "15:00",
                    "end_time": "18:00",
                }
            ],
        },
        "bookings": [
            {
                "booking_id": "BK-OPS-DEMO",
                "vendor_id": "V-VENUE-001",
                "service_type": "venue",
                "status": "Confirmed",
            }
        ],
    }


def test_operations_late_arrival_to_finalization() -> None:
    service = EventOperationsService(late_after_minutes=1)
    plan = service.generate_execution_plan(request())
    task_id = plan["tasks"][0]["task_id"]

    delayed = service.perform_action(
        plan["event_id"], plan["proposal_id"], "advance_clock", {"minutes": 2}
    )
    assert delayed["tasks"][0]["status"] == "DELAYED"
    assert delayed["issues"][0]["status"] == "OPEN"

    arrived = service.perform_action(
        plan["event_id"], plan["proposal_id"], "record_arrival", {"task_id": task_id}
    )
    assert arrived["tasks"][0]["arrival_status"] == "ARRIVED"
    assert arrived["issues"][0]["status"] == "RESOLVED"

    started = service.perform_action(
        plan["event_id"], plan["proposal_id"], "start_service", {"task_id": task_id}
    )
    assert started["tasks"][0]["status"] == "IN_PROGRESS"
    completed = service.perform_action(
        plan["event_id"], plan["proposal_id"], "complete_service", {"task_id": task_id}
    )
    assert completed["status"] == "READY_TO_FINALIZE"
    finalized = service.perform_action(
        plan["event_id"], plan["proposal_id"], "finalize_execution", {"confirm": True}
    )
    assert finalized["status"] == "COMPLETED"
    assert finalized["finalized"] is True


def test_operations_requires_arrival_and_persists(tmp_path: Path) -> None:
    database = tmp_path / "shared.sqlite3"
    service = EventOperationsService(database)
    plan = service.generate_execution_plan(request())
    task_id = plan["tasks"][0]["task_id"]

    with pytest.raises(OperationsBlocked, match="Confirm supplier arrival"):
        service.perform_action(
            plan["event_id"], plan["proposal_id"], "start_service", {"task_id": task_id}
        )

    reloaded = EventOperationsService(database).monitor_execution(plan["event_id"])
    assert reloaded["execution_plan_id"] == plan["execution_plan_id"]
    assert reloaded["tasks"][0]["status"] == "NOT_STARTED"


def test_non_venue_service_is_explicit_automatic_mock() -> None:
    payload = request()
    payload["proposal"]["required_services"].append("photography")
    payload["proposal"]["service_schedule"].append(
        {
            "service_type": "photography",
            "arrival_time": "14:30",
            "start_time": "15:00",
            "end_time": "18:00",
        }
    )
    payload["bookings"].append(
        {
            "booking_id": "BK-PHOTO-DEMO",
            "vendor_id": "V-PHOTO-001",
            "service_type": "photography",
            "status": "Confirmed",
        }
    )

    plan = EventOperationsService().generate_execution_plan(payload)
    photography = next(
        task for task in plan["tasks"] if task["service_type"] == "photography"
    )
    assert photography["mock_automatic"] is True
    assert photography["arrival_status"] == "ARRIVED"
    assert photography["status"] == "COMPLETED"


def test_clear_all_removes_persisted_operations_cases(tmp_path: Path) -> None:
    database = tmp_path / "shared.sqlite3"
    service = EventOperationsService(database)
    service.generate_execution_plan(request())

    assert service.clear_all() == 1
    assert service.list_execution_plans() == []
    assert EventOperationsService(database).list_execution_plans() == []
