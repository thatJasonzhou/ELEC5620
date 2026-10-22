"""KAN-25: FIN-01 provenance, unchanged cents and fail-closed generation."""
from copy import deepcopy
from datetime import datetime
import json

import pytest

from test_budget_check import budget_request, make_worker
from src.shared.schemas import Budget
from src.services.customer_quotation_service import budget_fingerprint


def quotation_request():
    request = budget_request()
    request["quotations"][0]["quoted_total_cents"] = 1005
    request["budget"] = make_worker().handle(request)["data"]
    request["action"] = "generate_customer_quotation"
    return request


def test_exact_fin01_projection_and_linkage(monkeypatch):
    request = quotation_request()
    before = deepcopy(request)
    def no_calculation(*args):
        pytest.fail("quotation generation recalculated budget")
    monkeypatch.setattr(Budget, "calculate_total", no_calculation)
    worker = make_worker()
    result = worker.handle(request)
    assert result["status"] == "success"
    assert result["agent"] == "finance"
    quote = result["data"]["customer_quotation"]
    for key in ("event_id", "proposal_id", "selected_quotation_ids", "vendor_total_cents",
                "service_fee_cents", "contingency_cents", "estimated_total_cents",
                "budget_fingerprint", "quotation_fingerprint", "source_fingerprint"):
        assert quote[key] == request["budget"][key]
    assert quote["estimated_total_cents"] == 1207
    assert quote["service_fee_cents"] == quote["contingency_cents"] == 101
    assert quote["vendor_cost_breakdown"] == request["quotations"]
    assert quote["customer_quotation_id"].startswith("CQ-")
    assert datetime.fromisoformat(quote["generated_at"]).utcoffset() is not None
    assert request == before and not worker.llm.calls
    quote["vendor_cost_breakdown"][0]["quoted_total_cents"] = 999
    assert request == before


@pytest.mark.parametrize("field", ["budget_valid", "within_budget", "vendor_total_cents",
    "service_fee_cents", "contingency_cents", "estimated_total_cents", "price_basis",
    "quotation_fingerprint", "source_fingerprint", "budget_fingerprint",
    "selected_quotation_ids", "required_services", "event_id", "proposal_id"])
def test_incomplete_budget(field):
    request = quotation_request()
    del request["budget"][field]
    result = make_worker().handle(request)
    assert result["status"] == "blocked"
    assert result["data"] == {}


@pytest.mark.parametrize("value", [None, {}, [], "budget"])
def test_missing_invalid_budget(value):
    request = quotation_request()
    request["budget"] = value
    result = make_worker().handle(request)
    assert result["status"] == "blocked" and not result["data"]


@pytest.mark.parametrize("value", [True, -1, 10.5, "101", None])
def test_invalid_financial_values(value):
    request = quotation_request()
    request["budget"]["service_fee_cents"] = value
    result = make_worker().handle(request)
    assert result["status"] == "blocked" and not result["data"]


@pytest.mark.parametrize("change", ["budget-event", "budget-proposal", "quote-price",
    "quote-vendor", "quote-event", "quote-proposal", "unavailable", "missing-quote",
    "duplicate-quote", "selection", "duplicate-selection", "proposal-content",
    "proposal-id", "event-date", "event-limit", "required-services", "invalid-marker",
    "over-budget", "tampered-fee", "legacy-budget"])
def test_stale_inconsistent_or_unvalidated_sources(change):
    r = quotation_request()
    if change == "budget-event": r["budget"]["event_id"] = "OTHER"
    if change == "budget-proposal": r["budget"]["proposal_id"] = "OTHER"
    if change == "quote-price": r["quotations"][0]["quoted_total_cents"] += 1
    if change == "quote-vendor": r["quotations"][0]["vendor_id"] = "OTHER"
    if change == "quote-event": r["quotations"][0]["event_id"] = "OTHER"
    if change == "quote-proposal": r["quotations"][0]["proposal_id"] = "OTHER"
    if change == "unavailable": r["quotations"][0]["available"] = False
    if change == "missing-quote": r["quotations"] = []
    if change == "duplicate-quote": r["quotations"] *= 2
    if change == "selection": r["selected_quotation_ids"] = ["Q2"]
    if change == "duplicate-selection": r["selected_quotation_ids"] *= 2
    if change == "proposal-content": r["proposal"]["description"] = "Revised scope"
    if change == "proposal-id": r["proposal"]["proposal_id"] = "P2"
    if change == "event-date": r["event"]["event_date"] = "2026-12-06"
    if change == "event-limit": r["event"]["budget_limit_cents"] = 1
    if change == "required-services": r["proposal"]["required_services"].append("venue")
    if change == "invalid-marker": r["budget"]["budget_valid"] = "true"
    if change == "over-budget": r["budget"]["within_budget"] = False
    if change == "tampered-fee": r["budget"]["service_fee_cents"] += 1
    if change == "legacy-budget": del r["budget"]["source_fingerprint"]
    result = make_worker().handle(r)
    assert result["status"] == "blocked" and not result["data"]


def test_unselected_quotes_do_not_invalidate_budget():
    r = quotation_request()
    r["quotations"].append({**r["quotations"][0], "quotation_id": "ALTERNATIVE"})
    result = make_worker().handle(r)
    assert result["status"] == "success"
    assert len(result["data"]["customer_quotation"]["vendor_cost_breakdown"]) == 1


def test_revalidate_after_revision():
    r = quotation_request()
    r["proposal"]["revision"] = 2
    r["action"] = "prepare_budget"
    r["budget"] = make_worker().handle(r)["data"]
    r["action"] = "generate_customer_quotation"
    assert make_worker().handle(r)["status"] == "success"


@pytest.mark.parametrize("metadata", [float("nan"), float("inf"), {"invalid": float("nan")},
                                     object(), ["unexpected", None]])
def test_ancillary_metadata_is_excluded_from_strict_json_output(metadata):
    request = quotation_request()
    supplier = request["quotations"][0]
    supplier.update(recommendation_reason=metadata, scenario_id=metadata,
                    internal_notes=metadata)
    result = make_worker().handle(request)
    assert result["status"] == "success"
    exported = result["data"]["customer_quotation"]["vendor_cost_breakdown"][0]
    fields = {"event_id", "proposal_id", "quotation_id", "vendor_id", "offering_id",
              "service_type", "event_date", "guest_count", "quoted_total_cents",
              "available", "mock"}
    assert set(exported) == fields
    assert exported == {key: supplier[key] for key in fields}
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    assert result["data"]["customer_quotation"]["budget_fingerprint"] == request["budget"]["budget_fingerprint"]


@pytest.mark.parametrize("field,value", [
    ("vendor_id", None), ("quotation_id", []), ("offering_id", 123),
    ("service_type", {}), ("event_date", "invalid"), ("guest_count", True),
    ("quoted_total_cents", float("nan")), ("available", "true"), ("mock", False),
    ("event_id", "OTHER"), ("proposal_id", "OTHER"),
])
def test_invalid_required_projection_field_fails_safely(field, value):
    request = quotation_request()
    request["quotations"][0][field] = value
    result = make_worker().handle(request)
    assert result["status"] == "blocked" and result["data"] == {}
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("field", ["vendor_total_cents", "service_fee_cents", "contingency_cents",
    "tax_amount_cents", "estimated_total_cents", "budget_limit_cents", "over_budget_cents"])
@pytest.mark.parametrize("value", [True, -1, 10.5, "101", None])
def test_budget_amount_validation_with_matching_fingerprint(field, value):
    request = quotation_request()
    request["budget"][field] = value
    request["budget"]["budget_fingerprint"] = budget_fingerprint(request["budget"])
    result = make_worker().handle(request)
    assert result["status"] == "blocked" and result["data"] == {}
    assert field in result["message"]
    assert "integer" in result["message"] or "must be >=" in result["message"]


@pytest.mark.parametrize("field,value,message", [
    ("vendor_total_cents", 1006, "vendor total"),
    ("estimated_total_cents", 1208, "amount breakdown"),
    ("tax_amount_cents", 1, "limits or GST-inclusive tax"),
    ("over_budget_cents", 1, "limits or GST-inclusive tax"),
    ("budget_limit_cents", 1206, "limits or GST-inclusive tax"),
])
def test_budget_consistency_with_matching_fingerprint(field, value, message):
    request = quotation_request()
    request["budget"][field] = value
    request["budget"]["budget_fingerprint"] = budget_fingerprint(request["budget"])
    result = make_worker().handle(request)
    assert result["status"] == "blocked" and result["data"] == {}
    assert message in result["message"]
