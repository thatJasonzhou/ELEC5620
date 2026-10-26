"""Code shortlist, one actual-quote bundle decision, exact budget boundaries."""
from copy import deepcopy
import json

import pytest

from examples.event_procurement_example import make_event_demo, RecordingMockQuotations
from examples.shared_catalog_procurement_example import build_agent
from src.agents.vendor_procurement_manager import VendorProcurementManagerAgent
from src.llm import LLMError, MockLLMClient


def payload(messages):
    return json.loads(messages[-1]["content"].split("\n", 1)[1])


def choose_vendors(*vendors):
    def respond(messages):
        facts = payload(messages)
        choices = [next(row[0] for row in service["quotes"] if row[1].endswith(vendor))
                   for service, vendor in zip(facts["services"], vendors)]
        return json.dumps({"choices": choices, "reason": "Prioritise photography and save on other services."})
    return respond


def fixture(*, services=None, reply=None, quote_overrides=None, records=None, progress=None):
    options = {} if services is None else {"services": services}
    source, supplier, request = make_event_demo(**options)
    scenarios = deepcopy(supplier.scenarios)
    for scenario in scenarios:
        if scenario["offering_id"] in (quote_overrides or {}):
            scenario["quoted_total_cents"] = quote_overrides[scenario["offering_id"]]
    supplier = RecordingMockQuotations(scenarios)
    reply = choose_vendors(*(["B"] * len(request["services"]))) if reply is None else reply
    agent = VendorProcurementManagerAgent(
        MockLLMClient(reply), source._vendor_service, quotation_service=supplier,
        compact_llm=True, joint_selection=True, record_service=records,
        progress_callback=progress)
    return agent, supplier, request


def lookup(result):
    return {k: result["data"][k] for k in ("event_id", "proposal_id", "batch_id")}


def test_five_services_are_shortlisted_without_llm_then_compared_in_one_decision():
    events = []
    agent, supplier, request = fixture(progress=events.append)
    prepared = agent.prepare_event_enquiries(request)
    assert prepared["status"] == "success" and agent.llm.calls == [] and supplier.calls == []
    assert all(len(r["enquiries"]) == 3 for r in prepared["data"]["service_rounds"])
    assert {e["candidate"]["vendor_id"] for e in prepared["data"]["service_rounds"][0]["enquiries"]} == {"A", "B", "C"}
    ref = lookup(prepared)
    assert agent.request_event_quotations(ref)["status"] == "success"
    result = agent.compare_event_quotations(ref)
    assert result["status"] == "success" and result["data"]["selection_complete"]
    assert len(agent.llm.calls) == 1 and len(supplier.calls) == 15
    assert len(result["data"]["quotations"]) == 5
    facts = payload(agent.llm.calls[0])
    assert len(facts["services"]) == 5
    assert sum(len(s["quotes"]) for s in facts["services"]) == 10  # C declined.
    photo = facts["services"][0]
    assert sorted(row[2] for row in photo["quotes"]) == [95000, 130000]  # Not catalogue estimates.
    assert result["data"]["budget_summary"]["proposed_supplier_total_cents"] == 760000
    assert result["data"]["budget_summary"]["supplier_total_within_ceiling"] is None
    assert [e["stage"] for e in events if e["state"] == "submitted"] == ["comparison"]
    assert not supplier.calls[0]["vendor_id"] == "D"
    for service in result["data"]["service_results"]:
        assert service["data"]["ranking_scope"] == "selected_only"
        assert len(service["data"]["quotation_ranking"]) == 1
        assert len(service["data"]["unranked_quotation_ids"]) == 1


def test_soft_service_target_can_be_exceeded_using_savings_elsewhere():
    agent, _, request = fixture(
        services=("photography", "catering"), reply=choose_vendors("A", "B"),
        quote_overrides={"A-photography": 105000})
    request.update(budget_limit_cents=330000, supplier_budget_limit_cents=300000,
                   customer_preferences="Photography matters most; save on catering.")
    request["services"][0]["customer_preferences"] = "Prioritise photography quality."
    result = agent.procure_services(request)
    assert result["status"] == "success" and len(agent.llm.calls) == 1
    quotes = result["data"]["quotations"]
    assert [q["quoted_total_cents"] for q in quotes] == [105000, 190000]
    assert result["data"]["service_results"][0]["data"]["quotation_ranking"][0]["over_target_cents"] == 5000
    assert result["data"]["budget_summary"]["proposed_supplier_total_cents"] == 295000
    assert result["data"]["budget_summary"]["supplier_total_within_ceiling"] is True
    facts = payload(agent.llm.calls[0])
    assert facts["supplier_ceiling_cents"] == 300000
    assert facts["event_preferences"].startswith("Photography matters")
    assert facts["services"][0]["preferences"] == "Prioritise photography quality."


def test_expensive_catalogue_option_survives_shortlist_but_hard_actual_quote_limit_applies():
    agent, _, request = fixture(services=("photography",), reply=choose_vendors("B"))
    request["services"][0].update(service_budget_cents=100000, budget_is_hard_limit=True)
    prepared = agent.prepare_event_enquiries(request)
    assert any(e["candidate"]["vendor_id"] == "A" for e in prepared["data"]["service_rounds"][0]["enquiries"])
    ref = lookup(prepared)
    agent.request_event_quotations(ref)
    result = agent.compare_event_quotations(ref)
    assert result["status"] == "success"
    assert [row[2] for row in payload(agent.llm.calls[0])["services"][0]["quotes"]] == [95000]


def test_above_target_high_rating_option_is_not_removed_by_initial_price_cutoff():
    agent = build_agent(joint_selection=True)
    from examples.shared_catalog_procurement_example import event_request
    request = event_request(services=["photography"])
    request["services"][0]["service_budget_cents"] = 100000
    prepared = agent.prepare_event_enquiries(request)
    estimates = [e["candidate"]["total_price_cents"] for e in prepared["data"]["service_rounds"][0]["enquiries"]]
    assert 140000 in estimates and len(estimates) == 3 and not agent.llm.calls


@pytest.mark.parametrize("reply", [
    '{"choices":[],"reason":"missing"}',
    '{"choices":[true],"reason":"bool is not an index"}',
    '{"choices":[99],"reason":"unknown"}',
    '{"choices":[0,0],"reason":"too many"}',
    '{"choices":[0],"reason":""}',
    '{"choices":[0],"reason":"ok","price":1}',
    '{"choices":[0],"choices":[1],"reason":"duplicate key"}',
])
def test_malformed_decision_never_returns_a_financial_selection(reply):
    agent, _, request = fixture(services=("photography",), reply=reply)
    result = agent.procure_services(request)
    assert result["status"] == "error" and not result["data"]["selection_complete"]
    assert result["data"]["quotations"] == result["data"]["selected_quotation_ids"] == []
    assert result["data"]["service_results"][0]["data"]["llm_error"]["code"] == "response_format"


def test_overall_ceiling_is_enforced_without_silently_replacing_llm_choice():
    agent, supplier, request = fixture(services=("photography",), reply=choose_vendors("A"))
    request["budget_limit_cents"] = 100000
    result = agent.procure_services(request)
    assert result["status"] == "blocked" and len(agent.llm.calls) == 1
    assert not result["data"]["selection_complete"] and result["data"]["quotations"] == []
    assert result["data"]["proposed_quotation_ids"]
    assert result["data"]["budget_summary"]["proposed_supplier_total_cents"] == 130000
    assert len(supplier.calls) == 3


def test_no_feasible_combination_does_not_call_model():
    agent, supplier, request = fixture(services=("photography",))
    request["supplier_budget_limit_cents"] = 94000
    result = agent.procure_services(request)
    assert result["status"] == "blocked" and not agent.llm.calls and len(supplier.calls) == 3
    assert result["data"]["budget_summary"]["minimum_supplier_total_cents"] == 95000


def test_failure_after_success_returns_no_old_selection_or_automatic_mock_fallback():
    answers = iter([json.dumps({"choices": [1], "reason": "Quality choice."}), None])
    def respond(_):
        answer = next(answers)
        if answer is None:
            raise LLMError("safe timeout", code="timeout", retryable=True)
        return answer
    agent, supplier, request = fixture(services=("photography",), reply=respond)
    first = agent.procure_services(request)
    assert first["status"] == "success"
    second = agent.compare_event_quotations(lookup(first))
    assert second["status"] == "error" and second["data"]["quotations"] == []
    assert not second["data"]["selection_complete"]
    assert len(agent.llm.calls) == 2 and len(supplier.calls) == 3


def test_pending_ui_replies_block_model_then_can_resume_with_stored_event_context():
    agent, supplier, request = fixture(services=("photography",))
    request["budget_limit_cents"] = 100000
    prepared = agent.prepare_event_enquiries(request)
    ref = lookup(prepared)
    prepared["data"]["selection_context"]["budget_limit_cents"] = 99999999
    assert agent.compare_event_quotations(ref)["status"] == "blocked" and not agent.llm.calls
    # Exercise the future UI seam, independently of the mock provider adapter.
    for enquiry in prepared["data"]["service_rounds"][0]["enquiries"]:
        reply = enquiry["reply"]
        agent.submit_quotation_reply({
            **reply, **ref, "round_id": prepared["data"]["round_ids"][0],
            "enquiry_id": enquiry["enquiry_id"], "mock": True,
            "status": "accepted", "available": True, "quoted_total_cents": 99000,
            "reason": "MOCK manual supplier input.",
        })
    result = agent.compare_event_quotations({**ref, "budget_limit_cents": 1})
    assert result["status"] == "success" and supplier.calls == []
    assert result["data"]["budget_summary"]["effective_supplier_ceiling_cents"] == 100000


@pytest.mark.parametrize("bad", [True, -1, 1.5, "1000"])
def test_invalid_whole_event_budget_is_rejected_before_enquiries(bad):
    agent, supplier, request = fixture()
    request["budget_limit_cents"] = bad
    assert agent.procure_services(request)["status"] == "needs_input"
    assert agent.llm.calls == supplier.calls == []


def test_joint_mode_is_explicit_and_cannot_mix_ranking_modes():
    assert isinstance(build_agent().llm, MockLLMClient)
    with pytest.raises(ValueError):
        build_agent(joint_selection=True, policy_ranking=True)
    with pytest.raises(ValueError):
        build_agent(joint_selection=True, compact_llm=False)
    with pytest.raises(TypeError):
        build_agent(joint_selection="yes")


def test_live_builder_sends_one_supported_http_request_for_all_actual_quotes(monkeypatch):
    from src.llm import CampusQwenClient
    from examples.shared_catalog_procurement_example import event_request
    sent = []
    monkeypatch.setattr(CampusQwenClient, "from_env", classmethod(
        lambda cls, **kw: cls("https://test.example/chat", "test-key", "test-model", **kw)))

    def transport(self, request):
        body = json.loads(request.data)
        assert set(body) == {"model", "messages"}
        facts = payload(body["messages"])
        assert len(facts["services"]) == 5 and all(len(s["quotes"]) == 3 for s in facts["services"])
        sent.append(body)
        decision = json.dumps({"choices": [0, 0, 0, 0, 0], "reason": "Test bundle."})
        return json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": decision}}]})

    monkeypatch.setattr(CampusQwenClient, "_open_and_read", transport)
    result = build_agent(live=True, joint_selection=True).procure_services(event_request())
    assert result["status"] == "success" and len(sent) == 1
    assert len(result["data"]["quotations"]) == 5
