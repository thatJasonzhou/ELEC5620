from pathlib import Path

import pytest

from src.api.app import build_workflow
from src.shared.selection_preferences import explicit_service_priorities


@pytest.fixture
def workflow(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLANNER_LLM_MODE", "mock")
    monkeypatch.setenv("ELEC5620_DB_PATH", str(tmp_path / "procurement.sqlite3"))
    monkeypatch.setenv("SUPPLIER_PORTAL_DB_PATH", str(tmp_path / "supplier.sqlite3"))
    return build_workflow()


def quote_with_preference(workflow, preference, budget=20000):
    event = workflow.handle_message(event_id=None, message=(
        "I need a conference in Sydney on 16 December 2026 from 9 am to 5 pm "
        f"for 50 guests. My budget is AUD {budget}. I only need a venue. {preference}"
    ))
    identity = event["event_id"]
    workflow.confirm_plan(identity)
    waiting = workflow.request_vendor_quotations(identity)
    for request in waiting["supplier_requests"]:
        workflow.supplier_portal.respond_to_quote_request(
            request["request_id"], available=True,
            quoted_total_cents=request["catalogue_estimate_cents"],
        )
    return waiting, workflow.get_event(identity)


@pytest.mark.parametrize(("preference", "priority", "expected"), [
    ("I want the best venue.", "highest_rating", "V-VENUE-004"),
    ("I want the cheapest venue.", "lowest_price", "V-VENUE-001"),
])
def test_priority_reaches_shortlist_and_final_choice(workflow, preference, priority, expected):
    waiting, final = quote_with_preference(workflow, preference)
    assert final["requirements"]["service_priorities"]["venue"] == priority
    assert expected in {r["vendor_id"] for r in waiting["supplier_requests"]}
    # Quality shortlists also retain the cheapest quote for budget recovery.
    assert "V-VENUE-001" in {r["vendor_id"] for r in waiting["supplier_requests"]}
    assert final["stage"] == "quotation"
    chosen, = final["customer_quotation"]["vendor_cost_breakdown"]
    assert chosen["vendor_id"] == expected
    assert chosen["recommendation_reason"]
    assert chosen["selection_source"] in {"ai", "preference_rule", "fallback_rule"}


def test_over_budget_quality_choice_selects_best_affordable_and_explains(workflow):
    _, final = quote_with_preference(workflow, "I want the best venue.", budget=5000)
    assert final["stage"] == "quotation"
    chosen, = final["customer_quotation"]["vendor_cost_breakdown"]
    assert chosen["vendor_id"] == "V-VENUE-003"  # 4.7; 4.9 exceeds the complete budget.
    assert final["budget"]["within_budget"] is True
    assert any("Budget trade-off" in note for note in final["selection_notes"])


def test_quality_still_applies_when_model_fails_final_comparison(workflow):
    event = workflow.handle_message(event_id=None, message=(
        "I need a conference in Sydney on 16 December 2026 from 9 am to 5 pm "
        "for 50 guests. My budget is AUD 20000. I only need a venue. I want the best venue."
    ))
    identity = event["event_id"]
    workflow.confirm_plan(identity)
    waiting = workflow.request_vendor_quotations(identity)
    for request in waiting["supplier_requests"]:
        workflow.supplier_portal.respond_to_quote_request(request["request_id"], available=True,
            quoted_total_cents=request["catalogue_estimate_cents"])
    workflow._procurement.llm.complete = lambda messages: "not valid JSON"
    final = workflow.get_event(identity)
    chosen, = final["customer_quotation"]["vendor_cost_breakdown"]
    assert chosen["vendor_id"] == "V-VENUE-004"
    assert chosen["selection_source"] == "fallback_rule"
    assert final["quotation_rankings"][0]["data"]["fallback_used"] is True


@pytest.mark.parametrize(("message", "expected"), [
    ("I want the highest-rated venue.", {"venue": "highest_rating"}),
    ("I want the best venue.", {"venue": "highest_rating"}),
    ("场地质量优先。", {"venue": "highest_rating"}),
    ("I want the cheapest venue.", {"venue": "lowest_price"}),
    ("Photography quality matters. I also need a venue.", {}),
])
def test_only_explicit_venue_priorities_are_normalised(message, expected):
    assert explicit_service_priorities(message) == expected


@pytest.mark.parametrize(("preference", "priority", "expected"), [
    ("Please prioritise the highest catalogue rating over the lowest price, while staying within my total budget.", "highest_rating", "V-VENUE-004"),
    ("Please prioritise the lowest price over the highest catalogue rating.", "lowest_price", "V-VENUE-001"),
    ("I want the highest-rated venue over the cheapest venue.", "highest_rating", "V-VENUE-004"),
])
def test_following_sentence_and_rejected_alternative_reach_final_choice(workflow, preference, priority, expected):
    waiting, final = quote_with_preference(workflow, preference)
    assert final["requirements"]["service_priorities"]["venue"] == priority
    assert expected in {r["vendor_id"] for r in waiting["supplier_requests"]}
    chosen, = final["customer_quotation"]["vendor_cost_breakdown"]
    assert chosen["vendor_id"] == expected


@pytest.mark.parametrize("message", [
    "I need a venue. Photography quality first.",
    "Photography quality matters. I also need a venue.",
    "I need a venue. Thanks for helping. Lowest price please.",
])
def test_venue_context_does_not_leak_to_other_services_or_unrelated_sentences(message):
    assert explicit_service_priorities(message) == {}
