"""Activity-level Procurement contract: at most five services, three enquiries each."""
from copy import deepcopy

import pytest

from examples.event_procurement_example import SERVICE_TYPES, make_event_demo
from src.llm import LLMError
from src.services.vendor_quotation_service import NoQuotationScenarioError


def batch_ref(prepared):
    return {k: prepared["data"][k] for k in ("event_id", "proposal_id", "batch_id")}


def test_five_services_get_15_enquiries_and_five_selected_quotes():
    agent, supplier, request = make_event_demo()
    result = agent.procure_services(request)
    assert result["status"] == "success"
    data = result["data"]
    assert data["selection_complete"] and data["required_services"] == list(SERVICE_TYPES)
    assert len(data["quotations"]) == len(data["selected_quotation_ids"]) == 5
    assert len(data["candidate_quotations"]) == 10
    assert len(supplier.calls) == 15
    assert all(call["vendor_id"] in ("A", "B", "C") for call in supplier.calls)
    assert all(q["vendor_id"] == "B" for q in data["quotations"])
    assert len({q["quotation_id"] for q in data["quotations"]}) == 5
    assert len({q["offering_id"] for q in data["quotations"]}) == 5
    assert len(agent.llm.calls) == 10
    for result in data["service_results"]:
        assert [r["vendor_id"] for r in result["data"]["quotation_ranking"]] == ["B", "A"]
        assert result["data"]["recommendations"][0]["vendor_id"] == "A"


@pytest.mark.parametrize("services", [[], None, "photography",
    [{"service_type": s} for s in SERVICE_TYPES + ("transport",)],
    [{"service_type": "photography"}, {"service_type": " Photography "}],
    [{"service_type": "photography"}, None],
    [{"service_type": "photography", "event_id": "OTHER"}],
    [{"service_type": "photography", "proposal_id": "OTHER"}],
    [{"service_type": "photography", "min_rating": 6}],
    [{"service_type": "photography"}, {"service_type": "catering", "service_budget_cents": -1}],
])
def test_invalid_complete_service_list_fails_before_any_model_or_supplier_call(services):
    agent, supplier, request = make_event_demo()
    result = agent.procure_services({**request, "services": services})
    assert result["status"] == "needs_input"
    assert not agent.llm.calls and not supplier.calls


def test_single_service_is_supported_by_the_same_event_entry():
    agent, supplier, request = make_event_demo(services=("photography",))
    result = agent.procure_services(request)
    assert result["status"] == "success" and len(result["data"]["quotations"]) == 1
    assert len(supplier.calls) == 3


def test_one_pending_reply_prevents_final_selection_and_second_stage_models(monkeypatch):
    agent, supplier, request = make_event_demo()
    original = supplier.request_quotation
    def pending(**kwargs):
        result = original(**kwargs)
        if kwargs["offering_id"] == "A-catering":
            result.update(status="pending", available=None, quoted_total_cents=None)
        return result
    monkeypatch.setattr(supplier, "request_quotation", pending)
    result = agent.procure_services(request)
    assert result["status"] == "blocked"
    assert not result["data"]["selection_complete"]
    assert result["data"]["quotations"] == result["data"]["selected_quotation_ids"] == []
    assert len(agent.llm.calls) == 5


def test_unconfigured_reply_stays_pending_instead_of_using_catalogue_price(monkeypatch):
    agent, supplier, request = make_event_demo(services=("photography",))
    original = supplier.request_quotation
    def missing(**kwargs):
        if kwargs["vendor_id"] == "A":
            raise NoQuotationScenarioError("no preset")
        return original(**kwargs)
    monkeypatch.setattr(supplier, "request_quotation", missing)
    result = agent.procure_services(request)
    assert result["status"] == "blocked" and not result["data"]["quotations"]
    a = result["data"]["service_rounds"][0]["supplier_replies"][0]
    assert a["status"] == "pending" and a["quoted_total_cents"] is None


def test_one_service_all_rejected_prevents_partial_financial_handoff(monkeypatch):
    agent, supplier, request = make_event_demo()
    original = supplier.request_quotation
    def reject(**kwargs):
        result = original(**kwargs)
        if kwargs["offering_id"].endswith("-venue"):
            result.update(status="rejected", available=False, quoted_total_cents=None)
        return result
    monkeypatch.setattr(supplier, "request_quotation", reject)
    result = agent.procure_services(request)
    assert result["status"] == "blocked"
    assert result["data"]["quotations"] == [] and not result["data"]["selection_complete"]
    assert any(r["service_type"] == "venue" and r["status"] == "blocked"
               for r in result["data"]["service_results"])


def test_future_ui_path_reuses_submission_and_comparison_without_mock_provider():
    agent, supplier, request = make_event_demo()
    prepared = agent.prepare_event_enquiries(request)
    assert prepared["status"] == "success" and not supplier.calls
    for current in prepared["data"]["service_rounds"]:
        for enquiry in current["enquiries"]:
            reply = enquiry["reply"]
            result = agent.submit_quotation_reply({
                **{k: reply[k] for k in ("event_id", "proposal_id")},
                "round_id": current["round_id"], "enquiry_id": enquiry["enquiry_id"],
                "status": "accepted", "mock": True,
                "quoted_total_cents": {"A": 130000, "B": 95000, "C": 110000}[reply["vendor_id"]],
                "reason": "MOCK supplier form input",
            })
            assert result["status"] == "success"
    compared = agent.compare_event_quotations(batch_ref(prepared))
    assert compared["status"] == "success" and len(compared["data"]["quotations"]) == 5
    assert all(q["vendor_id"] == "B" for q in compared["data"]["quotations"])
    assert supplier.calls == []


def test_retry_skips_terminal_supplier_replies():
    agent, supplier, request = make_event_demo()
    prepared = agent.prepare_event_enquiries(request)
    lookup = batch_ref(prepared)
    assert agent.request_event_quotations(lookup)["status"] == "success"
    assert len(supplier.calls) == 15
    assert agent.request_event_quotations(lookup)["status"] == "success"
    assert len(supplier.calls) == 15


@pytest.mark.parametrize("changes", [{"event_id": "OTHER"}, {"proposal_id": "OTHER"}, {"batch_id": "UNKNOWN"}])
def test_batch_identity_cannot_be_changed(changes):
    agent, supplier, request = make_event_demo()
    prepared = agent.prepare_event_enquiries(request)
    lookup = {**batch_ref(prepared), **changes}
    assert agent.request_event_quotations(lookup)["status"] == "blocked"
    assert agent.compare_event_quotations(lookup)["status"] == "blocked"
    assert supplier.calls == []


def test_low_level_sixth_service_is_also_rejected_but_reenquiry_reuses_a_slot():
    agent, _, request = make_event_demo(services=SERVICE_TYPES + ("transport",))
    for s in SERVICE_TYPES:
        result = agent.prepare_enquiries({**request, "service_type": s})
        assert result["status"] == "success"
    assert agent.prepare_enquiries({**request, "service_type": "photography"})["status"] == "success"
    before = len(agent.llm.calls)
    result = agent.prepare_enquiries({**request, "service_type": "transport"})
    assert result["status"] == "needs_input"
    assert len(agent.llm.calls) == before
    # A new proposal version has its own bounded service list.
    result = agent.prepare_enquiries({**request, "proposal_id": "P-NEW", "service_type": "transport"})
    assert result["status"] == "success"


def test_existing_slots_and_new_batch_are_validated_together():
    agent, supplier, request = make_event_demo(services=SERVICE_TYPES + ("transport",))
    assert agent.prepare_enquiries({**request, "service_type": "photography"})["status"] == "success"
    before = len(agent.llm.calls)
    other_five = [{"service_type": s} for s in SERVICE_TYPES[1:] + ("transport",)]
    result = agent.prepare_event_enquiries({**request, "services": other_five})
    assert result["status"] == "needs_input" and len(agent.llm.calls) == before
    assert supplier.calls == []


def test_invalid_mock_reply_cannot_become_a_selected_quote(monkeypatch):
    agent, supplier, request = make_event_demo()
    original = supplier.request_quotation
    def bad(**kwargs):
        result = original(**kwargs)
        result["event_id"] = "OTHER"
        return result
    monkeypatch.setattr(supplier, "request_quotation", bad)
    result = agent.procure_services(request)
    assert result["status"] == "error"
    assert not result["data"]["selection_complete"] and not result["data"]["quotations"]
    assert len(agent.llm.calls) == 5


def test_initial_model_error_never_sends_supplier_enquiries():
    agent, supplier, request = make_event_demo()
    agent.llm.set_exception(LLMError("unavailable"))
    result = agent.procure_services(request)
    assert result["status"] == "error" and not supplier.calls


def test_batch_snapshot_is_detached_and_round_subset_cannot_drop_services():
    agent, supplier, request = make_event_demo()
    prepared = agent.prepare_event_enquiries(request)
    lookup = batch_ref(prepared)
    prepared["data"]["round_ids"].clear()
    prepared["data"]["required_services"].clear()
    collected = agent.request_event_quotations(lookup)
    assert collected["status"] == "success" and len(supplier.calls) == 15
    result = agent.compare_event_quotations({**lookup, "round_ids": []})
    assert result["status"] == "success" and len(result["data"]["quotations"]) == 5
