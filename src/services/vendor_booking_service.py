"""Deterministic mock booking with optional durable Procurement records.

No payment, refund or network call is performed here. SQLite is opt-in.
Caller-supplied approval/budget/payment records are trusted internal handoff
data for this prototype, not evidence authenticated against a payment gateway.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from src.services.procurement_record_service import ProcurementRecordService, ProcurementStorageError
from src.shared.schemas import VendorBooking, require_int, require_non_empty_str, require_valid_date


def _text(value, name):
    return require_non_empty_str(value, name)


def _quote(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("quotation must be an object")
    result = {name: _text(raw.get(name), name) for name in
              ("event_id", "proposal_id", "quotation_id", "vendor_id", "offering_id", "service_type")}
    result["event_date"] = require_valid_date(raw.get("event_date"), "event_date")
    result["guest_count"] = require_int(raw.get("guest_count"), "guest_count", minimum=0)
    result["quoted_total_cents"] = require_int(raw.get("quoted_total_cents"), "quoted_total_cents", minimum=0)
    if raw.get("available") is not True or raw.get("mock") is not True:
        raise ValueError("quotation must be confirmed available and explicitly mock")
    result.update(available=True, mock=True)
    return result


def quotation_fingerprint(quotations: list[dict[str, Any]]) -> str:
    """Bind the selected quote identities, requirements and amounts (not free text)."""
    if not isinstance(quotations, list) or not quotations:
        raise ValueError("quotations must be a non-empty list")
    quotes = [_quote(q) for q in quotations]
    if len({q["quotation_id"] for q in quotes}) != len(quotes):
        raise ValueError("duplicate quotation_id")
    if len({(q["vendor_id"], q["offering_id"], q["event_date"]) for q in quotes}) != len(quotes):
        raise ValueError("duplicate selected supplier offering/date")
    payload = json.dumps(sorted(quotes, key=lambda q: q["quotation_id"]), sort_keys=True,
                         ensure_ascii=False, separators=(",", ":"))
    return "QF-" + sha256(payload.encode("utf-8")).hexdigest()


class NoBookingScenarioError(ValueError):
    """The simulator has no final supplier reply for a valid booking request."""


class MockVendorBookingService:
    """Preset final replies, independent of enquiry/catalogue availability."""

    def __init__(self, scenarios: list[dict[str, Any]]) -> None:
        if not isinstance(scenarios, list):
            raise ValueError("booking scenarios must be a list")
        self._index = {}
        self.calls: list[dict[str, Any]] = []
        for raw in scenarios:
            if not isinstance(raw, dict):
                raise ValueError("booking scenario must be an object")
            item = {n: _text(raw.get(n), n) for n in ("scenario_id", "vendor_id", "offering_id", "reason")}
            item["event_date"] = require_valid_date(raw.get("event_date"), "event_date")
            item["guest_count"] = require_int(raw.get("guest_count"), "guest_count", minimum=0)
            status = raw.get("status")
            if status not in ("confirmed", "rejected", "pending"):
                raise ValueError("booking scenario status must be confirmed/rejected/pending")
            item["status"] = status
            item["supplier_confirmation_id"] = (
                _text(raw.get("supplier_confirmation_id"), "supplier_confirmation_id")
                if status == "confirmed" else None
            )
            if status != "confirmed" and raw.get("supplier_confirmation_id") is not None:
                raise ValueError("unconfirmed booking cannot contain a confirmation ID")
            key = self._key(item)
            if key in self._index:
                raise ValueError("duplicate booking scenario")
            self._index[key] = item

    @staticmethod
    def _key(item):
        return tuple(item[n] for n in ("vendor_id", "offering_id", "event_date", "guest_count"))

    @classmethod
    def from_json_file(cls, path: str | Path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "scenarios" not in data:
            raise ValueError("booking scenario file must contain scenarios")
        return cls(data["scenarios"])

    def request_booking(self, quotation: dict[str, Any]) -> dict[str, Any]:
        quote = _quote(quotation)
        self.calls.append(deepcopy(quote))
        scenario = self._index.get(self._key(quote))
        if scenario is None:
            raise NoBookingScenarioError("No final mock supplier booking reply configured.")
        return {**quote, **{n: scenario[n] for n in
                ("scenario_id", "status", "reason", "supplier_confirmation_id")}, "mock": True}


class VendorBookingService:
    """Validate handoff gates; optionally reload/save confirmed bookings in SQLite."""

    def __init__(self, supplier_service: MockVendorBookingService, *,
                 record_service: ProcurementRecordService | None = None) -> None:
        if not isinstance(supplier_service, MockVendorBookingService):
            raise TypeError("supplier_service must be a MockVendorBookingService")
        self.supplier_service = supplier_service
        if record_service is not None and not isinstance(record_service, ProcurementRecordService):
            raise TypeError("record_service must be a ProcurementRecordService instance")
        self._record_service = record_service
        self._bookings: dict[tuple[str, str, str], VendorBooking] = {}

    def _refresh_bookings(self):
        if self._record_service is not None:
            for raw in self._record_service.all_bookings():
                booking = VendorBooking(**raw)
                key = (booking.event_id, booking.proposal_id, booking.quotation_id)
                if key in self._bookings and self._bookings[key] != booking:
                    raise ProcurementStorageError("Stored booking conflicts with a retained confirmation.")
                self._bookings[key] = booking

    @property
    def bookings(self):
        self._refresh_bookings()
        return [asdict(b) for b in self._bookings.values()]

    def get_bookings(self, event_id: str, proposal_id: str):
        """Operations handoff read, without sending any supplier request."""
        _text(event_id, "event_id")
        _text(proposal_id, "proposal_id")
        return [b for b in self.bookings if b["event_id"] == event_id and b["proposal_id"] == proposal_id]

    def confirm_bookings(self, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict):
            return self._result(None, "error", "request must be an object", {})
        event_id = request.get("event_id")
        if not isinstance(event_id, str) or not event_id.strip():
            event_id = None
        try:
            _text(event_id, "event_id")
            proposal_id = _text(request.get("proposal_id"), "proposal_id")
            fingerprint = quotation_fingerprint(request.get("quotations"))
            quotes = [_quote(q) for q in request["quotations"]]
            approval, budget, deposit = [self._record(request.get(n), n) for n in ("approval", "budget", "deposit")]
            if type(approval.get("approved")) is not bool or type(budget.get("within_budget")) is not bool:
                raise ValueError("approved and within_budget must be booleans")
            approved_ids = approval.get("approved_quotation_ids")
            if not isinstance(approved_ids, list):
                raise ValueError("approved_quotation_ids must be a list")
            for value in approved_ids:
                _text(value, "approved_quotation_ids item")
            if len(set(approved_ids)) != len(approved_ids):
                raise ValueError("duplicate approved quotation ID")
            due = require_int(budget.get("deposit_due_cents"), "deposit_due_cents", minimum=1)
            paid = require_int(deposit.get("amount_cents"), "amount_cents", minimum=0)
            _text(deposit.get("payment_id"), "payment_id")
            if deposit.get("status") not in ("pending", "paid", "failed"):
                raise ValueError("invalid deposit status")
            if deposit.get("mock") is not True:
                raise ValueError("deposit record must be explicitly marked mock")
        except (ValueError, TypeError, KeyError) as exc:
            return self._result(event_id, "needs_input", str(exc), {})

        replies: list[dict[str, Any]] = []
        def outcome(status, message):
            selected = {(event_id, proposal_id, q["quotation_id"]) for q in quotes}
            records = [asdict(b) for key, b in self._bookings.items() if key in selected]
            return self._result(event_id, status, message, {
                "bookings": records, "supplier_replies": deepcopy(replies),
                "customer_payment": deepcopy(deposit),
                "requires_attention": status != "success" and deposit["status"] == "paid",
            })

        for record in [*quotes, approval, budget, deposit]:
            if record["event_id"] != event_id or record["proposal_id"] != proposal_id:
                return outcome("blocked", "Event/proposal mismatch; no new supplier booking request sent.")
        for record in (approval, budget, deposit):
            if record["quotation_fingerprint"] != fingerprint:
                return outcome("blocked", "Quotation snapshot changed; fresh budget, approval and payment review required.")
        if not budget["within_budget"]:
            return outcome("blocked", "Budget has not passed Financial review.")
        if not approval["approved"] or set(approved_ids) != {q["quotation_id"] for q in quotes}:
            return outcome("blocked", "Customer has not approved exactly the selected quotations.")
        if deposit["status"] != "paid" or paid < due:
            return outcome("blocked", "Required simulated deposit has not been paid in full.")
        try:
            self._refresh_bookings()
            if self._record_service is not None:
                # Retry a failed local save before any new supplier call. Never
                # discard a confirmation that was retained in this process.
                for saved in self._bookings.values():
                    self._record_service.save_booking(asdict(saved))
        except ProcurementStorageError:
            return outcome("error", "Cannot load/save confirmed bookings; stop for storage review.")
        for quote in quotes:
            existing = self._bookings.get((event_id, proposal_id, quote["quotation_id"]))
            if existing and existing.source_quotation_fingerprint != quotation_fingerprint([quote]):
                return outcome("blocked", "A confirmed booking already exists for different quotation contents; manual review required.")

        for quote in quotes:
            key = (event_id, proposal_id, quote["quotation_id"])
            if key in self._bookings:
                continue  # Repeat calls never re-send an already confirmed booking.
            try:
                reply = self.supplier_service.request_booking(quote)
            except NoBookingScenarioError:
                replies.append({**quote, "status": "unconfigured", "reason": "No final supplier reply configured.", "mock": True})
                return outcome("blocked", "Final supplier confirmation is missing; paid deposit retained for review.")
            except (ValueError, TypeError, KeyError, OSError, RuntimeError):
                return outcome("error", "Supplier booking call failed; inspect retained bookings and payment.")
            try:
                reply = self._reply(reply, quote)
                if reply["status"] == "confirmed" and any(
                    b.supplier_confirmation_id == reply["supplier_confirmation_id"]
                    for b in self._bookings.values()
                ):
                    raise ValueError("duplicate supplier confirmation ID")
            except (ValueError, TypeError, KeyError):
                return outcome("error", "Invalid/mismatched final supplier reply; inspect retained bookings and payment.")
            replies.append(reply)
            if reply["status"] != "confirmed":
                return outcome("blocked", "Supplier did not confirm booking: " + reply["reason"])
            identity = json.dumps([event_id, proposal_id, quote["quotation_id"], reply["supplier_confirmation_id"]])
            self._bookings[key] = VendorBooking(
                event_id=event_id, proposal_id=proposal_id,
                booking_id="MB-" + sha256(identity.encode()).hexdigest(),
                quotation_id=quote["quotation_id"], vendor_id=quote["vendor_id"], status="Confirmed",
                offering_id=quote["offering_id"], service_type=quote["service_type"], event_date=quote["event_date"],
                guest_count=quote["guest_count"], quoted_total_cents=quote["quoted_total_cents"],
                supplier_confirmation_id=reply["supplier_confirmation_id"],
                source_quotation_fingerprint=quotation_fingerprint([quote]), mock=True,
            )
            if self._record_service is not None:
                try:
                    self._record_service.save_booking(asdict(self._bookings[key]))
                except ProcurementStorageError:
                    return outcome("error", "Supplier confirmed but local save failed. Retain this result for manual review before restarting.")
        return outcome("success", "All selected MOCK bookings confirmed. No payment or refund was performed.")

    @staticmethod
    def _record(raw, name):
        if not isinstance(raw, dict):
            raise ValueError(name + " record is required")
        for field in ("event_id", "proposal_id", "quotation_fingerprint"):
            _text(raw.get(field), name + "." + field)
        return dict(raw)

    @staticmethod
    def _reply(raw, quote):
        if not isinstance(raw, dict) or raw.get("mock") is not True:
            raise ValueError("expected explicitly mock final supplier reply")
        for name, expected in quote.items():
            if type(raw.get(name)) is not type(expected) or raw[name] != expected:
                raise ValueError("final supplier reply mismatch: " + name)
        status = raw.get("status")
        if status not in ("confirmed", "rejected", "pending"):
            raise ValueError("unknown final supplier status")
        for name in ("scenario_id", "reason"):
            _text(raw.get(name), name)
        confirmation = raw.get("supplier_confirmation_id")
        if status == "confirmed":
            _text(confirmation, "supplier_confirmation_id")
        elif confirmation is not None:
            raise ValueError("unconfirmed reply contains a confirmation ID")
        return {**quote, "status": status, "reason": raw["reason"], "scenario_id": raw["scenario_id"],
                "supplier_confirmation_id": confirmation}

    @staticmethod
    def _result(event_id, status, message, data):
        return {"event_id": event_id, "status": status, "message": message, "data": data}
