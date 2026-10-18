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
  shared-data-and-interfaces.md and is NOT implemented here.
- Prices come from the fictional catalog and are whole-event estimates.
  They are never treated as confirmed quotations.
- No booking, no payment, no persistence, no other Agents.
"""
from __future__ import annotations

import json
from typing import Any

from src.agents.base import AIAgent
from src.llm import LLMClient, LLMError
from src.services.vendor_procurement_service import VendorProcurementService
from src.shared.schemas import (
    require_int,
    require_non_empty_str,
    require_number,
    require_valid_date,
)

#: Closed set of basis codes the model may cite for a recommendation.
ALLOWED_BASIS_CODES = ("lowest_price", "highest_rating", "highest_capacity")

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
    ) -> None:
        super().__init__(llm)
        if not isinstance(vendor_service, VendorProcurementService):
            raise TypeError(
                "vendor_service must be a VendorProcurementService instance"
            )
        self._vendor_service = vendor_service

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
                            f"must be within the 0-5 rating scale, "
                            f"got {min_rating}",
                        )
                    )
                    min_rating = None
        params["min_rating"] = min_rating

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
