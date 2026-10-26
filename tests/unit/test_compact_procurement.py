"""Compact model I/O retains the public Procurement fact/selection contract."""
import json

import pytest

from examples.event_procurement_example import mock_compare
from examples.shared_catalog_procurement_example import build_agent, event_request
from src.llm import CampusQwenClient, LLMError, MockLLMClient


@pytest.mark.parametrize("workers", [1, 3])
def test_compact_and_legacy_rank_same_facts_with_a_prompt_driven_mock(workers):
    selections = []
    sizes = []
    for compact in (False, True):
        agent = build_agent(compact_llm=compact, llm_concurrency=workers)
        result = agent.procure_services(event_request())
        assert result["status"] == "success"
        selections.append([(q["service_type"], q["vendor_id"], q["offering_id"], q["quoted_total_cents"])
                           for q in result["data"]["quotations"]])
        sizes.append(sum(len(m["content"]) for call in agent.llm.calls for m in call))
        assert len(agent.llm.calls) == 10
    assert selections[0] == selections[1]
    assert sizes[1] < sizes[0] * 0.6


def test_compact_payload_omits_internal_ids_and_model_response_has_no_repeated_facts():
    agent = build_agent()
    result = agent.procure_services(event_request(services=["photography"]))
    assert result["status"] == "success"
    for messages in agent.llm.calls:
        payload = json.loads(messages[-1]["content"])
        assert "candidate_rows" in payload
        for omitted in ("event_id", "proposal_id", "round_id", "quotation_id", "vendor_id", "offering_id"):
            assert omitted not in payload and omitted not in payload["columns"]
        raw = json.loads(mock_compare(messages))
        assert set(raw) == {"ranked"}
        assert len(raw["ranked"]) == 3
    for item in result["data"]["service_results"][0]["data"]["quotation_ranking"]:
        assert item["vendor_id"] and item["offering_id"] and item["quotation_id"]
        assert item["quoted_total_cents"] >= 0 and item["basis_codes"] == []


@pytest.mark.parametrize("ranked", [
    [], [[0, "x"], [1, "x"]], [[0, "x"], [0, "x"], [1, "x"]],
    [[True, "x"], [1, "x"], [2, "x"]], [[0.0, "x"], [1, "x"], [2, "x"]],
    [["0", "x"], [1, "x"], [2, "x"]], [[-1, "x"], [1, "x"], [2, "x"]],
    [[5, "x"], [1, "x"], [2, "x"]], [[0, ""], [1, "x"], [2, "x"]],
    [[0, "x" * 121], [1, "x"], [2, "x"]],
    [{"index": 0, "reason": "x"}, [1, "x"], [2, "x"]],
])
def test_invalid_or_incomplete_compact_shortlist_cannot_create_a_complete_selection(ranked):
    agent = build_agent(llm_concurrency=3)
    agent.llm = MockLLMClient(json.dumps({"ranked": ranked}))
    result = agent.procure_services(event_request(services=["photography"]))
    assert result["status"] == "error"
    assert not result["data"]["selection_complete"] and not result["data"]["quotations"]


def test_compact_output_cannot_override_price_with_extra_fields():
    agent = build_agent()
    agent.llm = MockLLMClient('{"ranked":[[0,"value"],[1,"rating"],[2,"capacity"]],"price_cents":1}')
    result = agent.procure_services(event_request(services=["photography"]))
    assert result["status"] == "error" and not result["data"]["quotations"]


def test_compact_comparison_still_requires_every_accepted_candidate():
    agent = build_agent(llm_concurrency=3)
    prepared = agent.prepare_event_enquiries(event_request(services=["photography"]))
    lookup = {k: prepared["data"][k] for k in ("event_id", "proposal_id", "batch_id")}
    assert agent.request_event_quotations(lookup)["status"] == "success"
    agent.llm = MockLLMClient('{"ranked":[[0,"value"],[1,"rating"]]}')
    result = agent.compare_event_quotations(lookup)
    assert result["status"] == "error"
    assert result["data"]["quotations"] == [] and not result["data"]["selection_complete"]
    assert len(result["data"]["candidate_quotations"]) == 3


@pytest.mark.parametrize("limit", [None, 256])
def test_output_limit_is_explicit_and_not_added_to_legacy_clients(monkeypatch, limit):
    captured = []
    client = CampusQwenClient("https://test.example/chat", "test-key", "test", max_output_tokens=limit)
    def send(request):
        captured.append(json.loads(request.data))
        return '{"choices":[{"message":{"content":"OK"},"finish_reason":"stop"}]}'
    monkeypatch.setattr(client, "_send_with_retry", send)
    assert client.complete([{"role": "user", "content": "OK"}]) == "OK"
    if limit is None:
        assert "max_tokens" not in captured[0]
    else:
        assert captured[0]["max_tokens"] == limit


@pytest.mark.parametrize("limit", [0, -1, True, 2.5])
def test_invalid_output_limit_is_rejected(limit):
    with pytest.raises(LLMError):
        CampusQwenClient("https://test.example/chat", "test-key", "test", max_output_tokens=limit)


def test_server_truncation_is_a_failure_even_if_partial_text_looks_like_json():
    raw = json.dumps({"choices": [{"message": {"content": '{"ranked":[[0,"value"]]}'},
                                  "finish_reason": "length"}]})
    with pytest.raises(LLMError, match="output limit") as raised:
        CampusQwenClient._parse_response(raw)
    assert raised.value.code == "response_format" and not raised.value.retryable

def test_named_supplier_reference_in_preferences_remains_resolvable():
    agent = build_agent()
    request = event_request(services=["photography"])
    request["customer_preferences"] = "Prefer V-PHOTO-002-O2 if suitable."
    result = agent.procure_services(request)
    assert result["status"] == "success"
    payload = json.loads(agent.llm.calls[0][-1]["content"])
    ref_index = payload["columns"].index("ref")
    assert any("V-PHOTO-002-O2" in row[ref_index] for row in payload["candidate_rows"])
    assert "V-PHOTO-002-O2" in payload["preferences"]
