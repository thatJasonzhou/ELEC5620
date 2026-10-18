"""Shared dataclasses for the vendor catalog (Stage 2, KAN-15).

These are minimal example structures for the vendor filtering feature.
They intentionally do NOT reproduce the complete Stage 1 class
definitions; the field conventions follow shared-data-and-interfaces.md
(snake_case, integer AUD cents, dates in YYYY-MM-DD).

Mapping (Stage 1 names, minimal scope):
- Vendor                 -> vendor identity + its service offerings
- VendorServiceOffering  -> one service a vendor can deliver (type,
                            location, capacity, rating, whole-event price)
- VendorAvailability     -> one available date slot on an offering

Loading is strict: wrong types (bools where ints are required, float
cents, string booleans, invalid dates) raise ValueError instead of
being silently coerced.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def require_non_empty_str(value: Any, field_name: str) -> str:
    """Return ``value`` if it is a non-empty string, else raise ValueError."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string, got {value!r}")
    return value


def require_valid_date(value: Any, field_name: str) -> str:
    """Return ``value`` if it is a real calendar date in YYYY-MM-DD."""
    if not isinstance(value, str):
        raise ValueError(
            f"{field_name} must be a YYYY-MM-DD date string, "
            f"got {type(value).__name__}: {value!r}"
        )
    if not _DATE_RE.match(value):
        raise ValueError(
            f"{field_name} must use YYYY-MM-DD format, got {value!r}"
        )
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError(
            f"{field_name} is not a valid calendar date: {value!r}"
        ) from None
    return value


def require_int(value: Any, field_name: str, *, minimum: int = 0) -> int:
    """Return ``value`` if it is an int (bools rejected) and >= minimum."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"{field_name} must be an integer, "
            f"got {type(value).__name__}: {value!r}"
        )
    if value < minimum:
        raise ValueError(f"{field_name} must be >= {minimum}, got {value}")
    return value


def require_number(value: Any, field_name: str) -> float:
    """Return ``value`` as float if it is a number (bools rejected)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"{field_name} must be a number, "
            f"got {type(value).__name__}: {value!r}"
        )
    return float(value)


@dataclass
class VendorAvailability:
    """One availability slot on a service offering.

    ``date`` uses the shared format ``YYYY-MM-DD``.
    """

    date: str
    available: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VendorAvailability":
        if not isinstance(data, dict):
            raise ValueError(
                "availability slot must be an object, "
                f"got {type(data).__name__}: {data!r}"
            )
        return cls(
            date=require_valid_date(data.get("date"), "availability.date"),
            available=cls._require_available(data.get("available", True)),
        )

    @staticmethod
    def _require_available(value: Any) -> bool:
        if not isinstance(value, bool):
            raise ValueError(
                "availability.available must be a boolean, "
                f"got {type(value).__name__}: {value!r}"
            )
        return value


@dataclass
class VendorServiceOffering:
    """A service a vendor offers for a whole event.

    ``total_price_cents`` is the whole-event price in integer AUD cents.
    """

    offering_id: str
    service_type: str
    service_location: str
    guest_capacity: int
    rating: float
    total_price_cents: int
    availability: list[VendorAvailability] = field(default_factory=list)

    def is_available_on(self, date: str) -> bool:
        return any(slot.date == date and slot.available for slot in self.availability)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VendorServiceOffering":
        if not isinstance(data, dict):
            raise ValueError(
                "service offering must be an object, "
                f"got {type(data).__name__}: {data!r}"
            )
        raw_availability = data.get("availability", [])
        if not isinstance(raw_availability, list):
            raise ValueError(
                "offering.availability must be a list of availability slots, "
                f"got {type(raw_availability).__name__}"
            )
        return cls(
            offering_id=require_non_empty_str(
                data.get("offering_id"), "offering.offering_id"
            ),
            service_type=require_non_empty_str(
                data.get("service_type"), "offering.service_type"
            ),
            service_location=require_non_empty_str(
                data.get("service_location"), "offering.service_location"
            ),
            guest_capacity=require_int(
                data.get("guest_capacity"), "offering.guest_capacity", minimum=0
            ),
            rating=require_number(data.get("rating"), "offering.rating"),
            total_price_cents=require_int(
                data.get("total_price_cents"),
                "offering.total_price_cents",
                minimum=0,
            ),
            availability=[
                VendorAvailability.from_dict(slot) for slot in raw_availability
            ],
        )


@dataclass
class Vendor:
    """A fictional vendor in the catalog."""

    vendor_id: str
    name: str
    service_offerings: list[VendorServiceOffering] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Vendor":
        if not isinstance(data, dict):
            raise ValueError(
                f"vendor must be an object, got {type(data).__name__}: {data!r}"
            )
        raw_offerings = data.get("service_offerings", [])
        if not isinstance(raw_offerings, list):
            raise ValueError(
                "vendor.service_offerings must be a list of offerings, "
                f"got {type(raw_offerings).__name__}"
            )
        return cls(
            vendor_id=require_non_empty_str(data.get("vendor_id"), "vendor.vendor_id"),
            name=require_non_empty_str(data.get("name"), "vendor.name"),
            service_offerings=[
                VendorServiceOffering.from_dict(offer) for offer in raw_offerings
            ],
        )
