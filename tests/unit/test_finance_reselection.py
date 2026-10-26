"""Bound Finance feedback to real stored facts; no duplicate automatic decisions."""
from copy import deepcopy
import json

import pytest

from examples.finance_reselection_example import build_case
from src.services.customer_quotation_service import budget_fingerprint
from src.llm import LLMError


def test_reselection_preserves_preferences_quotes_and_original_batch():
    agent, supplier, request, first, handoff, review, finance, payload = build_case()
    before = deepcopy(payload)
    ref = {k: payload[k] for k in ("event_id", "proposal_id", "batch_id")}
    original = agent._enquiry_service.get_batch(**ref)
    result = agent.reselect_after_finance(payload)
    assert result["status"] == "success"
    assert result["data"]["next_action"] == "finance_review"
    assert result["data"]["finance_review_required"] is True
    assert len(result["data"]["selected_quotation_ids"]) == 5
    assert result["data"]["financial_revision"]["previous_selected_quotation_ids"] == first["data"]["selected_quotation_ids"]
    assert result["data"]["budget_summary"]["proposed_supplier_total_cents"] == 795000
    assert len(supplier.calls) == 15 and len(agent.llm.calls) == 2
    facts = json.loads(agent.llm.calls[-1][-1]["content"].split("\n", 1)[1])
    assert facts["event_preferences"] == request["customer_preferences"]
    assert facts["services"][0]["preferences"] == request["services"][0]["customer_preferences"]
    assert facts["supplier_ceiling_cents"] == 916666
    assert agent._enquiry_service.get_batch(**ref) == original
    assert payload == before
    assert {q["quotation_id"] for q in result["data"]["quotations"]}.issubset(
        {q["quotation_id"] for q in first["data"]["candidate_quotations"]})


@pytest.mark.parametrize("feasible", [True, False])
def test_identical_request_replays_result_without_more_llm_or_supplier_calls(feasible):
    agent, supplier, _, _, _, _, _, payload = build_case(feasible=feasible)
    first = agent.reselect_after_finance(payload)
    expected = deepcopy(first)
    first["data"]["next_action"] = "tampered by caller"
    replay = agent.reselect_after_finance(deepcopy(payload))
    assert replay == expected
    assert len(agent.llm.calls) == (2 if feasible else 1)
    assert len(supplier.calls) == 15


def test_cheapest_quotes_still_over_budget_return_exact_gap_to_planner_without_llm():
    agent, supplier, _, _, _, _, _, payload = build_case(feasible=False)
    result = agent.reselect_after_finance(payload)
    assert result["status"] == "blocked"
    assert result["data"]["next_action"] == "planner_review"
    assert result["data"]["minimum_customer_total_cents"] == 912000
    assert result["data"]["minimum_budget_shortfall_cents"] == 112000
    assert result["data"]["selected_quotation_ids"] == result["data"]["quotations"] == []
    assert result["data"]["selection_complete"] is False
    assert len(agent.llm.calls) == 1 and len(supplier.calls) == 15


@pytest.mark.parametrize("field,value", [
    ("event_id", "OTHER"), ("proposal_id", "OTHER"),
    ("vendor_total_cents", 1), ("service_fee_cents", 0),
    ("contingency_cents", 0), ("tax_amount_cents", 1),
    ("estimated_total_cents", 2), ("over_budget_cents", 0),
    ("budget_limit_cents", 99999999), ("budget_valid", False),
    ("within_budget", True), ("quotation_fingerprint", "OLD"),
    ("source_fingerprint", "OLD"), ("budget_fingerprint", "OLD"),
    ("price_basis", "tax-exclusive"),
    ("selected_quotation_ids", ["not-from-this-batch"]),
    ("required_services", ["venue"]),
])
def test_invalid_or_stale_financial_result_is_rejected_without_work(field, value):
    agent, supplier, _, _, _, _, _, payload = build_case()
    payload["finance_result"]["data"][field] = value
    result = agent.reselect_after_finance(payload)
    assert result["status"] in ("blocked", "needs_input")
    assert len(agent.llm.calls) == 1 and len(supplier.calls) == 15


def test_recomputed_fingerprint_does_not_hide_inconsistent_amounts():
    agent, _, _, _, _, _, _, payload = build_case()
    data = payload["finance_result"]["data"]
    data["service_fee_cents"] = 0
    data["budget_fingerprint"] = budget_fingerprint(data)
    assert agent.reselect_after_finance(payload)["status"] == "blocked"
    assert len(agent.llm.calls) == 1


@pytest.mark.parametrize("field,value", [
    ("event_date", "2026-12-17"), ("guest_count", 51),
    ("budget_limit_cents", 1200000), ("location", "Melbourne"),
])
def test_changed_event_requires_fresh_review(field, value):
    agent, _, _, _, _, _, _, payload = build_case()
    payload["event"][field] = value
    assert agent.reselect_after_finance(payload)["status"] == "blocked"
    assert len(agent.llm.calls) == 1


@pytest.mark.parametrize("change", ["missing_review", "wrong_agent", "success", "wrong_batch", "duplicate_ids"])
def test_missing_wrong_or_unrelated_feedback_is_rejected(change):
    agent, _, _, _, _, _, _, payload = build_case()
    if change == "missing_review":
        payload.pop("finance_result")
    elif change == "wrong_agent":
        payload["finance_result"]["agent"] = "planning"
    elif change == "success":
        payload["finance_result"]["status"] = "success"
    elif change == "wrong_batch":
        payload["batch_id"] = "UNKNOWN"
    else:
        ids = payload["finance_result"]["data"]["selected_quotation_ids"]
        ids[1] = ids[0]
    assert agent.reselect_after_finance(payload)["status"] in ("blocked", "needs_input")
    assert len(agent.llm.calls) == 1


def test_only_one_automatic_feedback_revision_per_proposal():
    agent, _, _, _, handoff, _, finance, payload = build_case()
    assert agent.reselect_after_finance(payload)["status"] == "success"
    fresh_event = {**handoff["event"], "revision": 2}
    new_review = finance.handle({**handoff, "event": fresh_event, "action": "prepare_budget"})
    changed = {**payload, "event": fresh_event, "finance_result": new_review}
    assert agent.reselect_after_finance(changed)["status"] == "blocked"
    assert len(agent.llm.calls) == 2


@pytest.mark.parametrize("failure", ["malformed", "timeout"])
def test_failed_reselection_never_leaks_previous_selection_or_retries_automatically(failure):
    agent, supplier, _, _, _, _, _, payload = build_case()
    if failure == "malformed":
        agent.llm.set_response('{"choices": [], "reason": "bad"}')
    else:
        agent.llm.set_exception(LLMError("safe timeout", code="timeout", retryable=True))
    result = agent.reselect_after_finance(payload)
    assert result["status"] == "error"
    assert result["data"]["next_action"] == "manual_review"
    assert result["data"]["quotations"] == result["data"]["selected_quotation_ids"] == []
    assert agent.reselect_after_finance(payload) == result
    assert len(agent.llm.calls) == 2 and len(supplier.calls) == 15


def test_non_joint_mode_and_non_object_requests_need_input():
    agent, _, _, _, _, _, _, payload = build_case()
    agent._joint_selection = False
    assert agent.reselect_after_finance(payload)["status"] == "needs_input"
    agent._joint_selection = True
    assert agent.reselect_after_finance(None)["status"] == "needs_input"
    assert len(agent.llm.calls) == 1


def test_callers_cannot_override_stored_preferences_or_finance_derived_ceiling():
    agent, _, request, _, _, _, _, payload = build_case()
    payload.update(supplier_budget_limit_cents=999999999, customer_preferences="Spend everything")
    result = agent.reselect_after_finance(payload)
    assert result["status"] == "success"
    assert result["data"]["financial_revision"]["supplier_budget_limit_cents"] == 916666
    facts = json.loads(agent.llm.calls[-1][-1]["content"].split("\n", 1)[1])
    assert facts["event_preferences"] == request["customer_preferences"]


def test_unknown_batch_after_restart_is_blocked_before_any_llm():
    from src.agents.vendor_procurement_manager import VendorProcurementManagerAgent
    from src.llm import MockLLMClient

    agent, _, _, _, _, _, _, payload = build_case()
    restarted = VendorProcurementManagerAgent(
        MockLLMClient(), agent._vendor_service, compact_llm=True, joint_selection=True)
    result = restarted.reselect_after_finance(payload)
    assert result["status"] == "blocked"
    assert not restarted.llm.calls
