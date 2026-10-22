"""VendorProcurementService implementation for deterministic vendor filtering.

Scope (KAN-15): filter the fictional vendor catalog by service type,
event date, guest count and service location. No LLM, no booking,
no payment, no other agents.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.shared.schemas import (
    Vendor,
    VendorServiceOffering,
    require_int,
    require_non_empty_str,
    require_valid_date,
)


ANY_SERVICE_TYPE = "any"


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
        - offering.service_type == service_type (case-insensitive), unless
          service_type is "any", which disables only the service filter
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
                if wanted_type != ANY_SERVICE_TYPE and offering.service_type.lower() != wanted_type:
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
