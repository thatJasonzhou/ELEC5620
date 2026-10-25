"""Supplier enquiry rounds and five-service activity batches (KAN-36).

A supplier simulator submits facts; the Agent only compares accepted replies.
Rounds are process-local and serialized. They are not authenticated vendor sessions.
Only accepted quotation snapshots may optionally be persisted via the existing
ProcurementRecordService. Old quotation and booking paths are unchanged.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

from src.services.procurement_record_service import ProcurementRecordService
from src.services.vendor_procurement_service import VendorProcurementService
from src.shared.schemas import require_int, require_non_empty_str, require_valid_date


class EnquiryConflict(ValueError):
    """Unknown round, wrong context, or an attempted final-reply overwrite."""


class VendorEnquiryService:
    """Own a shortlist and its supplier replies, without LLMs, booking or payment."""

    def __init__(self, vendors: VendorProcurementService, *,
                 record_service: ProcurementRecordService | None = None) -> None:
        self._vendors = vendors
        self._records = record_service
        self._rounds: dict[str, dict[str, Any]] = {}
        self._batches: dict[str, dict[str, Any]] = {}

    @staticmethod
    def validate_request(request: Any) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise ValueError("request must be an object")
        result = {n: require_non_empty_str(request.get(n), n) for n in
                  ("event_id", "proposal_id", "service_type", "location")}
        result["event_date"] = require_valid_date(request.get("event_date"), "event_date")
        result["guest_count"] = require_int(request.get("guest_count"), "guest_count", minimum=0)
        prefs = request.get("customer_preferences", "")
        if not isinstance(prefs, str):
            raise ValueError("customer_preferences must be text")
        result["customer_preferences"] = prefs
        budget = request.get("service_budget_cents")
        if budget is not None:
            budget = require_int(budget, "service_budget_cents", minimum=0)
        hard = request.get("budget_is_hard_limit", False)
        if type(hard) is not bool or (hard and budget is None):
            raise ValueError("budget_is_hard_limit must be boolean and requires service_budget_cents when true")
        result.update(service_budget_cents=budget, budget_is_hard_limit=hard)
        # Base Agent validation handles the optional rating scale.
        result["min_rating"] = request.get("min_rating")
        return result

    def create_round(self, context: dict[str, Any],
                     recommendations: list[dict[str, Any]]) -> dict[str, Any]:
        self.validate_service_slot(context)
        candidates = self._vendors.filter_vendors(
            service_type=context["service_type"], date=context["event_date"],
            guest_count=context["guest_count"], location=context["location"])
        if context["min_rating"] is not None:
            candidates = [c for c in candidates if c["rating"] >= context["min_rating"]]
        by_pair = {(c["vendor_id"], c["offering_id"]): c for c in candidates}
        if len(recommendations) != min(3, len(candidates)) or not recommendations:
            raise ValueError("shortlist must contain exactly the first up-to-three recommendations")
        pairs = [(r["vendor_id"], r["offering_id"]) for r in recommendations]
        if len(set(pairs)) != len(pairs) or any(p not in by_pair for p in pairs):
            raise ValueError("invalid shortlist")
        round_id = "ER-" + uuid4().hex
        enquiries = []
        for rank, pair in enumerate(pairs, 1):
            candidate = by_pair[pair]
            enquiry_id = "ENQ-" + uuid4().hex
            enquiries.append({
                "enquiry_id": enquiry_id, "initial_rank": rank,
                "candidate": deepcopy(candidate),
                "reply": {
                    **{n: context[n] for n in ("event_id", "proposal_id", "event_date", "guest_count")},
                    "vendor_id": pair[0], "offering_id": pair[1],
                    "quotation_id": "MIQ-" + enquiry_id[4:],
                    "scenario_id": "MOCK-ROUND-" + round_id[3:],
                    "mock": True, "status": "pending", "available": None,
                    "quoted_total_cents": None, "reason": "MOCK: supplier has not replied.",
                },
            })
        self._rounds[round_id] = {"round_id": round_id, "context": deepcopy(context),
                                  "enquiries": enquiries, "recommendations": deepcopy(recommendations)}
        return self.get_round(context["event_id"], context["proposal_id"], round_id)

    def _get(self, event_id: str, proposal_id: str, round_id: str) -> dict[str, Any]:
        for name, value in (("event_id", event_id), ("proposal_id", proposal_id), ("round_id", round_id)):
            require_non_empty_str(value, name)
        current = self._rounds.get(round_id)
        if current is None:
            raise EnquiryConflict("Unknown enquiry round; process-local enquiry rounds do not survive restart.")
        if any(current["context"][n] != value for n, value in
               (("event_id", event_id), ("proposal_id", proposal_id))):
            raise EnquiryConflict("Event/proposal does not match the stored enquiry.")
        return current

    def get_round(self, event_id: str, proposal_id: str, round_id: str) -> dict[str, Any]:
        current = deepcopy(self._get(event_id, proposal_id, round_id))
        current["supplier_replies"] = [deepcopy(e["reply"]) for e in current["enquiries"]]
        current["quotations"] = [self._quotation(e) for e in current["enquiries"]
                                 if e["reply"]["status"] == "accepted"]
        current["awaiting_replies"] = any(r["status"] == "pending" for r in current["supplier_replies"])
        return current

    @staticmethod
    def _quotation(enquiry: dict[str, Any]) -> dict[str, Any]:
        reply, candidate = enquiry["reply"], enquiry["candidate"]
        return {**deepcopy(reply), "service_type": candidate["service_type"],
                "recommendation_reason":
                    "MOCK supplier-submitted quotation; not a comparative recommendation or booking."}

    def submit_reply(self, request: Any) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise ValueError("request must be an object")
        current = self._get(request.get("event_id"), request.get("proposal_id"), request.get("round_id"))
        enquiry_id = require_non_empty_str(request.get("enquiry_id"), "enquiry_id")
        enquiry = next((e for e in current["enquiries"] if e["enquiry_id"] == enquiry_id), None)
        if enquiry is None:
            raise EnquiryConflict("Enquiry does not belong to this shortlist.")
        if request.get("mock") is not True:
            raise ValueError("Supplier input must explicitly declare mock=true.")
        # The simulator may echo facts, but cannot alter the original enquiry.
        for field in ("vendor_id", "offering_id", "event_date", "guest_count", "quotation_id", "scenario_id"):
            if field in request and (type(request[field]) is not type(enquiry["reply"][field])
                                     or request[field] != enquiry["reply"][field]):
                raise EnquiryConflict("Reply does not match stored " + field)
        status = request.get("status")
        if status not in ("accepted", "rejected", "pending"):
            raise ValueError("status must be accepted, rejected or pending")
        reason = require_non_empty_str(request.get("reason"), "reason")
        amount = request.get("quoted_total_cents")
        if status == "accepted":
            amount = require_int(amount, "quoted_total_cents", minimum=0)
        elif amount is not None:
            raise ValueError("Pending/rejected replies must not carry an accepted price.")
        available = {"accepted": True, "rejected": False, "pending": None}[status]
        if "available" in request and request["available"] is not available:
            raise ValueError("available contradicts status")
        reply = {**enquiry["reply"], "status": status, "available": available,
                 "quoted_total_cents": amount, "reason": reason}
        if enquiry["reply"]["status"] != "pending" and reply != enquiry["reply"]:
            raise EnquiryConflict("Final reply is immutable; changed quotes require a new enquiry round and review.")
        updated = {**enquiry, "reply": reply}
        if status == "accepted" and self._records is not None:
            self._records.save_quotations([self._quotation(updated)])
        enquiry["reply"] = reply
        return deepcopy(reply)

    def comparison(self, event_id: str, proposal_id: str, round_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        current = self.get_round(event_id, proposal_id, round_id)
        context = current["context"]
        budget = context["service_budget_cents"]
        candidates = []
        for enquiry in current["enquiries"]:
            reply = enquiry["reply"]
            if reply["status"] != "accepted":
                continue
            if context["budget_is_hard_limit"] and reply["quoted_total_cents"] > budget:
                continue
            candidates.append({
                **enquiry["candidate"], "quotation_id": reply["quotation_id"],
                "catalog_estimate_cents": enquiry["candidate"]["total_price_cents"],
                "total_price_cents": reply["quoted_total_cents"],
                "supplier_reason": reply["reason"],
                "over_target_cents": max(0, reply["quoted_total_cents"] - budget) if budget is not None else None,
            })
        return current, candidates

    @staticmethod
    def validate_event_request(request: Any) -> list[dict[str, Any]]:
        """Validate the complete service list before any model or supplier call."""
        if not isinstance(request, dict):
            raise ValueError("request must be an object")
        for field in ("event_id", "proposal_id"):
            require_non_empty_str(request.get(field), field)
        services = request.get("services")
        if not isinstance(services, list) or not 1 <= len(services) <= 5:
            raise ValueError("An activity requires 1-5 service items; none are silently truncated.")
        contexts = []
        seen_types: set[str] = set()
        for item in services:
            if not isinstance(item, dict):
                raise ValueError("Each service item must be an object")
            for field in ("event_id", "proposal_id"):
                if field in item and item[field] != request[field]:
                    raise ValueError("Service item cannot override " + field)
            context = VendorEnquiryService.validate_request({**request, **item})
            service_type = context["service_type"].strip().lower()
            if service_type in seen_types:
                raise ValueError("Use one service item per category; duplicate service_type: " + service_type)
            seen_types.add(service_type)
            contexts.append(context)
        return contexts

    def validate_service_slot(self, context: dict[str, Any]) -> None:
        """Re-enquiries reuse a slot; a sixth category in this proposal is blocked."""
        self.validate_service_slots([context])

    def validate_service_slots(self, contexts: list[dict[str, Any]]) -> None:
        """Check proposed categories together, including already prepared rounds."""
        if not contexts:
            raise ValueError("At least one service context is required.")
        context = contexts[0]
        if any(c["event_id"] != context["event_id"] or c["proposal_id"] != context["proposal_id"]
               for c in contexts):
            raise ValueError("Service contexts must belong to the same event and proposal.")
        types = {r["context"]["service_type"].strip().lower() for r in self._rounds.values()
                 if r["context"]["event_id"] == context["event_id"]
                 and r["context"]["proposal_id"] == context["proposal_id"]}
        types.update(c["service_type"].strip().lower() for c in contexts)
        if len(types) > 5:
            raise ValueError("An activity proposal supports at most five service categories.")

    def create_batch(self, event_id: str, proposal_id: str, round_ids: list[str]) -> dict[str, Any]:
        if not 1 <= len(round_ids) <= 5 or len(set(round_ids)) != len(round_ids):
            raise ValueError("A batch requires 1-5 distinct service rounds.")
        rounds = [self._get(event_id, proposal_id, r) for r in round_ids]
        types = [r["context"]["service_type"].strip().lower() for r in rounds]
        if len(set(types)) != len(types):
            raise ValueError("A batch may not repeat a service category.")
        batch_id = "EB-" + uuid4().hex
        self._batches[batch_id] = {
            "event_id": event_id, "proposal_id": proposal_id, "batch_id": batch_id,
            "required_services": [r["context"]["service_type"] for r in rounds],
            "round_ids": list(round_ids),
        }
        return self.get_batch(event_id, proposal_id, batch_id)

    def get_batch(self, event_id: str, proposal_id: str, batch_id: str) -> dict[str, Any]:
        for name, value in (("event_id", event_id), ("proposal_id", proposal_id), ("batch_id", batch_id)):
            require_non_empty_str(value, name)
        batch = self._batches.get(batch_id)
        if batch is None or batch["event_id"] != event_id or batch["proposal_id"] != proposal_id:
            raise EnquiryConflict("Unknown batch or mismatched event/proposal.")
        result = deepcopy(batch)
        result["service_rounds"] = [self.get_round(event_id, proposal_id, r) for r in batch["round_ids"]]
        # Empty until ALL required services have a valid comparison.
        result.update(quotations=[], selected_quotations=[], selected_quotation_ids=[],
                      selection_complete=False)
        return result
