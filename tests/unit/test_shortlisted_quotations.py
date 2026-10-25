"""Behaviour tests for isolated supplier enquiry rounds (KAN-36)."""
from copy import deepcopy
import json

import pytest

from examples.shortlisted_quotation_example import (
    DEMO_REQUEST, make_demo_agent, model_response, submit_demo_replies,
)
from src.llm import LLMError, MockLLMClient
from src.services.procurement_record_service import ProcurementRecordService, ProcurementStorageError


def lookup(prepared):
    return {**{n: prepared["data"]["context"][n] for n in ("event_id", "proposal_id")},
            "round_id": prepared["data"]["round_id"]}


def reply(prepared, vendor="A", **changes):
    enquiry = next(e for e in prepared["data"]["enquiries"] if e["reply"]["vendor_id"] == vendor)
    return {**lookup(prepared), "enquiry_id": enquiry["enquiry_id"], "mock": True,
            "status": "accepted", "quoted_total_cents": 130000,
            "reason": "MOCK supplier confirmation", **changes}


@pytest.fixture
def opened():
    agent = make_demo_agent()
    prepared = agent.prepare_enquiries(dict(DEMO_REQUEST))
    assert prepared["status"] == "success"
    return agent, prepared


def test_only_top_three_get_enquiries_and_no_price_is_assumed(opened):
    agent, prepared = opened
    data = prepared["data"]
    assert [e["reply"]["vendor_id"] for e in data["enquiries"]] == ["A", "B", "C"]
    assert all(r["status"] == "pending" and r["quoted_total_cents"] is None
               for r in data["supplier_replies"])
    assert not data["quotations"]
    data["enquiries"][0]["reply"]["quoted_total_cents"] = 1
    assert agent.get_enquiry_round(lookup(prepared))["data"]["supplier_replies"][0]["quoted_total_cents"] is None


def test_missing_reply_blocks_selection_without_calling_llm(opened):
    agent, prepared = opened
    agent.submit_quotation_reply(reply(prepared))
    result = agent.compare_quotations(lookup(prepared))
    assert result["status"] == "blocked"
    assert result["data"]["awaiting_replies"]
    assert not result["data"]["selected_quotations"]
    assert len(agent.llm.calls) == 1


def test_reply_prices_change_ranking_and_facts_are_backfilled(opened):
    agent, prepared = opened
    submit_demo_replies(agent, prepared)
    # Model's invented price/rating fields cannot overwrite supplier/catalog facts.
    raw = json.loads(model_response(["B", "A"], {"B": ["lowest_price"]}))
    raw["recommendations"][0].update(total_price_cents=1, quoted_total_cents=1, rating=5)
    agent.llm.set_response(json.dumps(raw))
    result = agent.compare_quotations(lookup(prepared))
    assert result["status"] == "success"
    ranking = result["data"]["quotation_ranking"]
    assert [r["vendor_id"] for r in ranking] == ["B", "A"]
    assert ranking[0]["quoted_total_cents"] == 95000
    assert ranking[1]["catalog_estimate_cents"] == 90000
    assert ranking[1]["quoted_total_cents"] == 130000
    assert ranking[1]["over_target_cents"] == 30000
    selected, = result["data"]["selected_quotations"]
    assert selected["vendor_id"] == "B" and selected["quoted_total_cents"] == 95000
    assert len(result["data"]["quotations"]) == 2
    prompt = agent.llm.calls[-1][1]["content"]
    assert '"total_price_cents": 130000' in prompt and '"catalog_estimate_cents": 90000' in prompt


@pytest.mark.parametrize("changes", [
    {"mock": False}, {"mock": 1}, {"status": "confirmed"},
    {"quoted_total_cents": True}, {"quoted_total_cents": 1.5},
    {"quoted_total_cents": -1}, {"quoted_total_cents": None},
    {"status": "pending", "quoted_total_cents": 100},
    {"status": "rejected", "quoted_total_cents": 100},
    {"available": False}, {"reason": ""},
])
def test_invalid_reply_never_becomes_a_quote(opened, changes):
    agent, prepared = opened
    result = agent.submit_quotation_reply(reply(prepared, **changes))
    assert result["status"] == "needs_input"
    assert not agent.get_enquiry_round(lookup(prepared))["data"]["quotations"]
    assert len(agent.llm.calls) == 1


@pytest.mark.parametrize("changes", [
    {"event_id": "OTHER"}, {"proposal_id": "OTHER"}, {"round_id": "OTHER"},
    {"enquiry_id": "OUTSIDE"}, {"vendor_id": "D"}, {"offering_id": "D-PHOTO"},
    {"event_date": "2026-12-17"}, {"guest_count": 51},
])
def test_reply_must_match_original_context(opened, changes):
    agent, prepared = opened
    assert agent.submit_quotation_reply(reply(prepared, **changes))["status"] == "blocked"
    assert not agent.get_enquiry_round(lookup(prepared))["data"]["quotations"]


def test_final_reply_is_idempotent_but_changed_price_requires_new_round(opened):
    agent, prepared = opened
    request = reply(prepared)
    first = agent.submit_quotation_reply(request)
    second = agent.submit_quotation_reply(request)
    assert first["data"] == second["data"]
    assert agent.submit_quotation_reply({**request, "quoted_total_cents": 1})["status"] == "blocked"
    assert agent.submit_quotation_reply({**request, "status": "rejected", "quoted_total_cents": None})["status"] == "blocked"


def test_pending_reply_can_later_accept(opened):
    agent, prepared = opened
    assert agent.submit_quotation_reply(reply(prepared, status="pending", quoted_total_cents=None))["status"] == "success"
    assert agent.submit_quotation_reply(reply(prepared))["status"] == "success"


def test_hard_limit_excludes_over_budget_quote_before_llm():
    agent = make_demo_agent(llm=MockLLMClient([
        model_response(["A", "B", "C"]), model_response(["B"], {"B": ["lowest_price"]})]))
    prepared = agent.prepare_enquiries({**DEMO_REQUEST, "budget_is_hard_limit": True})
    submit_demo_replies(agent, prepared)
    result = agent.compare_quotations(lookup(prepared))
    assert result["status"] == "success"
    assert [r["vendor_id"] for r in result["data"]["quotation_ranking"]] == ["B"]
    assert len(result["data"]["quotations"]) == 2  # Keep evidence of the excluded quote.
    assert [c["vendor_id"] for c in json.loads(agent.llm.calls[-1][1]["content"])["candidates"]] == ["B"]


def test_no_affordable_accepted_quote_blocks_without_model():
    agent = make_demo_agent()
    prepared = agent.prepare_enquiries({**DEMO_REQUEST, "budget_is_hard_limit": True, "service_budget_cents": 1})
    submit_demo_replies(agent, prepared)
    result = agent.compare_quotations(lookup(prepared))
    assert result["status"] == "blocked" and not result["data"]["selected_quotations"]
    assert len(agent.llm.calls) == 1


def test_all_rejected_blocks_without_model(opened):
    agent, prepared = opened
    for name in ["A", "B", "C"]:
        agent.submit_quotation_reply(reply(prepared, name, status="rejected", quoted_total_cents=None))
    assert agent.compare_quotations(lookup(prepared))["status"] == "blocked"
    assert len(agent.llm.calls) == 1


@pytest.mark.parametrize("response", [
    "not json", model_response(["D", "A"]), model_response(["A", "A"]),
    model_response(["B"]), model_response(["A", "B"], {"A": ["lowest_price"]}),
])
def test_invalid_model_ranking_releases_no_selection(opened, response):
    agent, prepared = opened
    submit_demo_replies(agent, prepared)
    agent.llm.set_response(response)
    result = agent.compare_quotations(lookup(prepared))
    assert result["status"] == "error"
    assert not result["data"]["quotation_ranking"] and not result["data"]["selected_quotations"]


def test_model_failure_preserves_replies_without_inventing_selection(opened):
    agent, prepared = opened
    submit_demo_replies(agent, prepared)
    agent.llm.set_exception(LLMError("unavailable"))
    result = agent.compare_quotations(lookup(prepared))
    assert result["status"] == "error" and len(result["data"]["quotations"]) == 2
    assert not result["data"]["selected_quotation_ids"]


@pytest.mark.parametrize("changes", [
    {"proposal_id": ""}, {"guest_count": True}, {"service_budget_cents": True},
    {"service_budget_cents": -1}, {"budget_is_hard_limit": "true"},
    {"budget_is_hard_limit": True, "service_budget_cents": None}, {"min_rating": 6},
])
def test_invalid_prepare_input_does_not_call_llm(changes):
    agent = make_demo_agent()
    assert agent.prepare_enquiries({**DEMO_REQUEST, **changes})["status"] == "needs_input"
    assert not agent.llm.calls


def test_incomplete_initial_ranking_creates_no_round():
    agent = make_demo_agent(llm=MockLLMClient(model_response(["A"])))
    result = agent.prepare_enquiries(dict(DEMO_REQUEST))
    assert result["status"] == "error" and not result["data"]


def test_new_round_has_new_quote_ids_and_old_context_is_detached(opened):
    agent, first = opened
    agent.llm.set_response(model_response(["A", "B", "C"]))
    second = agent.prepare_enquiries({**DEMO_REQUEST, "proposal_id": "P-NEW"})
    assert first["data"]["round_id"] != second["data"]["round_id"]
    assert first["data"]["enquiries"][0]["reply"]["quotation_id"] != second["data"]["enquiries"][0]["reply"]["quotation_id"]
    assert agent.get_enquiry_round({**lookup(first), "proposal_id": "P-NEW"})["status"] == "blocked"
    assert agent.get_enquiry_round(lookup(first))["data"]["context"]["proposal_id"] == DEMO_REQUEST["proposal_id"]


def test_storage_error_does_not_mark_reply_accepted(tmp_path, monkeypatch):
    records = ProcurementRecordService(tmp_path / "procurement.sqlite3")
    agent = make_demo_agent(record_service=records)
    prepared = agent.prepare_enquiries(dict(DEMO_REQUEST))
    def fail(_):
        raise ProcurementStorageError("unavailable")
    monkeypatch.setattr(records, "save_quotations", fail)
    assert agent.submit_quotation_reply(reply(prepared))["status"] == "error"
    assert not agent.get_enquiry_round(lookup(prepared))["data"]["quotations"]


def test_rounds_are_explicitly_process_local(opened):
    _, prepared = opened
    assert make_demo_agent().get_enquiry_round(lookup(prepared))["status"] == "blocked"
