"""Read-only vendor filtering (KAN-15) and Planner budget estimates (KAN-41).

Filter the fictional catalogue by service type, event date, guest count and
location. Estimate whole-event costs before enquiries. No LLM, bookings,
payments, state writes or other Agent calls.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.shared.schemas import (
    Vendor,
    VendorServiceOffering,
    require_int,
    require_number,
    require_non_empty_str,
    require_valid_date,
)


class VendorProcurementService:
    """Read-only access to the vendor catalog with deterministic filtering."""

    def __init__(self, catalog: list[Vendor]) -> None:
        self._catalog = catalog

    @classmethod
    def from_json_file(cls, path: str | Path) -> "VendorProcurementService":
        """Load and strictly validate a vendor catalog JSON file.

        Raises ValueError with the offending path when the file is not a
        JSON object, the ``vendors`` key is missing, or any vendor,
        offering or availability slot has an invalid type or value.
        An empty or malformed catalog is never silently treated as valid.
        """
        catalog_path = Path(path)
        try:
            data = json.loads(catalog_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"invalid JSON in vendor catalog {catalog_path}: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise ValueError(
                f"vendor catalog {catalog_path} must be a JSON object, "
                f"got {type(data).__name__}"
            )
        if "vendors" not in data:
            raise ValueError(
                f"vendor catalog {catalog_path} must contain a 'vendors' "
                "list of vendors"
            )
        raw_vendors = data["vendors"]
        if not isinstance(raw_vendors, list):
            raise ValueError(
                f"'vendors' in {catalog_path} must be a list of vendors, "
                f"got {type(raw_vendors).__name__}"
            )
        try:
            vendors = [Vendor.from_dict(v) for v in raw_vendors]
        except ValueError as exc:
            raise ValueError(
                f"invalid vendor catalog {catalog_path}: {exc}"
            ) from exc
        return cls(vendors)

    @property
    def catalog(self) -> list[Vendor]:
        return list(self._catalog)

    def filter_vendors(
        self,
        *,
        service_type: str,
        date: str,
        guest_count: int,
        location: str,
    ) -> list[dict[str, Any]]:
        """Return matching offerings, sorted deterministically.

        Criteria (all must hold):
        - offering.service_type == service_type (case-insensitive)
        - offering available on ``date`` (YYYY-MM-DD)
        - offering.guest_capacity >= guest_count
        - offering.service_location == location (case-insensitive)

        Ordering: (total_price_cents, rating desc, vendor_id, offering_id).

        Raises ValueError when any argument has a wrong type or value:
        ``service_type``/``location`` must be non-empty strings, ``date``
        a real YYYY-MM-DD calendar date, ``guest_count`` a non-negative
        int (bools and floats rejected).
        """
        wanted_type = require_non_empty_str(
            service_type, "service_type"
        ).strip().lower()
        wanted_location = require_non_empty_str(
            location, "location"
        ).strip().lower()
        event_date = require_valid_date(date, "date")
        guests = require_int(guest_count, "guest_count", minimum=0)
        matches: list[tuple[int, float, str, str, dict[str, Any]]] = []

        for vendor in self._catalog:
            for offering in vendor.service_offerings:
                if offering.service_type.lower() != wanted_type:
                    continue
                if not offering.is_available_on(event_date):
                    continue
                if offering.guest_capacity < guests:
                    continue
                if offering.service_location.lower() != wanted_location:
                    continue
                result = self._to_result(vendor, offering, event_date)
                key = (
                    offering.total_price_cents,
                    -offering.rating,
                    vendor.vendor_id,
                    offering.offering_id,
                )
                matches.append((*key, result))

        matches.sort(key=lambda item: item[:4])
        return [item[4] for item in matches]

    @staticmethod
    def _to_result(
        vendor: Vendor, offering: VendorServiceOffering, date: str
    ) -> dict[str, Any]:
        return {
            "vendor_id": vendor.vendor_id,
            "vendor_name": vendor.name,
            "offering_id": offering.offering_id,
            "service_type": offering.service_type,
            "service_location": offering.service_location,
            "guest_capacity": offering.guest_capacity,
            "rating": offering.rating,
            "total_price_cents": offering.total_price_cents,
            "date": date,
        }

    def estimate_event(self, request: dict[str, Any]) -> dict[str, Any]:
        """Read-only catalogue budget precheck for Planner (KAN-41).

        Requires event_date, location, guest_count, budget_limit_cents and
        1-5 unique services objects. Optional per-service/global min_rating
        is a hard eligibility filter. Preferences and soft allocations are
        not priced. Invalid requests raise ValueError without side effects.

        The minimum is catalogue evidence only, not a quote, supplier
        commitment, final selection or Financial approval.
        """
        from math import isfinite
        from src.shared.costing import calculate_event_costs, supplier_budget_ceiling

        if not isinstance(request, dict):
            raise ValueError("request must be an object")
        event_date = require_valid_date(request.get("event_date"), "event_date")
        location = require_non_empty_str(request.get("location"), "location").strip()
        guests = require_int(request.get("guest_count"), "guest_count", minimum=0)
        budget = require_int(request.get("budget_limit_cents"), "budget_limit_cents", minimum=0)
        services = request.get("services")
        if not isinstance(services, list) or not 1 <= len(services) <= 5:
            raise ValueError("services must contain 1-5 service objects")
        preferences = request.get("customer_preferences", "")
        if not isinstance(preferences, str):
            raise ValueError("customer_preferences must be text")

        ceiling = supplier_budget_ceiling(budget)
        if request.get("supplier_budget_limit_cents") is not None:
            ceiling = min(ceiling, require_int(
                request["supplier_budget_limit_cents"], "supplier_budget_limit_cents", minimum=0))

        def rating(value):
            if value is None:
                return None
            try:
                value = require_number(value, "min_rating")
            except OverflowError as exc:
                raise ValueError("min_rating must be finite and between 0 and 5") from exc
            if not isfinite(value) or not 0 <= value <= 5:
                raise ValueError("min_rating must be finite and between 0 and 5")
            return value

        global_rating = rating(request.get("min_rating"))
        normalized, seen = [], set()
        for item in services:
            if not isinstance(item, dict):
                raise ValueError("each services item must be an object")
            kind = require_non_empty_str(item.get("service_type"), "service_type").strip().lower()
            if kind in seen:
                raise ValueError("services must contain unique service types")
            seen.add(kind)
            item_rating = rating(item.get("min_rating"))
            thresholds = [r for r in (global_rating, item_rating) if r is not None]
            normalized.append((kind, max(thresholds) if thresholds else None))

        estimates, missing = [], []
        for kind, threshold in normalized:
            candidates = self.filter_vendors(
                service_type=kind, date=event_date, guest_count=guests, location=location)
            if threshold is not None:
                candidates = [c for c in candidates if c["rating"] >= threshold]
            prices = [c["total_price_cents"] for c in candidates]
            estimates.append({
                "service_type": kind,
                "candidate_count": len(candidates),
                "min_rating": threshold,
                "minimum_catalog_price_cents": min(prices) if prices else None,
                "maximum_catalog_price_cents": max(prices) if prices else None,
            })
            if not candidates:
                missing.append(kind)

        # A partial catalogue match must never look like a cheap complete event.
        costs = None if missing else calculate_event_costs(sum(
            item["minimum_catalog_price_cents"] for item in estimates))
        customer_shortfall = None if costs is None else max(
            0, costs["customer_price_cents"] - budget)
        supplier_shortfall = None if costs is None else max(
            0, costs["vendor_cost_cents"] - ceiling)
        if missing:
            status = "no_candidates"
        elif customer_shortfall or supplier_shortfall:
            status = "over_budget_estimate"
        else:
            status = "within_budget_estimate"
        return {
            "status": status,
            "estimate_only": True,
            "finance_review_required": True,
            "preferences_evaluated": False,
            "event_date": event_date,
            "location": location,
            "guest_count": guests,
            "budget_limit_cents": budget,
            "supplier_budget_limit_cents": ceiling,
            "service_estimates": estimates,
            "missing_services": missing,
            "minimum_costs": costs,
            "budget_shortfall_cents": customer_shortfall,
            "supplier_budget_shortfall_cents": supplier_shortfall,
        }
