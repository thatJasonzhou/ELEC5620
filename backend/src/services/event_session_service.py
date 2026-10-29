"""In-memory conversation state for the Stage 2 prototype."""
from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any
from uuid import uuid4


class EventSessionService:
    """Store event drafts behind a small service boundary.

    The interface can later be replaced by SQLite without changing the Agents
    or API routes.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = RLock()

    def get_or_create(self, event_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            identifier = event_id.strip() if isinstance(event_id, str) and event_id.strip() else f"EV-{uuid4().hex[:8].upper()}"
            if identifier not in self._sessions:
                self._sessions[identifier] = {
                    "event_id": identifier,
                    "requirements": {},
                    "progress": {"completed": 0, "total": 6, "missing_fields": []},
                    "history": [],
                    "stage": "requirements",
                    "proposal": None,
                    "plan_version": 0,
                    "plan_confirmed": False,
                    "vendor_recommendations": [],
                    "vendor_quotations": [],
                    "automatic_quotations": [],
                    "supplier_replies": [],
                    "supplier_requests": [],
                    "procurement_batch_id": None,
                    "quotation_rankings": [],
                    "recommended_quotation_ids": [],
                    "quotation_comparison_complete": False,
                    "quotation_comparison_fingerprint": None,
                    "selected_quotation_ids": [],
                    "finance_revision_attempts": 0,
                    "finance_feedback": None,
                    "budget": None,
                    "customer_quotation": None,
                    "approval": None,
                    "supplier_confirmations": [],
                    "declined_quotation_ids": [],
                    "deposit": None,
                    "final_payment": None,
                    "bookings": [],
                    "booking_replies": [],
                    "operations_plan": None,
                }
            return deepcopy(self._sessions[identifier])

    def save(self, session: dict[str, Any]) -> dict[str, Any]:
        event_id = session.get("event_id")
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("session event_id is required")
        with self._lock:
            self._sessions[event_id] = deepcopy(session)
            return deepcopy(session)

    def get(self, event_id: str) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(event_id)
            return deepcopy(session) if session is not None else None

    def list_all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [deepcopy(item) for item in self._sessions.values()]
