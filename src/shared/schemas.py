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
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class VendorAvailability:
    """One availability slot on a service offering.

    ``date`` uses the shared format ``YYYY-MM-DD``.
    """

    date: str
    available: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VendorAvailability":
        return cls(date=data["date"], available=bool(data.get("available", True)))


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
        return cls(
            offering_id=data["offering_id"],
            service_type=data["service_type"],
            service_location=data["service_location"],
            guest_capacity=int(data["guest_capacity"]),
            rating=float(data["rating"]),
            total_price_cents=int(data["total_price_cents"]),
            availability=[
                VendorAvailability.from_dict(slot)
                for slot in data.get("availability", [])
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
        return cls(
            vendor_id=data["vendor_id"],
            name=data["name"],
            service_offerings=[
                VendorServiceOffering.from_dict(offer)
                for offer in data.get("service_offerings", [])
            ],
        )
