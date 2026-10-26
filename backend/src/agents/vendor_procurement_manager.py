"""Vendor Procurement Manager Agent — recommendation stage (KAN-16).

Pipeline for one ``handle(request)`` call:

1. Validate required inputs (failures -> ``needs_input``).
2. Reuse ``VendorProcurementService.filter_vendors`` (KAN-15) to get
   deterministic candidates. The service's ``date`` argument is mapped
   from the request's ``event_date``; the KAN-15 interface is unchanged.
3. Apply the optional code-side ``min_rating`` filter (catalog rating
   scale is 0-5).
4. If no candidates remain -> ``blocked``, no LLM call.
5. Ask the LLM (via the centralized ``src/llm`` package) to compare the
   qualified candidates against the optional ``customer_preferences``
   text (soft comparison only) and return strict JSON with verifiable
   basis codes.
6. Validate the LLM output (strict JSON, field types, ID pairing,
   uniqueness, count, basis codes checked against real candidate
   facts). Any failure -> ``error``; never a fake success.
7. Backfill every fact field from the filtered candidates and return
   ``data.recommendations`` (1-3 items).

Scope notes:

- This is a *recommendation* stage. The later quotation stage uses the
  ``data.quotations`` structure defined in
  shared-data-and-interfaces.md; request_quotations implements mock enquiries separately.
- Prices come from the fictional catalog and are whole-event estimates.
  They are never treated as confirmed quotations.
- Separate confirm_bookings delegates simulated booking to a Service.
- Optional persistence is delegated to Services; no direct SQL or payment processing.
"""
from __future__ import annotations

import json
from typing import Any

from src.agents.base import AIAgent
from src.llm import LLMClient, LLMError
from src.services.procurement_record_service import (
    ProcurementRecordService,
    ProcurementStorageError,
)
from src.services.vendor_booking_service import VendorBookingService
from src.services.vendor_procurement_service import VendorProcurementService
from src.services.vendor_quotation_service import (
    MockVendorQuotationService,
    NoQuotationScenarioError,
)
from src.shared.schemas import (
    require_int,
    require_non_empty_str,
    require_number,
    require_valid_date,
)

#: Closed set of basis codes the model may cite for a recommendation.
ALLOWED_BASIS_CODES = (
    "lowest_price",
    "highest_rating",
    "highest_capacity",
    "within_budget",
)

#: Output limits for ``data.recommendations``.
MIN_RECOMMENDATIONS = 1
MAX_RECOMMENDATIONS = 3

_SYSTEM_PROMPT = (
    "You are the Vendor Procurement Manager for a one-person AI event "
    "management company. You compare candidate vendors that have already "
    "passed deterministic code-side filtering (service type, event date, "
    "guest capacity, service location, and optionally a minimum rating). "
    "You never invent vendors, prices, ratings or availability; you only "
    "choose from the candidates provided and explain the trade-offs."
)

_USER_PROMPT_TEMPLATE = """Recommend the best vendors from the candidates below.

Event:
- service_type: {service_type}
- event_date: {event_date}
- guest_count: {guest_count}
- location: {location}
- min_rating (already applied by code): {min_rating}
- target_vendor_budget_cents: {target_vendor_budget_cents}

Customer preferences (SOFT guidance only. Use them to compare candidates.
Do NOT treat them as hard filters, do NOT promise anything that is not in
the candidate facts, and do NOT add vendors):
{customer_preferences}

Candidates (facts, already verified by code):
{candidates_json}

Respond with STRICT JSON only — no markdown fences, no commentary.
Shape:
{{"recommendations": [{{"vendor_id": str, "offering_id": str, "basis_codes": [str], "reason": str}}]}}

Rules:
- Return {min_count} to {max_count} recommendations, chosen ONLY from the candidates.
- Order matters: the first item is rank 1 (your top pick).
- Prefer candidates within target_vendor_budget_cents. If none are within the target, prefer the closest available price and clearly explain that it is over budget.
- (vendor_id, offering_id) pairs must come from the candidates and must not repeat.
- "basis_codes" is a list drawn ONLY from: {basis_codes}.
  A basis code may be listed for a recommendation only if it is factually
  true for that candidate relative to ALL other candidates
  (e.g. "lowest_price" only if its total_price_cents is the minimum).
  An empty list is allowed when no superlative applies.
- "reason" is 1-2 sentences of plain text explaining why this candidate
  fits the event and preferences.
"""


class VendorProcurementManagerAgent(AIAgent):
    """Recommends vendors (1-3) for one service type of one event."""

    agent_name = "procurement"

    def __init__(
        self,
        llm: LLMClient,
        vendor_service: VendorProcurementService,
        quotation_service: MockVendorQuotationService | None = None,
        booking_service: VendorBookingService | None = None,
        *,
        record_service: ProcurementRecordService | None = None,
    ) -> None:
        super().__init__(llm)
        if not isinstance(vendor_service, VendorProcurementService):
            raise TypeError(
                "vendor_service must be a VendorProcurementService instance"
            )
        self._vendor_service = vendor_service
        if quotation_service is not None and not isinstance(quotation_service, MockVendorQuotationService):
            raise TypeError("quotation_service must be a MockVendorQuotationService instance")
        self._quotation_service = quotation_service
        if booking_service is not None and not isinstance(booking_service, VendorBookingService):
            raise TypeError("booking_service must be a VendorBookingService instance")
        self._booking_service = booking_service
        if record_service is not None and not isinstance(record_service, ProcurementRecordService):
            raise TypeError("record_service must be a ProcurementRecordService instance")
        self._record_service = record_service

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict):
            return self.envelope(
                None,
                "error",
                f"request must be a dict, got {type(request).__name__}",
            )

        event_id, params, errors = self._validate_request(request)
        if errors:
            return self.envelope(
                event_id,
                "needs_input",
                "Missing or invalid input fields: "
                + "; ".join(f"{name}: {problem}" for name, problem in errors),
            )

        try:
            candidates = self._vendor_service.filter_vendors(
                service_type=params["service_type"],
                date=params["event_date"],
                guest_count=params["guest_count"],
                location=params["location"],
            )
        except ValueError as exc:
            # Defensive: inputs were validated above with the same rules.
            return self.envelope(
                event_id, "error", f"vendor filtering failed: {exc}"
            )

        if params["min_rating"] is not None:
            candidates = [
                c
                for c in candidates
                if c["rating"] >= params["min_rating"]
            ]

        target_budget = params["target_vendor_budget_cents"]
        for candidate in candidates:
            candidate["within_target_budget"] = (
                target_budget is None
                or candidate["total_price_cents"] <= target_budget
            )
            candidate["budget_gap_cents"] = (
                0
                if target_budget is None
                else candidate["total_price_cents"] - target_budget
            )

        if not candidates:
            return self.envelope(
                event_id,
                "blocked",
                "No vendor candidates match the request"
                + (
                    f" (including min_rating={params['min_rating']})"
                    if params["min_rating"] is not None
                    else ""
                )
                + ". No LLM call was made.",
            )

        messages = self._build_messages(params, candidates)
        try:
            raw = self.llm.complete(messages)
        except LLMError as exc:
            return self.envelope(event_id, "error", f"LLM call failed: {exc}")

        recommendations, problem = self._validate_recommendations(
            raw, candidates
        )
        if problem is not None:
            return self.envelope(
                event_id, "error", f"LLM output validation failed: {problem}"
            )

        top = recommendations[0]
        message = (
            f"Returned {len(recommendations)} of {len(candidates)} "
            f"candidate(s) for {top['service_type']} in "
            f"{top['service_location']} on {top['event_date']}. Top pick: "
            f"{top['vendor_name']} ({top['vendor_id']}) — whole-event "
            f"price AUD {top['total_price_cents'] / 100:,.2f}, rating "
            f"{top['rating']}, capacity {top['guest_capacity']} guests. "
            "Catalog prices are estimates, not confirmed quotations. "
            "Recommendation reasons are AI-generated and not fully "
            "fact-verified."
        )
        return self.envelope(
            event_id, "success", message, {"recommendations": recommendations}
        )

    def deterministic_fallback(self, request: dict[str, Any]) -> dict[str, Any]:
        """Rank verified candidates when an optional LLM comparison fails.

        This method never creates vendor facts. It reuses the catalogue filter
        and its stable price/rating/capacity ordering so the application can
        continue safely after malformed model output.
        """
        if not isinstance(request, dict):
            return self.envelope(None, "error", "request must be a dict")
        event_id, params, errors = self._validate_request(request)
        if errors:
            return self.envelope(
                event_id,
                "needs_input",
                "Missing or invalid input fields: "
                + "; ".join(f"{name}: {problem}" for name, problem in errors),
            )
        try:
            candidates = self._vendor_service.filter_vendors(
                service_type=params["service_type"],
                date=params["event_date"],
                guest_count=params["guest_count"],
                location=params["location"],
            )
        except (ValueError, TypeError, KeyError, OSError, RuntimeError):
            return self.envelope(event_id, "error", "Vendor filtering failed.")
        if params["min_rating"] is not None:
            candidates = [
                item for item in candidates
                if item["rating"] >= params["min_rating"]
            ]
        if not candidates:
            return self.envelope(
                event_id, "blocked", "No vendor candidates match the request."
            )
        target = params["target_vendor_budget_cents"]
        min_price = min(item["total_price_cents"] for item in candidates)
        max_rating = max(item["rating"] for item in candidates)
        max_capacity = max(item["guest_capacity"] for item in candidates)
        recommendations = []
        for rank, candidate in enumerate(candidates[:MAX_RECOMMENDATIONS], start=1):
            basis_codes = []
            if candidate["total_price_cents"] == min_price:
                basis_codes.append("lowest_price")
            if candidate["rating"] == max_rating:
                basis_codes.append("highest_rating")
            if candidate["guest_capacity"] == max_capacity:
                basis_codes.append("highest_capacity")
            if target is None or candidate["total_price_cents"] <= target:
                basis_codes.append("within_budget")
            recommendations.append(
                {
                    "vendor_id": candidate["vendor_id"],
                    "offering_id": candidate["offering_id"],
                    "vendor_name": candidate["vendor_name"],
                    "service_type": candidate["service_type"],
                    "service_location": candidate["service_location"],
                    "guest_capacity": candidate["guest_capacity"],
                    "rating": candidate["rating"],
                    "total_price_cents": candidate["total_price_cents"],
                    "event_date": candidate["date"],
                    "basis_codes": basis_codes,
                    "recommendation_reason": (
                        "Verified catalogue match, ordered by estimated price "
                        "with rating and capacity used as tie-breakers."
                    ),
                    "rank": rank,
                }
            )
        return self.envelope(
            event_id,
            "success",
            "The AI comparison was unavailable, so verified catalogue "
            "candidates were ranked using deterministic business rules.",
            {"recommendations": recommendations, "fallback_used": True},
        )

    def request_quotations(self, request: dict[str, Any]) -> dict[str, Any]:
        """Collect confirmed mock quotes; never book, pay, or call the LLM.

        This separate entry point leaves ``handle`` recommendations unchanged.
        Financial handoff requires a concrete event and proposal identifier.
        """
        if not isinstance(request, dict):
            return self.envelope(None, "error", "request must be a dict")
        event_id, params, errors = self._validate_request(request)
        try:
            proposal_id = require_non_empty_str(request.get("proposal_id"), "proposal_id")
        except ValueError as exc:
            errors.append(("proposal_id", str(exc)))
            proposal_id = None
        if errors:
            return self.envelope(event_id, "needs_input", "Missing or invalid input fields: "
                                 + "; ".join(f"{name}: {problem}" for name, problem in errors))
        if self._quotation_service is None:
            return self.envelope(event_id, "error", "No quotation_service is configured.")

        try:
            candidates = self._vendor_service.filter_vendors(
                service_type=params["service_type"], date=params["event_date"],
                guest_count=params["guest_count"], location=params["location"],
            )
            if params["min_rating"] is not None:
                candidates = [c for c in candidates if c["rating"] >= params["min_rating"]]
        except (ValueError, TypeError, KeyError, OSError, RuntimeError):
            return self.envelope(event_id, "error", "Vendor filtering failed during quotation enquiry.")

        quotations: list[dict[str, Any]] = []
        replies: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for candidate in candidates:
            enquiry = {
                "event_id": event_id, "proposal_id": proposal_id,
                "vendor_id": candidate["vendor_id"], "offering_id": candidate["offering_id"],
                "event_date": params["event_date"], "guest_count": params["guest_count"],
            }
            try:
                raw_reply = self._quotation_service.request_quotation(**enquiry)
            except NoQuotationScenarioError:
                replies.append({**enquiry, "mock": True, "status": "unconfigured",
                                "available": None, "quoted_total_cents": None,
                                "reason": "No mock reply configured; supplier has not confirmed."})
                continue
            except (ValueError, TypeError, KeyError, OSError, RuntimeError):
                return self.envelope(event_id, "error", "Supplier enquiry failed; no quotations released.")
            try:
                reply = self._validate_quotation_reply(raw_reply, enquiry)
                if reply["quotation_id"] in seen_ids:
                    raise ValueError("duplicate quotation_id")
                seen_ids.add(reply["quotation_id"])
            except (ValueError, TypeError, KeyError):
                return self.envelope(event_id, "error", "Invalid or mismatched supplier reply; no quotations released.")
            replies.append(reply)
            if reply["status"] != "accepted":
                continue
            cents = reply["quoted_total_cents"]
            quotations.append({
                **enquiry, "quotation_id": reply["quotation_id"],
                "service_type": candidate["service_type"], "quoted_total_cents": cents,
                "available": True, "mock": True, "scenario_id": reply["scenario_id"],
                "recommendation_reason": (
                    f"MOCK supplier confirmed {candidate['service_type']} in "
                    f"{candidate['service_location']} on {params['event_date']} for "
                    f"{params['guest_count']} guests at AUD {cents // 100:,}.{cents % 100:02d}. "
                    "This price comes from the supplier reply, not the catalogue estimate. "
                    "No comparative ranking is claimed; this is not a booking."
                ),
            })
        data = {"quotations": quotations, "supplier_replies": replies}
        if not quotations:
            reasons = "; ".join(f"{r['vendor_id']}/{r['offering_id']}: {r['reason']}" for r in replies)
            return self.envelope(event_id, "blocked", "No confirmed supplier quotations. "
                                 + (reasons or "No candidates match the request."), data)
        quotations.sort(key=lambda q: (q["quoted_total_cents"], q["vendor_id"], q["offering_id"]))
        if self._record_service is not None:
            try:
                self._record_service.save_quotations(quotations)
            except (ProcurementStorageError, ValueError, TypeError):
                return self.envelope(event_id, "error", "Cannot save confirmed quotations; review storage or proposal conflicts.")
        return self.envelope(event_id, "success", f"Returned {len(quotations)} confirmed MOCK quotation(s). "
                             "Other replies may remain pending or declined. No booking or payment was made.", data)

    def compare_received_quotations(
        self, request: dict[str, Any]
    ) -> dict[str, Any]:
        """Re-rank supplier-entered quotes for one service.

        This is the second procurement decision.  The first decision shortlists
        catalogue candidates; this one uses the prices suppliers actually
        entered in the simulated portal.  The returned top quotation is only a
        recommendation: customer approval, payment and booking remain separate
        workflow gates.
        """
        if not isinstance(request, dict):
            return self.envelope(None, "needs_input", "request must be a dict")

        event_id, params, errors = self._validate_request(request)
        try:
            proposal_id = require_non_empty_str(
                request.get("proposal_id"), "proposal_id"
            )
            service_budget_cents = require_int(
                request.get("service_budget_cents"),
                "service_budget_cents",
                minimum=0,
            )
        except ValueError as exc:
            errors.append(("quotation_context", str(exc)))
            proposal_id = None
            service_budget_cents = None
        raw_quotations = request.get("quotations")
        if not isinstance(raw_quotations, list) or not 1 <= len(raw_quotations) <= 3:
            errors.append(
                ("quotations", "must contain 1-3 accepted supplier quotations")
            )
            raw_quotations = []
        if errors:
            return self.envelope(
                event_id,
                "needs_input",
                "Missing or invalid input fields: "
                + "; ".join(f"{name}: {problem}" for name, problem in errors),
            )

        candidates: list[dict[str, Any]] = []
        source_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
        quotation_ids: set[str] = set()
        try:
            for index, quotation in enumerate(raw_quotations):
                if not isinstance(quotation, dict):
                    raise TypeError(f"quotations[{index}] must be an object")
                quotation_id = require_non_empty_str(
                    quotation.get("quotation_id"),
                    f"quotations[{index}].quotation_id",
                )
                vendor_id = require_non_empty_str(
                    quotation.get("vendor_id"), f"quotations[{index}].vendor_id"
                )
                offering_id = require_non_empty_str(
                    quotation.get("offering_id"),
                    f"quotations[{index}].offering_id",
                )
                service_type = require_non_empty_str(
                    quotation.get("service_type"),
                    f"quotations[{index}].service_type",
                )
                if service_type != params["service_type"]:
                    raise ValueError("quotation service_type does not match the comparison")
                if quotation.get("available") is not True:
                    raise ValueError("only accepted and available quotations may be compared")
                quoted_total_cents = require_int(
                    quotation.get("quoted_total_cents"),
                    f"quotations[{index}].quoted_total_cents",
                    minimum=1,
                )
                vendor_name = require_non_empty_str(
                    quotation.get("vendor_name"),
                    f"quotations[{index}].vendor_name",
                )
                service_location = require_non_empty_str(
                    quotation.get("service_location"),
                    f"quotations[{index}].service_location",
                )
                guest_capacity = require_int(
                    quotation.get("guest_capacity"),
                    f"quotations[{index}].guest_capacity",
                    minimum=params["guest_count"],
                )
                rating = require_number(
                    quotation.get("rating"), f"quotations[{index}].rating"
                )
                if not 0 <= rating <= 5:
                    raise ValueError("quotation rating must use the 0-5 scale")
                catalogue_estimate_cents = require_int(
                    quotation.get("catalogue_estimate_cents"),
                    f"quotations[{index}].catalogue_estimate_cents",
                    minimum=0,
                )
                pair = (vendor_id, offering_id)
                if pair in source_by_pair or quotation_id in quotation_ids:
                    raise ValueError("duplicate supplier quotation")
                quotation_ids.add(quotation_id)
                source_by_pair[pair] = dict(quotation)
                candidates.append(
                    {
                        "vendor_id": vendor_id,
                        "offering_id": offering_id,
                        "vendor_name": vendor_name,
                        "service_type": service_type,
                        "service_location": service_location,
                        "guest_capacity": guest_capacity,
                        "rating": rating,
                        # For this second comparison, price always means the
                        # supplier-entered amount, not the catalogue estimate.
                        "total_price_cents": quoted_total_cents,
                        "catalogue_estimate_cents": catalogue_estimate_cents,
                        "date": params["event_date"],
                        "within_target_budget": (
                            quoted_total_cents <= service_budget_cents
                        ),
                        "budget_gap_cents": (
                            quoted_total_cents - service_budget_cents
                        ),
                    }
                )
        except (ValueError, TypeError, KeyError) as exc:
            return self.envelope(event_id, "needs_input", str(exc))

        comparison_params = {
            **params,
            "target_vendor_budget_cents": service_budget_cents,
        }
        messages = self._build_messages(comparison_params, candidates)
        messages[0]["content"] += (
            " This is the final quotation comparison: total_price_cents is the "
            "supplier-entered quote and catalogue_estimate_cents is reference "
            "data only. The first result is a proposal, not an approval or booking."
        )
        messages[-1]["content"] += (
            f"\nReturn all {len(candidates)} supplied candidates, ranked once each. "
            "Do not omit an over-target quote unless code has already excluded it."
        )

        fallback_used = False
        try:
            raw = self.llm.complete(messages)
            recommendations, problem = self._validate_recommendations(
                raw, candidates
            )
        except LLMError as exc:
            recommendations, problem = [], f"LLM call failed: {exc}"
        if problem is not None or len(recommendations) != len(candidates):
            # A malformed model response must never update business state.
            # The verified facts can still be ranked by deterministic rules.
            fallback_used = True
            ordered = sorted(
                candidates,
                key=lambda item: (
                    not item["within_target_budget"],
                    abs(item["budget_gap_cents"]),
                    -item["rating"],
                    item["total_price_cents"],
                    item["vendor_id"],
                ),
            )
            minimum_price = min(item["total_price_cents"] for item in candidates)
            maximum_rating = max(item["rating"] for item in candidates)
            maximum_capacity = max(item["guest_capacity"] for item in candidates)
            recommendations = []
            for rank, candidate in enumerate(ordered, start=1):
                basis_codes = []
                if candidate["total_price_cents"] == minimum_price:
                    basis_codes.append("lowest_price")
                if candidate["rating"] == maximum_rating:
                    basis_codes.append("highest_rating")
                if candidate["guest_capacity"] == maximum_capacity:
                    basis_codes.append("highest_capacity")
                if candidate["within_target_budget"]:
                    basis_codes.append("within_budget")
                recommendations.append(
                    {
                        **candidate,
                        "rank": rank,
                        "basis_codes": basis_codes,
                        "recommendation_reason": (
                            "Ranked from verified supplier price, service budget, "
                            "catalogue rating and capacity facts."
                        ),
                    }
                )

        ranking = []
        for recommendation in recommendations:
            pair = (
                recommendation["vendor_id"],
                recommendation["offering_id"],
            )
            source = source_by_pair[pair]
            ranking.append(
                {
                    **source,
                    "rank": recommendation["rank"],
                    "basis_codes": recommendation["basis_codes"],
                    "recommendation_reason": recommendation[
                        "recommendation_reason"
                    ],
                    "within_service_budget": (
                        source["quoted_total_cents"] <= service_budget_cents
                    ),
                    "recommended": recommendation["rank"] == 1,
                }
            )
        ranking.sort(key=lambda item: item["rank"])
        selected_id = ranking[0]["quotation_id"]
        return self.envelope(
            event_id,
            "success",
            "Supplier quotations were compared using their submitted prices. "
            "The top option is a recommendation and still needs customer confirmation.",
            {
                "proposal_id": proposal_id,
                "service_type": params["service_type"],
                "service_budget_cents": service_budget_cents,
                "quotation_ranking": ranking,
                "recommended_quotation_id": selected_id,
                "selection_complete": True,
                "fallback_used": fallback_used,
            },
        )

    @staticmethod
    def _validate_quotation_reply(raw: Any, enquiry: dict[str, Any]) -> dict[str, Any]:
        """Check supplier facts before allowing any Financial handoff."""
        if not isinstance(raw, dict) or raw.get("mock") is not True:
            raise ValueError("expected an explicitly marked mock supplier reply")
        for field, expected in enquiry.items():
            actual = raw.get(field)
            if type(actual) is not type(expected) or actual != expected:
                raise ValueError(f"supplier reply does not match {field}")
        status = raw.get("status")
        if status not in ("accepted", "rejected", "pending"):
            raise ValueError("unknown supplier reply status")
        expected_available = {"accepted": True, "rejected": False, "pending": None}[status]
        if raw.get("available") is not expected_available:
            raise ValueError("supplier reply availability contradicts status")
        quotation_id = require_non_empty_str(raw.get("quotation_id"), "quotation_id")
        scenario_id = require_non_empty_str(raw.get("scenario_id"), "scenario_id")
        reason = require_non_empty_str(raw.get("reason"), "reason")
        cents = raw.get("quoted_total_cents")
        if status == "accepted":
            cents = require_int(cents, "quoted_total_cents", minimum=0)
        elif cents is not None:
            raise ValueError("unconfirmed supplier reply must not carry an accepted price")
        return {**enquiry, "mock": True, "quotation_id": quotation_id,
                "scenario_id": scenario_id, "status": status, "available": expected_available,
                "quoted_total_cents": cents, "reason": reason}


    def confirm_bookings(self, request: dict[str, Any]) -> dict[str, Any]:
        """Delegate booking gates and domain records to the booking Service."""
        if not isinstance(request, dict):
            return self.envelope(None, "error", "request must be a dict")
        event_id = request.get("event_id")
        if not isinstance(event_id, str) or not event_id.strip():
            event_id = None
        if self._booking_service is None:
            return self.envelope(event_id, "error", "No booking_service is configured.")
        result = self._booking_service.confirm_bookings(request)
        return self.envelope(result["event_id"], result["status"], result["message"], result["data"])

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------
    def _validate_request(
        self, request: dict[str, Any]
    ) -> tuple[str | None, dict[str, Any], list[tuple[str, str]]]:
        """Return (event_id, parsed params, per-field error list)."""
        event_id: str | None = None
        params: dict[str, Any] = {}
        errors: list[tuple[str, str]] = []

        def check(field_name: str, value: Any, validator: Any) -> Any:
            try:
                return validator(value, field_name)
            except ValueError as exc:
                errors.append((field_name, str(exc)))
                return None

        non_empty = require_non_empty_str
        event_id = check("event_id", request.get("event_id"), non_empty)
        params["service_type"] = check(
            "service_type", request.get("service_type"), non_empty
        )
        params["event_date"] = check(
            "event_date", request.get("event_date"), require_valid_date
        )
        params["guest_count"] = check(
            "guest_count", request.get("guest_count"),
            lambda v, n: require_int(v, n, minimum=0),
        )
        params["location"] = check("location", request.get("location"), non_empty)

        # Optional soft-preference text (default "").
        if "customer_preferences" in request:
            prefs = request["customer_preferences"]
            if not isinstance(prefs, str):
                errors.append(
                    (
                        "customer_preferences",
                        f"must be a string, got {type(prefs).__name__}",
                    )
                )
                params["customer_preferences"] = ""
            else:
                params["customer_preferences"] = prefs
        else:
            params["customer_preferences"] = ""

        # Optional code-side rating floor, on the catalog 0-5 scale.
        min_rating: float | None = None
        if "min_rating" in request and request["min_rating"] is not None:
            try:
                min_rating = require_number(
                    request["min_rating"], "min_rating"
                )
            except ValueError as exc:
                errors.append(("min_rating", str(exc)))
            else:
                if not 0 <= min_rating <= 5:
                    errors.append(
                        (
                            "min_rating",
                            (
                                f"must be within the 0-5 rating scale, "
                                f"got {min_rating}"
                            ),
                        )
                    )
                    min_rating = None
        params["min_rating"] = min_rating

        target_vendor_budget: int | None = None
        if (
            "target_vendor_budget_cents" in request
            and request["target_vendor_budget_cents"] is not None
        ):
            try:
                target_vendor_budget = require_int(
                    request["target_vendor_budget_cents"],
                    "target_vendor_budget_cents",
                    minimum=1,
                )
            except ValueError as exc:
                errors.append(("target_vendor_budget_cents", str(exc)))
        params["target_vendor_budget_cents"] = target_vendor_budget

        return event_id, params, errors

    # ------------------------------------------------------------------
    # Prompt building (business content stays here; transport/retry in
    # src/llm)
    # ------------------------------------------------------------------
    def _build_messages(
        self, params: dict[str, Any], candidates: list[dict[str, Any]]
    ) -> list[dict[str, str]]:
        candidate_facts = [
            {
                "vendor_id": c["vendor_id"],
                "offering_id": c["offering_id"],
                "vendor_name": c["vendor_name"],
                "service_type": c["service_type"],
                "service_location": c["service_location"],
                "guest_capacity": c["guest_capacity"],
                "rating": c["rating"],
                "total_price_cents": c["total_price_cents"],
                **(
                    {
                        "catalogue_estimate_cents": c[
                            "catalogue_estimate_cents"
                        ]
                    }
                    if "catalogue_estimate_cents" in c
                    else {}
                ),
                "within_target_budget": c.get("within_target_budget", True),
                "budget_gap_cents": c.get("budget_gap_cents", 0),
            }
            for c in candidates
        ]
        user_prompt = _USER_PROMPT_TEMPLATE.format(
            service_type=params["service_type"],
            event_date=params["event_date"],
            guest_count=params["guest_count"],
            location=params["location"],
            min_rating=(
                params["min_rating"]
                if params["min_rating"] is not None
                else "not set"
            ),
            target_vendor_budget_cents=(
                params["target_vendor_budget_cents"]
                if params["target_vendor_budget_cents"] is not None
                else "not set"
            ),
            customer_preferences=(
                params["customer_preferences"]
                if params["customer_preferences"].strip()
                else "(none provided)"
            ),
            candidates_json=json.dumps(candidate_facts, indent=2),
            min_count=MIN_RECOMMENDATIONS,
            max_count=MAX_RECOMMENDATIONS,
            basis_codes=", ".join(ALLOWED_BASIS_CODES),
        )
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

    # ------------------------------------------------------------------
    # Output validation (code-verified facts, no regex on free text)
    # ------------------------------------------------------------------
    def _validate_recommendations(
        self, raw: str, candidates: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Parse and verify the LLM output against candidate facts.

        Returns (recommendations, None) on success or ([], problem).
        """
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            return [], f"LLM response is not valid JSON: {exc}"
        if not isinstance(parsed, dict):
            return [], (
                f"LLM response must be a JSON object, "
                f"got {type(parsed).__name__}"
            )
        if "recommendations" not in parsed:
            return [], "LLM response is missing the 'recommendations' key"
        raw_recs = parsed["recommendations"]
        if not isinstance(raw_recs, list):
            return [], (
                "'recommendations' must be a list, "
                f"got {type(raw_recs).__name__}"
            )
        if not MIN_RECOMMENDATIONS <= len(raw_recs) <= MAX_RECOMMENDATIONS:
            return [], (
                f"expected {MIN_RECOMMENDATIONS}-{MAX_RECOMMENDATIONS} "
                f"recommendations, got {len(raw_recs)}"
            )

        by_pair = {
            (c["vendor_id"], c["offering_id"]): c for c in candidates
        }
        min_price = min(c["total_price_cents"] for c in candidates)
        max_rating = max(c["rating"] for c in candidates)
        max_capacity = max(c["guest_capacity"] for c in candidates)

        superlatives = {
            "lowest_price": (min_price, lambda c: c["total_price_cents"]),
            "highest_rating": (max_rating, lambda c: c["rating"]),
            "highest_capacity": (max_capacity, lambda c: c["guest_capacity"]),
            "within_budget": (True, lambda c: c.get("within_target_budget", True)),
        }

        recommendations: list[dict[str, Any]] = []
        seen_pairs: set[tuple[str, str]] = set()
        for index, item in enumerate(raw_recs):
            where = f"recommendations[{index}]"
            if not isinstance(item, dict):
                return [], f"{where} must be an object, got {type(item).__name__}"

            vendor_id = item.get("vendor_id")
            offering_id = item.get("offering_id")
            if not isinstance(vendor_id, str) or not vendor_id.strip():
                return [], f"{where}.vendor_id must be a non-empty string"
            if not isinstance(offering_id, str) or not offering_id.strip():
                return [], f"{where}.offering_id must be a non-empty string"

            candidate = by_pair.get((vendor_id, offering_id))
            if candidate is None:
                return [], (
                    f"{where} references unknown candidate pair "
                    f"({vendor_id!r}, {offering_id!r}); recommendations may "
                    "only come from the provided candidates"
                )
            pair = (vendor_id, offering_id)
            if pair in seen_pairs:
                return [], (
                    f"{where} repeats candidate pair {vendor_id!r}, "
                    f"{offering_id!r}"
                )
            seen_pairs.add(pair)

            basis_codes = item.get("basis_codes")
            if not isinstance(basis_codes, list):
                return [], (
                    f"{where}.basis_codes must be a list, "
                    f"got {type(basis_codes).__name__}"
                )
            for code in basis_codes:
                if not isinstance(code, str) or code not in ALLOWED_BASIS_CODES:
                    return [], (
                        f"{where}.basis_codes contains unknown code "
                        f"{code!r}; allowed: {', '.join(ALLOWED_BASIS_CODES)}"
                    )
                expected, getter = superlatives[code]
                actual = getter(candidate)
                if actual != expected:
                    return [], (
                        f"{where}.basis_code {code!r} does not hold: "
                        f"candidate {vendor_id}/{offering_id} has value "
                        f"{actual} but the extreme across all candidates "
                        f"is {expected}"
                    )

            reason = item.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                return [], f"{where}.reason must be a non-empty string"

            recommendations.append(
                {
                    # Facts — always backfilled from the catalog, never
                    # from the model output.
                    "vendor_id": candidate["vendor_id"],
                    "offering_id": candidate["offering_id"],
                    "vendor_name": candidate["vendor_name"],
                    "service_type": candidate["service_type"],
                    "service_location": candidate["service_location"],
                    "guest_capacity": candidate["guest_capacity"],
                    "rating": candidate["rating"],
                    "total_price_cents": candidate["total_price_cents"],
                    "event_date": candidate["date"],
                    # Codes verified against candidate facts in the
                    # current filtered candidate set (may be empty).
                    "basis_codes": list(basis_codes),
                    # AI preference explanation — NOT fully fact-verified.
                    "recommendation_reason": reason,
                    "rank": index + 1,
                }
            )
        return recommendations, None
