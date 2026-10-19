"""Offline tests for KAN-19 Agent quotation handoff."""
import json
from pathlib import Path

import pytest

from src.agents.vendor_procurement_manager import VendorProcurementManagerAgent
from src.llm import MockLLMClient
from src.services.vendor_procurement_service import VendorProcurementService
from src.services.vendor_quotation_service import MockVendorQuotationService, NoQuotationScenarioError

ROOT = Path(__file__).resolve().parents[2]
REQUEST = {"event_id": "EV001", "proposal_id": "P-001", "service_type": "catering",
           "event_date": "2026-12-05", "guest_count": 120, "location": "Melbourne"}


@pytest.fixture(scope="module")
def vendors():
    return VendorProcurementService.from_json_file(ROOT / "data/vendor_catalog.json")


@pytest.fixture
def quotes():
    return MockVendorQuotationService.from_json_file(ROOT / "data/mock_vendor_quotations.json")


def make_agent(vendors, quotes):
    llm = MockLLMClient()
    llm.set_exception(AssertionError("quotations must not call the LLM"))
    return VendorProcurementManagerAgent(llm, vendors, quotes)


def test_accepted_only_and_pending_reason_preserved(vendors, quotes):
    agent = make_agent(vendors, quotes)
    env = agent.request_quotations(dict(REQUEST))
    assert env["status"] == "success"
    assert env["agent"] == "procurement" and env["event_id"] == "EV001" and env["timestamp"]
    quotation, = env["data"]["quotations"]
    required = {"event_id", "proposal_id", "quotation_id", "vendor_id", "service_type",
                "quoted_total_cents", "available", "recommendation_reason", "offering_id",
                "event_date", "guest_count", "scenario_id", "mock"}
    assert required <= quotation.keys()
    assert quotation["vendor_id"] == "V-CAT-001" and quotation["available"] is True
    assert quotation["mock"] is True and quotation["quoted_total_cents"] == 1850000
    assert quotation["proposal_id"] == "P-001" and quotation["quotation_id"].startswith("MQ-")
    pending = next(r for r in env["data"]["supplier_replies"] if r["status"] == "pending")
    assert pending["vendor_id"] == "V-CAT-002" and pending["available"] is None
    assert "not replied" in pending["reason"]
    assert agent.llm.calls == []


@pytest.mark.parametrize("overrides,reply_status", [
    ({"service_type": "photography", "location": "Sydney", "guest_count": 80}, "rejected"),
    ({"guest_count": 80}, "unconfigured"),
    ({"min_rating": 5}, None), ({"location": "Brisbane"}, None),
])
def test_no_confirmed_quotes_block(vendors, quotes, overrides, reply_status):
    agent = make_agent(vendors, quotes)
    env = agent.request_quotations({**REQUEST, **overrides})
    assert env["status"] == "blocked" and env["data"]["quotations"] == []
    if reply_status:
        assert any(r["status"] == reply_status for r in env["data"]["supplier_replies"])
    assert env["message"] and agent.llm.calls == []


def test_pending_only_blocks(vendors, quotes):
    pending = next(s for s in quotes.scenarios if s["reply"] == "pending")
    agent = make_agent(vendors, MockVendorQuotationService([pending]))
    env = agent.request_quotations(dict(REQUEST))
    assert env["status"] == "blocked" and not env["data"]["quotations"]
    assert {r["status"] for r in env["data"]["supplier_replies"]} == {"pending", "unconfigured"}


@pytest.mark.parametrize("field", ["event_id", "proposal_id", "service_type", "event_date", "guest_count", "location"])
def test_missing_fields_need_input(vendors, quotes, field):
    agent = make_agent(vendors, quotes)
    request = {k: v for k, v in REQUEST.items() if k != field}
    env = agent.request_quotations(request)
    assert env["status"] == "needs_input" and field in env["message"]
    if field == "event_id":
        assert env["event_id"] is None
    assert agent.llm.calls == []


@pytest.mark.parametrize("overrides", [
    {"proposal_id": None}, {"proposal_id": " "}, {"event_id": False},
    {"guest_count": True}, {"guest_count": -1}, {"event_date": "2026-02-30"},
    {"min_rating": float("nan")},
])
def test_invalid_input_needs_input(vendors, quotes, overrides):
    assert make_agent(vendors, quotes).request_quotations({**REQUEST, **overrides})["status"] == "needs_input"


@pytest.mark.parametrize("payload", [None, []])
def test_non_dict_request_errors(vendors, quotes, payload):
    env = make_agent(vendors, quotes).request_quotations(payload)
    assert env["status"] == "error" and env["event_id"] is None


def test_missing_injection_is_error(vendors):
    agent = VendorProcurementManagerAgent(MockLLMClient(), vendors)
    assert agent.request_quotations(dict(REQUEST))["status"] == "error"


def test_wrong_injection_type(vendors):
    with pytest.raises(TypeError, match="quotation_service"):
        VendorProcurementManagerAgent(MockLLMClient(), vendors, object())


def test_supplier_price_replaces_estimate_without_reusing_price_rank(vendors, quotes):
    scenario = dict(next(s for s in quotes.scenarios if s["reply"] == "accepted"))
    scenario["quoted_total_cents"] = 1900000
    scenario["reason"] = "MOCK: final supplier quote differs from catalogue."
    env = make_agent(vendors, MockVendorQuotationService([scenario])).request_quotations(dict(REQUEST))
    quotation, = env["data"]["quotations"]
    assert quotation["quoted_total_cents"] == 1900000
    assert "19,000.00" in quotation["recommendation_reason"]
    assert "18,500.00" not in quotation["recommendation_reason"]
    assert "lowest_price" not in quotation["recommendation_reason"]


@pytest.mark.parametrize("override", [
    {"mock": False}, {"mock": 1}, {"available": 1}, {"available": False},
    {"status": "unknown"}, {"status": []}, {"quoted_total_cents": True},
    {"quoted_total_cents": 1.5}, {"quoted_total_cents": -1}, {"quoted_total_cents": None},
    {"quotation_id": ""}, {"scenario_id": ""}, {"reason": " "},
    {"event_id": "OTHER"}, {"proposal_id": "OTHER"}, {"vendor_id": "OTHER"},
    {"offering_id": "OTHER"}, {"event_date": "2026-12-06"}, {"guest_count": 80},
])
def test_invalid_reply_never_released(vendors, quotes, monkeypatch, override):
    original = quotes.request_quotation
    def altered(**request):
        reply = original(**request)
        return {**reply, **override} if reply["status"] == "accepted" else reply
    monkeypatch.setattr(quotes, "request_quotation", altered)
    env = make_agent(vendors, quotes).request_quotations(dict(REQUEST))
    assert env["status"] == "error" and env["data"] == {}


def test_non_dict_reply_errors(vendors, quotes, monkeypatch):
    monkeypatch.setattr(quotes, "request_quotation", lambda **request: [])
    assert make_agent(vendors, quotes).request_quotations(dict(REQUEST))["status"] == "error"


@pytest.mark.parametrize("failure,status", [
    (NoQuotationScenarioError("missing preset"), "blocked"),
    (ValueError("invalid supplier response"), "error"),
    (RuntimeError("external failure"), "error"), (OSError("transport failure"), "error"),
])
def test_missing_preset_is_distinct_from_service_failure(vendors, quotes, monkeypatch, failure, status):
    def fail(**request):
        raise failure
    monkeypatch.setattr(quotes, "request_quotation", fail)
    env = make_agent(vendors, quotes).request_quotations(dict(REQUEST))
    assert env["status"] == status
    assert env["data"].get("quotations", []) == []


def two_accepted(quotes):
    first = dict(next(s for s in quotes.scenarios if s["reply"] == "accepted"))
    second = dict(next(s for s in quotes.scenarios if s["reply"] == "pending"))
    first.update(quoted_total_cents=10000, reason="MOCK quoted 100 AUD")
    second.update(reply="accepted", quoted_total_cents=20000, reason="MOCK quoted 200 AUD")
    return MockVendorQuotationService([first, second])


def test_sort_uses_supplier_prices(vendors, quotes):
    env = make_agent(vendors, two_accepted(quotes)).request_quotations(dict(REQUEST))
    assert env["status"] == "success"
    assert [(q["vendor_id"], q["quoted_total_cents"]) for q in env["data"]["quotations"]] == [
        ("V-CAT-001", 10000), ("V-CAT-002", 20000)]


def test_duplicate_quote_ids_fail_closed(vendors, quotes, monkeypatch):
    service = two_accepted(quotes)
    original = service.request_quotation
    def duplicate(**request):
        return {**original(**request), "quotation_id": "DUPLICATE"}
    monkeypatch.setattr(service, "request_quotation", duplicate)
    env = make_agent(vendors, service).request_quotations(dict(REQUEST))
    assert env["status"] == "error" and env["data"] == {}


def test_legacy_handle_and_two_argument_constructor_still_work(vendors):
    answer = json.dumps({"recommendations": [{"vendor_id": "V-CAT-002", "offering_id": "V-CAT-002-O1",
                                               "basis_codes": ["lowest_price"], "reason": "Lowest catalogue estimate."}]})
    agent = VendorProcurementManagerAgent(MockLLMClient(answer), vendors)
    env = agent.handle({k: v for k, v in REQUEST.items() if k != "proposal_id"})
    assert env["status"] == "success" and set(env["data"]) == {"recommendations"}
