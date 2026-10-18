"""VendorProcurementService implementation for deterministic vendor filtering.

Scope (KAN-15): filter the fictional vendor catalog by service type,
event date, guest count and service location. No LLM, no booking,
no payment, no other agents.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.shared.schemas import Vendor, VendorServiceOffering


class VendorProcurementService:
    """Read-only access to the vendor catalog with deterministic filtering."""

    def __init__(self, catalog: list[Vendor]) -> None:
        self._catalog = catalog

    @classmethod
    def from_json_file(cls, path: str | Path) -> "VendorProcurementService":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        vendors = [Vendor.from_dict(v) for v in data.get("vendors", [])]
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
        """
        if guest_count < 0:
            raise ValueError("guest_count must be >= 0")

        wanted_type = service_type.strip().lower()
        wanted_location = location.strip().lower()
        matches: list[tuple[int, float, str, str, dict[str, Any]]] = []

        for vendor in self._catalog:
            for offering in vendor.service_offerings:
                if offering.service_type.lower() != wanted_type:
                    continue
                if not offering.is_available_on(date):
                    continue
                if offering.guest_capacity < guest_count:
                    continue
                if offering.service_location.lower() != wanted_location:
                    continue
                result = self._to_result(vendor, offering, date)
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
