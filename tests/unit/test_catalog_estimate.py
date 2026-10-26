"""Pre-enquiry catalogue evidence, budget boundaries and strict input validation."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import pytest

from src.services.vendor_procurement_service import VendorProcurementService
from src.shared.costing import calculate_event_costs, supplier_budget_ceiling

ROOT = Path(__file__).resolve().parents[2]


def request():
    return {
        "event_date": "2026-12-16", "location": "Sydney", "guest_count": 50,
        "budget_limit_cents": 1200000,
        "customer_preferences": "Photography quality is the priority.",
        "services": [{"service_type": kind} for kind in
                     ("photography", "catering", "venue", "sound", "decoration")],
    }


@pytest.fixture
def service():
    return VendorProcurementService.from_json_file(ROOT / "data/vendor_catalog.json")


def test_catalogue_precheck_is_complete_read_only_and_not_financial_approval(service):
    payload = request()
    before = deepcopy(payload)
    catalog_before = [asdict(v) for v in service.catalog]
    result = service.estimate_event(payload)
    assert result["status"] == "within_budget_estimate"
    assert result["estimate_only"] is result["finance_review_required"] is True
    assert result["preferences_evaluated"] is False
    assert [item["minimum_catalog_price_cents"] for item in result["service_estimates"]] == [
        95000, 380000, 250000, 70000, 60000]
    assert all(item["candidate_count"] == 5 for item in result["service_estimates"])
    assert result["minimum_costs"]["vendor_cost_cents"] == 855000
    assert result["minimum_costs"]["customer_price_cents"] == 1026000
    assert result["supplier_budget_limit_cents"] == 1000000
    assert result["budget_shortfall_cents"] == 0
    assert payload == before
    assert [asdict(v) for v in service.catalog] == catalog_before
    assert "quotations" not in result and "selected_quotation_ids" not in result


@pytest.mark.parametrize("budget,status,shortfall", [
    (50000, "over_budget_estimate", 976000),
    (1025999, "over_budget_estimate", 1),
    (1026000, "within_budget_estimate", 0),
])
def test_complete_cost_including_fees_decides_budget(service, budget, status, shortfall):
    payload = request()
    payload["budget_limit_cents"] = budget
    result = service.estimate_event(payload)
    assert result["status"] == status
    assert result["budget_shortfall_cents"] == shortfall


@pytest.mark.parametrize("change", [
    {"event_date": "2027-01-01"},
    {"location": "Unlisted city"},
    {"guest_count": 999999},
    {"services": [{"service_type": "unlisted"}]},
    {"services": [{"service_type": "photography"}, {"service_type": "unlisted"}]},
])
def test_missing_services_never_become_zero_or_partial_event_totals(service, change):
    payload = {**request(), **change}
    result = service.estimate_event(payload)
    assert result["status"] == "no_candidates"
    assert result["missing_services"]
    assert result["minimum_costs"] is None
    assert result["budget_shortfall_cents"] is None
    assert result["supplier_budget_shortfall_cents"] is None
    missing = [r for r in result["service_estimates"] if r["candidate_count"] == 0]
    assert all(r["minimum_catalog_price_cents"] is None for r in missing)


def test_hard_rating_filter_changes_the_price_evidence(service):
    payload = request()
    payload["services"] = [{"service_type": "photography", "min_rating": 4.9}]
    result = service.estimate_event(payload)
    candidates = service.filter_vendors(
        service_type="photography", date=payload["event_date"],
        location=payload["location"], guest_count=payload["guest_count"])
    expected = [c for c in candidates if c["rating"] >= 4.9]
    assert result["service_estimates"][0]["minimum_catalog_price_cents"] == min(
        c["total_price_cents"] for c in expected)
    assert result["service_estimates"][0]["candidate_count"] == len(expected)


def test_per_service_rating_cannot_weaken_global_requirement(service):
    payload = request()
    payload["min_rating"] = 5
    payload["services"] = [{"service_type": "photography", "min_rating": 0}]
    result = service.estimate_event(payload)
    assert result["service_estimates"][0]["min_rating"] == 5
    assert result["status"] == "no_candidates"


def test_optional_supplier_cap_can_be_stricter_but_cannot_spend_customer_fees(service):
    payload = request()
    payload["supplier_budget_limit_cents"] = 1100000
    assert service.estimate_event(payload)["supplier_budget_limit_cents"] == 1000000
    payload["supplier_budget_limit_cents"] = 800000
    result = service.estimate_event(payload)
    assert result["status"] == "over_budget_estimate"
    assert result["budget_shortfall_cents"] == 0
    assert result["supplier_budget_shortfall_cents"] == 55000


@pytest.mark.parametrize("change", [
    {"budget_limit_cents": True}, {"budget_limit_cents": -1},
    {"budget_limit_cents": 500.0}, {"budget_limit_cents": None},
    {"guest_count": True}, {"guest_count": -1},
    {"event_date": "2026-02-30"}, {"location": " "},
    {"services": []}, {"services": ["photography"]},
    {"services": [{"service_type": "photography"}] * 6},
    {"services": [{"service_type": "photography"}, {"service_type": " Photography "}]},
    {"services": [{"service_type": " "}]},
    {"min_rating": float("nan")}, {"min_rating": float("inf")},
    {"min_rating": True}, {"min_rating": 5.1}, {"min_rating": 10**400},
    {"services": [{"service_type": "photography", "min_rating": -1}]},
    {"supplier_budget_limit_cents": False},
    {"customer_preferences": []},
])
def test_invalid_input_is_rejected(service, change):
    with pytest.raises(ValueError):
        service.estimate_event({**request(), **change})


@pytest.mark.parametrize("bad", [None, [], "request"])
def test_non_object_rejected(service, bad):
    with pytest.raises(ValueError):
        service.estimate_event(bad)


@pytest.mark.parametrize("limit", [0, 1, 4, 5, 6, 9, 10, 1206, 1207, 50000, 1200000, 10**40])
def test_supplier_ceiling_is_exact_even_at_fee_rounding_boundaries(limit):
    ceiling = supplier_budget_ceiling(limit)
    assert calculate_event_costs(ceiling)["customer_price_cents"] <= limit
    assert calculate_event_costs(ceiling + 1)["customer_price_cents"] > limit


def test_zero_price_is_a_real_estimate_not_missing_data():
    from src.shared.schemas import Vendor, VendorAvailability, VendorServiceOffering

    offering = VendorServiceOffering(
        "O-FREE", "venue", "Sydney", 50, 4.5, 0,
        [VendorAvailability("2026-12-16", True)])
    service = VendorProcurementService([Vendor("V-FREE", "Free venue", [offering])])
    payload = request()
    payload.update(budget_limit_cents=0, services=[{"service_type": "venue"}])
    result = service.estimate_event(payload)
    assert result["status"] == "within_budget_estimate"
    assert result["minimum_costs"]["customer_price_cents"] == 0
    assert result["missing_services"] == []
