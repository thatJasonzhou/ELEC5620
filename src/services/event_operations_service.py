"""Operations MVP: deterministic, memory-only, no supplier/payment/LLM calls.

The caller supplies the current approved proposal and the *whole* successful
Procurement envelope, not a bare list from get_bookings(). These are trusted
internal handoffs, not cryptographically authenticated authorization records.
"""
from abc import ABC, abstractmethod
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
from threading import RLock
from uuid import uuid4

from src.shared.schemas import (ExecutionPlan, OperationalTask,
                                require_non_empty_str, require_valid_date)


class OperationsBlocked(ValueError):
    """Business precondition failed; caller must not advance the workflow."""


def text(value, name):
    # Do not reflect arbitrary user data into validation messages.
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def object_value(value, name):
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def timestamp(value, name):
    text(value, name)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{name} must be an ISO 8601 datetime") from None
    if parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone offset")
    return parsed


def interval(start, end, event_date):
    first, last = timestamp(start, "start_at"), timestamp(end, "end_at")
    if last <= first:
        raise ValueError("end_at must be after start_at")
    if first.date().isoformat() != event_date or last.date().isoformat() != event_date:
        raise ValueError("MVP tasks must start and end on event_date")


class EventOperationsService(ABC):
    """Service boundary used by the Agent; replace storage behind this interface."""

    @abstractmethod
    def create_execution_plan(self, request): ...

    @abstractmethod
    def monitor_execution(self, event_id, proposal_id): ...

    @abstractmethod
    def assign_task(self, event_id, proposal_id, task_id, booking_id): ...

    @abstractmethod
    def update_task_status(self, event_id, proposal_id, task_id, status, reason=None): ...

    @abstractmethod
    def add_task(self, event_id, proposal_id, title, start_at, end_at, booking_id=None): ...


class InMemoryEventOperationsService(EventOperationsService):
    """Session-local prototype. Repeated generation preserves task progress.

    A changed proposal/booking snapshot is blocked rather than overwriting an
    active plan. Revision, cancellation and database storage are follow-up work.
    """

    def __init__(self):
        self._records = {}
        self._lock = RLock()

    @staticmethod
    def _validate(request):
        object_value(request, "request")
        event_id = text(request.get("event_id"), "event_id")
        event_date = require_valid_date(request.get("event_date"), "event_date")
        proposal = object_value(request.get("proposal"), "proposal")
        proposal_id = text(proposal.get("proposal_id"), "proposal.proposal_id")
        if proposal.get("event_id") != event_id:
            raise OperationsBlocked("Proposal belongs to another event.")
        if proposal.get("status") != "Approved":
            raise OperationsBlocked("Customer-approved proposal required.")
        required = proposal.get("required_services")
        if not isinstance(required, list) or not required:
            raise ValueError("required_services must be a non-empty list")
        for item in required:
            text(item, "required service")
        if len(set(required)) != len(required):
            raise ValueError("Duplicate required service")
        timeline = proposal.get("timeline")
        if not isinstance(timeline, list) or not timeline:
            raise ValueError("A non-empty approved timeline is required; times are never invented.")
        slots = []
        for slot in timeline:
            object_value(slot, "timeline item")
            title = text(slot.get("title"), "timeline title")
            interval(slot.get("start_at"), slot.get("end_at"), event_date)
            slots.append({"title": title, "start_at": slot["start_at"], "end_at": slot["end_at"]})
        result = object_value(request.get("procurement_result"), "procurement_result")
        if result.get("agent") != "procurement" or result.get("event_id") != event_id:
            raise OperationsBlocked("A matching Procurement result is required.")
        if result.get("status") != "success":
            raise OperationsBlocked("Procurement did not succeed; partial bookings cannot advance.")
        data = object_value(result.get("data"), "procurement_result.data")
        if data.get("requires_attention") is not False:
            raise OperationsBlocked("Procurement handoff requires review.")
        payment = object_value(data.get("customer_payment"), "customer_payment")
        if (payment.get("event_id") != event_id or payment.get("proposal_id") != proposal_id
                or payment.get("status") != "paid" or payment.get("mock") is not True):
            raise OperationsBlocked("Matching paid mock deposit handoff required.")
        text(payment.get("payment_id"), "payment_id")
        text(payment.get("quotation_fingerprint"), "quotation_fingerprint")
        if type(payment.get("amount_cents")) is not int or payment["amount_cents"] <= 0:
            raise ValueError("Deposit amount must be a positive integer in AUD cents")
        bookings = data.get("bookings")
        if not isinstance(bookings, list) or not bookings:
            raise OperationsBlocked("No confirmed bookings supplied.")
        for booking in bookings:
            object_value(booking, "booking")
            for name in ("booking_id", "vendor_id", "quotation_id", "service_type",
                         "supplier_confirmation_id", "source_quotation_fingerprint"):
                text(booking.get(name), "booking." + name)
            if (booking.get("event_id") != event_id or booking.get("proposal_id") != proposal_id
                    or booking.get("event_date") != event_date or booking.get("status") != "Confirmed"
                    or booking.get("mock") is not True):
                raise OperationsBlocked("Booking identity/date/status mismatch; confirmed mock bookings required.")
        for name in ("booking_id", "quotation_id"):
            if len({b[name] for b in bookings}) != len(bookings):
                raise ValueError("Duplicate booking identity")
        if not set(required).issubset({b["service_type"] for b in bookings}):
            raise OperationsBlocked("A required service has no confirmed booking.")
        return event_id, event_date, proposal_id, slots, deepcopy(bookings), deepcopy(payment)

    def create_execution_plan(self, request):
        event_id, date, proposal_id, slots, bookings, payment = self._validate(request)
        fingerprint = sha256(json.dumps([date, request["proposal"],
            sorted(bookings, key=lambda b: b["booking_id"]), payment],
            sort_keys=True, allow_nan=False).encode()).hexdigest()
        with self._lock:
            if event_id in self._records:
                if self._records[event_id]["fingerprint"] != fingerprint:
                    raise OperationsBlocked("Active plan exists with different inputs; reviewed revision is required.")
                return self.monitor_execution(event_id, proposal_id)
            plan = ExecutionPlan(event_id, proposal_id, "EP-" + uuid4().hex)
            for slot in sorted(slots, key=lambda s: timestamp(s["start_at"], "start_at")):
                plan.add_task(OperationalTask("TASK-" + uuid4().hex, slot["title"],
                                              slot["start_at"], slot["end_at"]))
            self._records[event_id] = {"plan": plan, "bookings": bookings,
                                       "event_date": date, "fingerprint": fingerprint}
            return self.monitor_execution(event_id, proposal_id)

    def _record(self, event_id, proposal_id):
        text(event_id, "event_id")
        text(proposal_id, "proposal_id")
        record = self._records.get(event_id)
        if record is None:
            raise OperationsBlocked("No execution plan for this event. Generate or load it first.")
        if record["plan"].proposal_id != proposal_id:
            raise OperationsBlocked("Proposal does not match the active execution plan.")
        return record

    @staticmethod
    def _task(record, task_id):
        text(task_id, "task_id")
        for task in record["plan"].tasks:
            if task.task_id == task_id:
                return task
        raise ValueError("Unknown task_id")

    @staticmethod
    def _check_assignment(record, booking_id, start, end, exclude=None):
        if booking_id is None:
            return
        text(booking_id, "booking_id")
        if booking_id not in {b["booking_id"] for b in record["bookings"]}:
            raise ValueError("booking_id is not in this plan's confirmed bookings")
        for task in record["plan"].tasks:
            if task.task_id == exclude or task.booking_id != booking_id:
                continue
            if (timestamp(start, "start") < timestamp(task.planned_end_time, "end") and
                    timestamp(task.planned_start_time, "start") < timestamp(end, "end")):
                raise OperationsBlocked("This booking already has an overlapping task; review its assignment.")

    def monitor_execution(self, event_id, proposal_id):
        with self._lock:
            record = self._record(event_id, proposal_id)
            tasks = record["plan"].tasks
            unassigned = [b["booking_id"] for b in record["bookings"]
                          if not any(t.booking_id == b["booking_id"] for t in tasks)]
            all_done = bool(tasks) and all(t.status == "COMPLETED" for t in tasks)
            return {"execution_plan": record["plan"].to_dict(),
                    "bookings": deepcopy(record["bookings"]),
                    "summary": {"total": len(tasks),
                                "completed": sum(t.status == "COMPLETED" for t in tasks),
                                "delayed": sum(t.status == "DELAYED" for t in tasks),
                                "all_tasks_completed": all_done,
                                "unassigned_booking_ids": unassigned,
                                "execution_complete": all_done and not unassigned},
                    "storage": "memory-only"}

    def assign_task(self, event_id, proposal_id, task_id, booking_id):
        with self._lock:
            record = self._record(event_id, proposal_id)
            task = self._task(record, task_id)
            if task.status != "NOT_STARTED":
                raise OperationsBlocked("Only an unstarted task can be reassigned.")
            self._check_assignment(record, booking_id, task.planned_start_time,
                                   task.planned_end_time, task_id)
            task.booking_id = booking_id
            return self.monitor_execution(event_id, proposal_id)

    def add_task(self, event_id, proposal_id, title, start_at, end_at, booking_id=None):
        with self._lock:
            record = self._record(event_id, proposal_id)
            text(title, "title")
            interval(start_at, end_at, record["event_date"])
            self._check_assignment(record, booking_id, start_at, end_at)
            record["plan"].add_task(OperationalTask("TASK-" + uuid4().hex, title,
                                                  start_at, end_at, booking_id))
            record["plan"].tasks.sort(key=lambda t: timestamp(t.planned_start_time, "start"))
            return self.monitor_execution(event_id, proposal_id)

    def update_task_status(self, event_id, proposal_id, task_id, status, reason=None):
        with self._lock:
            task = self._task(self._record(event_id, proposal_id), task_id)
            text(status, "status")
            task.update_status(status, reason)
            return self.monitor_execution(event_id, proposal_id)
