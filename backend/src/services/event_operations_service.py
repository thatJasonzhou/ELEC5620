"""Persistent deterministic Operations lifecycle for the Stage 2 prototype."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any
from zoneinfo import ZoneInfo

from src.shared.schemas import require_non_empty_str


class OperationsBlocked(ValueError):
    """A valid Operations command cannot run in the current state."""


class EventOperationsService:
    """Create and maintain execution tasks after confirmed bookings."""

    def __init__(
        self,
        database_path: str | Path | None = None,
        *,
        timezone: str = "Australia/Sydney",
        late_after_minutes: int = 1,
    ) -> None:
        self._timezone = ZoneInfo(timezone)
        self._late_after_minutes = late_after_minutes
        self._lock = RLock()
        self._memory: dict[str, dict[str, Any]] = {}
        self._database_path = Path(database_path).resolve() if database_path else None
        if self._database_path is not None:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self._database_path) as connection:
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS operations_records (
                    event_id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                    )"""
                )

    def _now(self) -> str:
        return datetime.now(self._timezone).isoformat(timespec="seconds")

    def _load(self, event_id: str) -> dict[str, Any] | None:
        if self._database_path is None:
            record = deepcopy(self._memory.get(event_id))
            return self._normalise_record(record) if record else None
        with sqlite3.connect(self._database_path) as connection:
            row = connection.execute(
                "SELECT payload FROM operations_records WHERE event_id=?", (event_id,)
            ).fetchone()
        return self._normalise_record(json.loads(row[0])) if row else None

    def _save(self, record: dict[str, Any]) -> None:
        if self._database_path is None:
            self._memory[record["event_id"]] = deepcopy(record)
            return
        payload = json.dumps(
            record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        with sqlite3.connect(self._database_path) as connection:
            connection.execute(
                """INSERT INTO operations_records(event_id, proposal_id, payload)
                VALUES (?, ?, ?) ON CONFLICT(event_id) DO UPDATE SET
                proposal_id=excluded.proposal_id, payload=excluded.payload""",
                (record["event_id"], record["proposal_id"], payload),
            )

    @staticmethod
    def _task(record: dict[str, Any], task_id: Any) -> dict[str, Any]:
        identity = require_non_empty_str(task_id, "task_id")
        task = next(
            (item for item in record["tasks"] if item["task_id"] == identity), None
        )
        if task is None:
            raise ValueError("unknown Operations task")
        return task

    def _event_time(self, record: dict[str, Any], value: str) -> datetime:
        try:
            hour, minute = (int(part) for part in value.split(":"))
            return datetime.fromisoformat(record["event_date"]).replace(
                hour=hour, minute=minute, tzinfo=self._timezone
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("time must use HH:MM") from exc

    def _normalise_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Upgrade earlier demo records and keep non-venue services explicit Mock."""
        record.setdefault("customer_completion_confirmation", None)
        automatic_task_ids: set[str] = set()
        for task in record.get("tasks", []):
            automatic = task.get("service_type") != "venue"
            task["mock_automatic"] = automatic
            if automatic:
                automatic_task_ids.add(task["task_id"])
                task.update(
                    status="COMPLETED",
                    arrival_status="ARRIVED",
                    arrived_at=self._event_time(record, task["scheduled_at"]).isoformat(
                        timespec="minutes"
                    ),
                    actual_start_at=self._event_time(
                        record, task["planned_start_time"]
                    ).isoformat(timespec="minutes"),
                    actual_end_at=self._event_time(
                        record, task["planned_end_time"]
                    ).isoformat(timespec="minutes"),
                    delay_reason=None,
                )
        for issue in record.get("issues", []):
            if issue.get("task_id") in automatic_task_ids and issue.get("status") == "OPEN":
                issue.update(
                    status="RESOLVED",
                    resolution="Automatically resolved for the simulated supplier.",
                    resolved_at=self._now(),
                )
        if record.get("finalized"):
            record["status"] = "COMPLETED"
        elif record.get("tasks") and all(
            task.get("status") == "COMPLETED" for task in record["tasks"]
        ):
            record["status"] = "READY_TO_FINALIZE"
        return record

    def generate_execution_plan(self, request: dict[str, Any]) -> dict[str, Any]:
        event_id = require_non_empty_str(request.get("event_id"), "event_id")
        proposal = request.get("proposal")
        bookings = request.get("bookings")
        event_date = request.get("event_date")
        if not isinstance(proposal, dict):
            raise ValueError("proposal must be an object")
        if proposal.get("event_id") != event_id or proposal.get("status") != "Approved":
            raise ValueError("an approved proposal is required")
        if not isinstance(event_date, str) or not event_date:
            raise ValueError("event_date is required")
        schedule = proposal.get("service_schedule")
        if not isinstance(schedule, list) or not schedule:
            raise ValueError("approved service_schedule is required")
        if not isinstance(bookings, list) or not bookings:
            raise ValueError("confirmed supplier bookings are required")
        by_service = {
            require_non_empty_str(item.get("service_type"), "booking service_type"): item
            for item in bookings
            if isinstance(item, dict) and item.get("status") == "Confirmed"
        }
        required = proposal.get("required_services")
        if not isinstance(required, list) or set(by_service) != set(required):
            raise ValueError("one confirmed booking is required for every service")

        with self._lock:
            existing = self._load(event_id)
            if existing is not None:
                if existing["proposal_id"] != proposal.get("proposal_id"):
                    raise OperationsBlocked(
                        "Operations already exists for another proposal; review the revision."
                    )
                return deepcopy(existing)

            tasks: list[dict[str, Any]] = []
            for item in schedule:
                service = require_non_empty_str(item.get("service_type"), "service_type")
                booking = by_service.get(service)
                if booking is None:
                    raise ValueError(f"confirmed booking missing for {service}")
                identity = json.dumps(
                    [event_id, proposal.get("proposal_id"), service, booking.get("booking_id")],
                    separators=(",", ":"),
                )
                automatic = service != "venue"
                task = {
                        "task_id": "OT-" + sha256(identity.encode()).hexdigest()[:16].upper(),
                        "title": f"{service.replace('_', ' ').title()} service",
                        "service_type": service,
                        "scheduled_at": item["arrival_time"],
                        "planned_start_time": item["start_time"],
                        "planned_end_time": item["end_time"],
                        "booking_id": booking["booking_id"],
                        "vendor_id": booking["vendor_id"],
                        "status": "COMPLETED" if automatic else "NOT_STARTED",
                        "arrival_status": "ARRIVED" if automatic else "PENDING",
                        "expected_arrival_time": item["arrival_time"],
                        "arrived_at": None,
                        "actual_start_at": None,
                        "actual_end_at": None,
                        "delay_reason": None,
                        "mock_automatic": automatic,
                    }
                if automatic:
                    task.update(
                        arrived_at=self._event_time(
                            {"event_date": event_date}, item["arrival_time"]
                        ).isoformat(timespec="minutes"),
                        actual_start_at=self._event_time(
                            {"event_date": event_date}, item["start_time"]
                        ).isoformat(timespec="minutes"),
                        actual_end_at=self._event_time(
                            {"event_date": event_date}, item["end_time"]
                        ).isoformat(timespec="minutes"),
                    )
                tasks.append(task)
            record = {
                "event_id": event_id,
                "event_date": event_date,
                "proposal_id": proposal["proposal_id"],
                "execution_plan_id": "EP-"
                + sha256(json.dumps([event_id, proposal["proposal_id"]]).encode()).hexdigest()[:16].upper(),
                "status": "READY",
                "simulated_time": None,
                "tasks": tasks,
                "issues": [],
                "notifications": [],
                "feedback": [],
                "finalized": False,
                "customer_completion_confirmation": None,
                "updated_at": self._now(),
            }
            self._save(record)
            return deepcopy(record)

    def monitor_execution(self, event_id: str, proposal_id: str | None = None) -> dict[str, Any]:
        identity = require_non_empty_str(event_id, "event_id")
        with self._lock:
            record = self._load(identity)
        if record is None:
            raise KeyError("Operations event not found")
        if proposal_id is not None and record["proposal_id"] != proposal_id:
            raise ValueError("proposal_id does not match the Operations plan")
        return record

    def list_execution_plans(self) -> list[dict[str, Any]]:
        with self._lock:
            if self._database_path is None:
                records = list(self._memory.values())
            else:
                with sqlite3.connect(self._database_path) as connection:
                    rows = connection.execute(
                        "SELECT payload FROM operations_records ORDER BY event_id"
                    ).fetchall()
                records = [json.loads(row[0]) for row in rows]
        return deepcopy([self._normalise_record(record) for record in records])

    def clear_all(self) -> int:
        """Clear local simulated Operations cases for the demo reset control."""
        with self._lock:
            if self._database_path is None:
                count = len(self._memory)
                self._memory.clear()
                return count
            with sqlite3.connect(self._database_path) as connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM operations_records"
                ).fetchone()[0]
                connection.execute("DELETE FROM operations_records")
            return int(count)

    def snapshot_event(self, event_id: str) -> dict[str, Any] | None:
        identity = require_non_empty_str(event_id, "event_id")
        with self._lock:
            record = self._load(identity)
            return deepcopy(record) if record is not None else None

    def restore_event(self, event_id: str, snapshot: dict[str, Any] | None) -> None:
        identity = require_non_empty_str(event_id, "event_id")
        with self._lock:
            if snapshot is None:
                if self._database_path is None:
                    self._memory.pop(identity, None)
                else:
                    with sqlite3.connect(self._database_path) as connection:
                        connection.execute(
                            "DELETE FROM operations_records WHERE event_id=?", (identity,)
                        )
                return
            if snapshot.get("event_id") != identity:
                raise ValueError("Operations checkpoint event_id does not match")
            self._save(deepcopy(snapshot))

    def perform_action(
        self, event_id: str, proposal_id: str, action: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        identity = require_non_empty_str(event_id, "event_id")
        command = require_non_empty_str(action, "action")
        with self._lock:
            record = self._load(identity)
            if record is None:
                raise KeyError("Operations event not found")
            if record["proposal_id"] != proposal_id:
                raise ValueError("proposal_id does not match the Operations plan")
            if record.get("finalized") and command != "record_feedback":
                raise OperationsBlocked("Finalized Operations is read-only.")

            if command == "set_event_time":
                selected_time = require_non_empty_str(
                    fields.get("event_time"), "event_time"
                )
                selected_at = self._event_time(record, selected_time)
                record["simulated_time"] = selected_at.isoformat(timespec="minutes")

            elif command == "record_arrival":
                task = self._task(record, fields.get("task_id"))
                if task["arrival_status"] == "ARRIVED":
                    return deepcopy(record)
                pending_adjustment = next(
                    (
                        issue.get("adjustment")
                        for issue in record["issues"]
                        if issue.get("task_id") == task["task_id"]
                        and issue.get("status") == "OPEN"
                        and isinstance(issue.get("adjustment"), dict)
                        and issue["adjustment"].get("status") == "PROPOSED"
                    ),
                    None,
                )
                if pending_adjustment is not None:
                    raise OperationsBlocked(
                        "Wait for the customer to accept the delay adjustment before confirming arrival."
                    )
                task["arrival_status"] = "ARRIVED"
                task["arrived_at"] = record.get("simulated_time") or self._now()
                if task["status"] == "DELAYED":
                    task["status"] = "NOT_STARTED"
                for issue in record["issues"]:
                    if issue.get("task_id") == task["task_id"] and issue["status"] == "OPEN":
                        issue.update(
                            status="RESOLVED",
                            resolution="Supplier confirmed arrival.",
                            resolved_at=record.get("simulated_time") or self._now(),
                        )
                self._notify(record, task, f"{task['title']} supplier has arrived.")

            elif command == "report_delay":
                task = self._task(record, fields.get("task_id"))
                if task["arrival_status"] == "ARRIVED":
                    raise OperationsBlocked("Arrival is already recorded.")
                expected = require_non_empty_str(
                    fields.get("expected_arrival_time"), "expected_arrival_time"
                )
                self._event_time(record, expected)
                reason = require_non_empty_str(fields.get("reason"), "reason")
                adjustment = self._delay_adjustment(record, task, expected)
                task.update(
                    status="DELAYED",
                    arrival_status="DELAYED",
                    expected_arrival_time=expected,
                    delay_reason=reason,
                )
                issue = self._open_issue(record, task, reason)
                issue["adjustment"] = adjustment
                self._notify(
                    record,
                    task,
                    f"{task['title']} supplier reported a delay and expects to arrive at {expected}.",
                )

            elif command == "accept_delay_adjustment":
                issue_id = require_non_empty_str(fields.get("issue_id"), "issue_id")
                issue = next(
                    (item for item in record["issues"] if item["issue_id"] == issue_id),
                    None,
                )
                if issue is None or issue.get("status") != "OPEN":
                    raise OperationsBlocked("The delay issue is no longer awaiting a decision.")
                adjustment = issue.get("adjustment")
                if not isinstance(adjustment, dict) or adjustment.get("status") != "PROPOSED":
                    raise OperationsBlocked("No proposed delay adjustment is awaiting acceptance.")
                task = self._task(record, issue.get("task_id"))
                adjustment.update(
                    status="CUSTOMER_ACCEPTED",
                    accepted_at=record.get("simulated_time") or self._now(),
                )
                task["planned_start_time"] = adjustment["proposed_start_time"]
                task["planned_end_time"] = adjustment["proposed_end_time"]
                self._notify(
                    record,
                    task,
                    f"Customer accepted the revised arrival time of {adjustment['expected_arrival_time']}.",
                )

            elif command == "start_service":
                task = self._task(record, fields.get("task_id"))
                if task["arrival_status"] != "ARRIVED":
                    raise OperationsBlocked("Confirm supplier arrival before starting service.")
                if task["status"] == "COMPLETED":
                    raise OperationsBlocked("Completed service cannot be restarted.")
                task["status"] = "IN_PROGRESS"
                task["actual_start_at"] = record.get("simulated_time") or self._now()
                self._notify(record, task, f"{task['title']} has started.")

            elif command == "complete_service":
                task = self._task(record, fields.get("task_id"))
                if task["status"] != "IN_PROGRESS":
                    raise OperationsBlocked("Start the service before completing it.")
                task["status"] = "COMPLETED"
                task["actual_end_at"] = record.get("simulated_time") or self._now()
                self._notify(record, task, f"{task['title']} has been completed.")

            elif command == "advance_clock":
                minutes = fields.get("minutes")
                if type(minutes) is not int or minutes not in (1, 2, 5, 10, 15):
                    raise ValueError("minutes must be one of 1, 2, 5, 10 or 15")
                current = (
                    datetime.fromisoformat(record["simulated_time"])
                    if record.get("simulated_time")
                    else min(
                        self._event_time(record, task["scheduled_at"])
                        for task in record["tasks"]
                    )
                )
                current += timedelta(minutes=minutes)
                record["simulated_time"] = current.isoformat(timespec="minutes")
                for task in record["tasks"]:
                    expected = self._event_time(record, task["expected_arrival_time"])
                    if (
                        task["arrival_status"] == "PENDING"
                        and current > expected + timedelta(minutes=self._late_after_minutes)
                    ):
                        task.update(
                            status="DELAYED",
                            arrival_status="DELAYED",
                            delay_reason="Supplier has not confirmed arrival.",
                        )
                        self._open_issue(record, task, task["delay_reason"])
                        self._notify(
                            record,
                            task,
                            f"{task['title']} supplier has not confirmed arrival.",
                        )

            elif command == "resolve_issue":
                issue_id = require_non_empty_str(fields.get("issue_id"), "issue_id")
                issue = next(
                    (item for item in record["issues"] if item["issue_id"] == issue_id),
                    None,
                )
                if issue is None:
                    raise ValueError("unknown Operations issue")
                issue.update(
                    status="RESOLVED",
                    resolution=require_non_empty_str(fields.get("resolution"), "resolution"),
                    resolved_at=record.get("simulated_time") or self._now(),
                )

            elif command == "record_feedback":
                if not record.get("finalized"):
                    raise OperationsBlocked("Finalize Operations before recording feedback.")
                if record["feedback"]:
                    raise OperationsBlocked("Customer feedback has already been submitted.")
                rating = fields.get("rating")
                if type(rating) is not int or not 1 <= rating <= 5:
                    raise ValueError("rating must be an integer from 1 to 5")
                record["feedback"].append(
                    {
                        "rating": rating,
                        "comments": require_non_empty_str(fields.get("comments"), "comments"),
                        "created_at": self._now(),
                    }
                )

            elif command in {"finalize_execution", "confirm_event_completion"}:
                if any(task["status"] != "COMPLETED" for task in record["tasks"]):
                    raise OperationsBlocked("Complete every service before finalizing Operations.")
                if any(issue["status"] == "OPEN" for issue in record["issues"]):
                    raise OperationsBlocked("Resolve open Operations issues before finalizing.")
                if fields.get("confirm") is not True:
                    raise OperationsBlocked("Customer completion confirmation is required.")
                confirmed_at = record.get("simulated_time") or self._now()
                record["customer_completion_confirmation"] = {
                    "confirmed": True,
                    "confirmed_at": confirmed_at,
                    "source": "customer",
                }
                record["finalized"] = True
                record["status"] = "COMPLETED"
            else:
                raise ValueError("unsupported Operations action")

            if not record.get("finalized"):
                if all(task["status"] == "COMPLETED" for task in record["tasks"]):
                    record["status"] = "READY_TO_FINALIZE"
                elif any(task["status"] in {"IN_PROGRESS", "DELAYED"} for task in record["tasks"]):
                    record["status"] = "IN_PROGRESS"
                else:
                    record["status"] = "READY"
            record["updated_at"] = self._now()
            self._save(record)
            return deepcopy(record)

    def _open_issue(
        self, record: dict[str, Any], task: dict[str, Any], description: str
    ) -> dict[str, Any]:
        existing = next(
            (
                issue
                for issue in record["issues"]
                if issue.get("task_id") == task["task_id"] and issue["status"] == "OPEN"
            ),
            None,
        )
        if existing is None:
            existing = {
                "issue_id": "ISS-"
                + sha256(
                    f"{task['task_id']}:{len(record['issues'])}".encode()
                ).hexdigest()[:12].upper(),
                "task_id": task["task_id"],
                "kind": "LATE_ARRIVAL",
                "description": description,
                "status": "OPEN",
                "created_at": self._now(),
            }
            record["issues"].append(existing)
        return existing

    def _delay_adjustment(
        self, record: dict[str, Any], task: dict[str, Any], expected: str
    ) -> dict[str, Any]:
        original = task["scheduled_at"]
        expected_at = self._event_time(record, expected)
        planned_start_at = self._event_time(record, task["planned_start_time"])
        planned_end_at = self._event_time(record, task["planned_end_time"])
        if expected_at >= planned_end_at:
            raise OperationsBlocked(
                "The revised arrival time is after the planned service end and needs a new plan."
            )
        if expected_at <= planned_start_at:
            proposed_start = task["planned_start_time"]
            remaining_setup = int((planned_start_at - expected_at).total_seconds() // 60)
            recommendation = (
                f"Accept the revised arrival time of {expected}. "
                f"There will still be {remaining_setup} minutes for setup, so the service can start at "
                f"{proposed_start} as planned."
            )
        else:
            proposed_start = expected
            recommendation = (
                f"Accept the revised arrival time of {expected} and move the service start to "
                f"{expected}. Keep the planned end time of {task['planned_end_time']}."
            )
        return {
            "status": "PROPOSED",
            "original_arrival_time": original,
            "expected_arrival_time": expected,
            "proposed_start_time": proposed_start,
            "proposed_end_time": task["planned_end_time"],
            "recommendation": recommendation,
            "created_at": record.get("simulated_time") or self._now(),
            "accepted_at": None,
        }

    def _notify(
        self, record: dict[str, Any], task: dict[str, Any], message: str
    ) -> None:
        record["notifications"].append(
            {
                "notification_id": "N-"
                + sha256(
                    f"{task['task_id']}:{len(record['notifications'])}".encode()
                ).hexdigest()[:12].upper(),
                "task_id": task["task_id"],
                "message": message,
                "created_at": record.get("simulated_time") or self._now(),
            }
        )
