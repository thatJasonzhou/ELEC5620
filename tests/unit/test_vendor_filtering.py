"""Unit tests for deterministic vendor filtering (KAN-15)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.services.vendor_procurement_service import VendorProcurementService
from src.shared.schemas import Vendor, VendorAvailability, VendorServiceOffering

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = REPO_ROOT / "data" / "vendor_catalog.json"


@pytest.fixture(scope="module")
def service() -> VendorProcurementService:
    return VendorProcurementService.from_json_file(CATALOG_PATH)


class TestFilterHappyPath:
    def test_catering_melbourne_120_guests(self, service: VendorProcurementService):
        results = service.filter_vendors(
            service_type="catering",
            date="2026-12-05",
            guest_count=120,
            location="Melbourne",
        )
        # V-CAT-002-O1 (120 cap, 620000) and V-CAT-001-O1 (300 cap, 1850000);
        # V-CAT-001-O2 is Geelong. Sorted by price ascending.
        assert [r["vendor_id"] for r in results] == ["V-CAT-002", "V-CAT-001"]
        assert results[0]["offering_id"] == "V-CAT-002-O1"
        assert results[0]["total_price_cents"] == 620000
        assert results[1]["offering_id"] == "V-CAT-001-O1"

    def test_photography_melbourne_80_guests(self, service: VendorProcurementService):
        results = service.filter_vendors(
            service_type="photography",
            date="2026-12-05",
            guest_count=80,
            location="Melbourne",
        )
        # Only V-PHOTO-001-O1: V-PHOTO-002-O1 is not available on 2026-12-05.
        assert [r["vendor_id"] for r in results] == ["V-PHOTO-001"]
        assert results[0]["total_price_cents"] == 2400000

    def test_result_fields(self, service: VendorProcurementService):
        results = service.filter_vendors(
            service_type="catering",
            date="2026-12-05",
            guest_count=100,
            location="Melbourne",
        )
        assert len(results) == 2
        first = results[0]
        assert set(first) == {
            "vendor_id",
            "vendor_name",
            "offering_id",
            "service_type",
            "service_location",
            "guest_capacity",
            "rating",
            "total_price_cents",
            "date",
        }
        assert first["date"] == "2026-12-05"
        assert isinstance(first["total_price_cents"], int)


class TestFilterCriteria:
    def test_capacity_excludes_small_offering(self, service: VendorProcurementService):
        results = service.filter_vendors(
            service_type="catering",
            date="2026-12-05",
            guest_count=150,
            location="Melbourne",
        )
        # Bayside Bite Co (cap 120) must be excluded.
        assert [r["offering_id"] for r in results] == ["V-CAT-001-O1"]

    def test_date_excludes_unavailable_offering(self, service: VendorProcurementService):
        results = service.filter_vendors(
            service_type="photography",
            date="2026-12-07",
            guest_count=100,
            location="Melbourne",
        )
        # V-PHOTO-002-O1 has available=false on 2026-12-07.
        assert [r["offering_id"] for r in results] == ["V-PHOTO-001-O1"]

    def test_location_excludes_other_cities(self, service: VendorProcurementService):
        results = service.filter_vendors(
            service_type="catering",
            date="2026-12-05",
            guest_count=100,
            location="Geelong",
        )
        assert [r["offering_id"] for r in results] == ["V-CAT-001-O2"]

    def test_service_type_excludes_other_types(self, service: VendorProcurementService):
        results = service.filter_vendors(
            service_type="photography",
            date="2026-12-05",
            guest_count=100,
            location="Melbourne",
        )
        assert all(r["service_type"] == "photography" for r in results)

    def test_no_match_returns_empty_list(self, service: VendorProcurementService):
        results = service.filter_vendors(
            service_type="catering",
            date="2026-12-05",
            guest_count=100,
            location="Sydney",
        )
        assert results == []

    def test_case_insensitive_type_and_location(self, service: VendorProcurementService):
        results = service.filter_vendors(
            service_type="Catering",
            date="2026-12-05",
            guest_count=120,
            location="melbourne",
        )
        assert [r["vendor_id"] for r in results] == ["V-CAT-002", "V-CAT-001"]

    def test_negative_guest_count_raises(self, service: VendorProcurementService):
        with pytest.raises(ValueError):
            service.filter_vendors(
                service_type="catering",
                date="2026-12-05",
                guest_count=-1,
                location="Melbourne",
            )


class TestDeterministicOrdering:
    def test_same_price_orders_by_rating_then_ids(self, tmp_path: Path):
        catalog = {
            "vendors": [
                {
                    "vendor_id": "V-B",
                    "name": "B Vendor",
                    "service_offerings": [
                        {
                            "offering_id": "V-B-O1",
                            "service_type": "catering",
                            "service_location": "Melbourne",
                            "guest_capacity": 200,
                            "rating": 4.0,
                            "total_price_cents": 100000,
                            "availability": [{"date": "2026-12-05"}],
                        }
                    ],
                },
                {
                    "vendor_id": "V-A",
                    "name": "A Vendor",
                    "service_offerings": [
                        {
                            "offering_id": "V-A-O1",
                            "service_type": "catering",
                            "service_location": "Melbourne",
                            "guest_capacity": 200,
                            "rating": 4.5,
                            "total_price_cents": 100000,
                            "availability": [{"date": "2026-12-05"}],
                        }
                    ],
                },
            ]
        }
        file = tmp_path / "catalog.json"
        file.write_text(json.dumps(catalog), encoding="utf-8")

        svc = VendorProcurementService.from_json_file(file)
        results = svc.filter_vendors(
            service_type="catering",
            date="2026-12-05",
            guest_count=50,
            location="Melbourne",
        )
        # Same price: higher rating first; ties would fall back to vendor_id.
        assert [r["vendor_id"] for r in results] == ["V-A", "V-B"]


class TestSchemaLoading:
    def test_catalog_loaded_from_json(self, service: VendorProcurementService):
        catalog = service.catalog
        assert len(catalog) == 4
        first: Vendor = next(v for v in catalog if v.vendor_id == "V-CAT-001")
        offering: VendorServiceOffering = first.service_offerings[0]
        assert offering.total_price_cents == 1850000
        assert isinstance(offering.availability, list)
        assert all(
            isinstance(slot, VendorAvailability) for slot in offering.availability
        )
