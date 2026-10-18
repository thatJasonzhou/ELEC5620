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


class TestFilterInputValidation:
    def _kwargs(
        self,
        **overrides: Any,
    ) -> dict[str, Any]:
        kwargs = {
            "service_type": "catering",
            "date": "2026-12-05",
            "guest_count": 100,
            "location": "Melbourne",
        }
        kwargs.update(overrides)
        return kwargs

    def test_guest_count_rejects_bool(self, service: VendorProcurementService):
        with pytest.raises(ValueError, match="guest_count"):
            service.filter_vendors(**self._kwargs(guest_count=True))

    @pytest.mark.parametrize(
        "guest_count", ["100", 100.0, None, [100]]
    )
    def test_guest_count_rejects_non_int(
        self, service: VendorProcurementService, guest_count: Any
    ):
        with pytest.raises(ValueError, match="guest_count"):
            service.filter_vendors(**self._kwargs(guest_count=guest_count))

    def test_guest_count_rejects_negative(
        self, service: VendorProcurementService
    ):
        with pytest.raises(ValueError, match="guest_count"):
            service.filter_vendors(**self._kwargs(guest_count=-1))

    @pytest.mark.parametrize(
        "date",
        [
            "2026/12/05",   # wrong separator
            "2026-1-5",     # not zero padded
            "2026-13-05",   # invalid month
            "2026-02-30",   # not a real calendar date
            "26-12-05",     # not YYYY
            "2026-12-05T00:00:00",  # datetime, not date
            20261205,
            None,
            True,
        ],
    )
    def test_date_rejects_invalid(
        self, service: VendorProcurementService, date: Any
    ):
        with pytest.raises(ValueError, match="date"):
            service.filter_vendors(**self._kwargs(date=date))

    @pytest.mark.parametrize("service_type", ["", "   ", 42, None, 1.5, True])
    def test_service_type_rejects_empty_or_non_str(
        self, service: VendorProcurementService, service_type: Any
    ):
        with pytest.raises(ValueError, match="service_type"):
            service.filter_vendors(**self._kwargs(service_type=service_type))

    @pytest.mark.parametrize("location", ["", "   ", 0, None, ["Melbourne"]])
    def test_location_rejects_empty_or_non_str(
        self, service: VendorProcurementService, location: Any
    ):
        with pytest.raises(ValueError, match="location"):
            service.filter_vendors(**self._kwargs(location=location))


class TestCatalogLoadingValidation:
    @staticmethod
    def _write_catalog(tmp_path: Path, payload: Any) -> Path:
        file = tmp_path / "catalog.json"
        file.write_text(json.dumps(payload), encoding="utf-8")
        return file

    @staticmethod
    def _valid_vendor() -> dict[str, Any]:
        return {
            "vendor_id": "V-1",
            "name": "Valid Vendor",
            "service_offerings": [
                {
                    "offering_id": "V-1-O1",
                    "service_type": "catering",
                    "service_location": "Melbourne",
                    "guest_capacity": 100,
                    "rating": 4.0,
                    "total_price_cents": 100000,
                    "availability": [{"date": "2026-12-05"}],
                }
            ],
        }

    def test_missing_vendors_key_raises(self, tmp_path: Path):
        file = self._write_catalog(tmp_path, {"catalog": []})
        with pytest.raises(ValueError, match="'vendors'"):
            VendorProcurementService.from_json_file(file)

    def test_vendors_not_a_list_raises(self, tmp_path: Path):
        file = self._write_catalog(tmp_path, {"vendors": "oops"})
        with pytest.raises(ValueError, match="list of vendors"):
            VendorProcurementService.from_json_file(file)

    def test_catalog_not_an_object_raises(self, tmp_path: Path):
        file = self._write_catalog(tmp_path, ["not", "an", "object"])
        with pytest.raises(ValueError, match="JSON object"):
            VendorProcurementService.from_json_file(file)

    def test_invalid_json_raises(self, tmp_path: Path):
        file = tmp_path / "catalog.json"
        file.write_text("{ not json", encoding="utf-8")
        with pytest.raises(ValueError, match="invalid JSON"):
            VendorProcurementService.from_json_file(file)

    def test_string_available_rejected(self, tmp_path: Path):
        vendor = self._valid_vendor()
        vendor["service_offerings"][0]["availability"] = [
            {"date": "2026-12-05", "available": "yes"}
        ]
        file = self._write_catalog(tmp_path, {"vendors": [vendor]})
        with pytest.raises(ValueError, match="available must be a boolean"):
            VendorProcurementService.from_json_file(file)

    def test_int_available_rejected(self, tmp_path: Path):
        vendor = self._valid_vendor()
        vendor["service_offerings"][0]["availability"] = [
            {"date": "2026-12-05", "available": 1}
        ]
        file = self._write_catalog(tmp_path, {"vendors": [vendor]})
        with pytest.raises(ValueError, match="available must be a boolean"):
            VendorProcurementService.from_json_file(file)

    def test_float_price_rejected(self, tmp_path: Path):
        vendor = self._valid_vendor()
        vendor["service_offerings"][0]["total_price_cents"] = 100000.0
        file = self._write_catalog(tmp_path, {"vendors": [vendor]})
        with pytest.raises(ValueError, match="total_price_cents"):
            VendorProcurementService.from_json_file(file)

    def test_negative_price_rejected(self, tmp_path: Path):
        vendor = self._valid_vendor()
        vendor["service_offerings"][0]["total_price_cents"] = -5
        file = self._write_catalog(tmp_path, {"vendors": [vendor]})
        with pytest.raises(ValueError, match="total_price_cents"):
            VendorProcurementService.from_json_file(file)

    def test_bool_capacity_rejected(self, tmp_path: Path):
        vendor = self._valid_vendor()
        vendor["service_offerings"][0]["guest_capacity"] = True
        file = self._write_catalog(tmp_path, {"vendors": [vendor]})
        with pytest.raises(ValueError, match="guest_capacity"):
            VendorProcurementService.from_json_file(file)

    def test_float_capacity_rejected(self, tmp_path: Path):
        vendor = self._valid_vendor()
        vendor["service_offerings"][0]["guest_capacity"] = 100.5
        file = self._write_catalog(tmp_path, {"vendors": [vendor]})
        with pytest.raises(ValueError, match="guest_capacity"):
            VendorProcurementService.from_json_file(file)

    def test_invalid_availability_date_rejected(self, tmp_path: Path):
        vendor = self._valid_vendor()
        vendor["service_offerings"][0]["availability"] = [
            {"date": "2026-02-30"}
        ]
        file = self._write_catalog(tmp_path, {"vendors": [vendor]})
        with pytest.raises(ValueError, match="availability.date"):
            VendorProcurementService.from_json_file(file)

    def test_missing_vendor_id_rejected(self, tmp_path: Path):
        vendor = self._valid_vendor()
        del vendor["vendor_id"]
        file = self._write_catalog(tmp_path, {"vendors": [vendor]})
        with pytest.raises(ValueError, match="vendor_id"):
            VendorProcurementService.from_json_file(file)

    def test_error_message_includes_file_path(self, tmp_path: Path):
        vendor = self._valid_vendor()
        vendor["service_offerings"][0]["total_price_cents"] = 1.5
        file = self._write_catalog(tmp_path, {"vendors": [vendor]})
        with pytest.raises(ValueError, match=r"catalog\.json"):
            VendorProcurementService.from_json_file(file)

    def test_valid_catalog_still_loads(self, tmp_path: Path):
        """Legitimate data (including omitted optional fields) keeps working."""
        vendor = self._valid_vendor()
        # Omit 'available' (defaults to True) and add an explicitly
        # unavailable slot with a real boolean value.
        vendor["service_offerings"][0]["availability"] = [
            {"date": "2026-12-05"},
            {"date": "2026-12-06", "available": False},
        ]
        file = self._write_catalog(tmp_path, {"vendors": [vendor]})
        svc = VendorProcurementService.from_json_file(file)
        assert len(svc.catalog) == 1
        results = svc.filter_vendors(
            service_type="catering",
            date="2026-12-05",
            guest_count=50,
            location="Melbourne",
        )
        assert [r["offering_id"] for r in results] == ["V-1-O1"]


class TestTieBreakOrdering:
    def test_same_price_and_rating_orders_by_ids(self, tmp_path: Path):
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
                            "rating": 4.5,
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
                            "offering_id": "V-A-O2",
                            "service_type": "catering",
                            "service_location": "Melbourne",
                            "guest_capacity": 200,
                            "rating": 4.5,
                            "total_price_cents": 100000,
                            "availability": [{"date": "2026-12-05"}],
                        },
                        {
                            "offering_id": "V-A-O1",
                            "service_type": "catering",
                            "service_location": "Melbourne",
                            "guest_capacity": 200,
                            "rating": 4.5,
                            "total_price_cents": 100000,
                            "availability": [{"date": "2026-12-05"}],
                        },
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
        # All three have identical price and rating, so order is by
        # (vendor_id, offering_id): V-A-O1, V-A-O2, V-B-O1.
        assert [
            (r["vendor_id"], r["offering_id"]) for r in results
        ] == [
            ("V-A", "V-A-O1"),
            ("V-A", "V-A-O2"),
            ("V-B", "V-B-O1"),
        ]
