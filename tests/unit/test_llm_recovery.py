"""Safe transport diagnostics and bounded retry of only failed model jobs."""
from collections import Counter
import json
from threading import Lock
import urllib.error
from unittest.mock import Mock

import pytest

from examples.event_procurement_example import make_event_demo, mock_compare
from examples.shared_catalog_procurement_example import format_summary
from src.agents.vendor_procurement_manager import VendorProcurementManagerAgent
from src.llm import CampusQwenClient, LLMError, MockLLMClient
from src.llm.batch import complete_jobs


@pytest.mark.parametrize("status,code,retryable,calls", [
    (401, "authentication", False, 1), (403, "authentication", False, 1),
    (404, "http_error", False, 1), (429, "rate_limit", True, 2),
    (503, "http_error", True, 2),
])
def test_http_error_metadata_is_safe_and_has_correct_retry_policy(monkeypatch, status, code, retryable, calls):
    secret = "secret-key-in-reason"
    error = urllib.error.HTTPError("https://private.example/path", status, secret, {}, None)
    send = Mock(side_effect=error)
    monkeypatch.setattr("urllib.request.urlopen", send)
    client = CampusQwenClient("https://private.example/chat", secret, "test")
    with pytest.raises(LLMError) as raised:
        client.complete([{"role": "user", "content": "hello"}])
    exc = raised.value
    assert (exc.code, exc.http_status, exc.retryable) == (code, status, retryable)
    assert secret not in str(exc) and "private.example" not in str(exc)
    assert send.call_count == calls


@pytest.mark.parametrize("error,code", [
    (TimeoutError("secret endpoint"), "timeout"),
    (urllib.error.URLError(TimeoutError("secret endpoint")), "timeout"),
    (urllib.error.URLError("secret endpoint"), "network"),
])
def test_final_network_failure_is_classified_without_echoing_exception(monkeypatch, error, code):
    send = Mock(side_effect=error)
    monkeypatch.setattr("urllib.request.urlopen", send)
    with pytest.raises(LLMError) as raised:
        CampusQwenClient("http://private.example/chat", "secret", "test").complete([])
    assert raised.value.code == code and raised.value.retryable
    assert raised.value.http_status is None
    assert "secret endpoint" not in str(raised.value)
    assert send.call_count == 2


def test_bad_response_is_not_a_transient_transport_failure():
    with pytest.raises(LLMError) as raised:
        CampusQwenClient._parse_response("not JSON")
    assert raised.value.code == "response_format" and not raised.value.retryable


def test_only_transient_failed_jobs_retry_after_the_first_pass_drains():
    counts = Counter()
    finished = set()
    lock = Lock()
    events = []

    def model(messages):
        service = messages[0]["content"]
        with lock:
            counts[service] += 1
            attempt = counts[service]
            if attempt > 1:
                assert finished == {"a", "b", "c"}
        if service == "a" and attempt == 1:
            with lock:
                finished.add(service)
            raise LLMError("secret URL/key must stay hidden", code="timeout", retryable=True)
        with lock:
            finished.add(service)
        return service

    jobs = [(s, [{"role": "user", "content": s}]) for s in ("a", "b", "c")]
    result = complete_jobs(MockLLMClient(model), jobs, max_workers=3, stage="comparison",
                           retry_failed=True, progress=events.append)
    assert counts == {"a": 2, "b": 1, "c": 1}
    assert [r.text for r in result] == ["a", "b", "c"]
    assert not any(r.failed for r in result)
    assert result[0].attempts == 2
    assert [e["service_type"] for e in events if e["state"] == "retrying"] == ["a"]
    assert "secret URL/key" not in str(events)


@pytest.mark.parametrize("code", ["authentication", "response_format", "llm_error"])
def test_permanent_or_unknown_errors_are_not_retried(code):
    def fail(_):
        raise LLMError("sensitive diagnostic", code=code)
    client = MockLLMClient(fail)
    result = complete_jobs(client, [("a", [])], max_workers=3, stage="comparison", retry_failed=True)
    assert len(client.calls) == 1 and result[0].failed and result[0].attempts == 1


def test_failed_recovery_remains_an_error_and_is_bounded():
    def fail(_):
        raise LLMError("sensitive diagnostic", code="network", retryable=True)
    client = MockLLMClient(fail)
    result = complete_jobs(client, [("a", [])], max_workers=3, stage="comparison", retry_failed=True)
    assert len(client.calls) == 2 and result[0].failed
    assert result[0].attempts == 2 and result[0].error_code == "network"


@pytest.mark.parametrize("bad_output", [False, True])
def test_activity_recovers_two_transport_failures_without_reenquiring_or_repeating_successes(bad_output):
    counts = Counter()
    lock = Lock()

    def model(messages):
        text = messages[-1]["content"]
        if not text.startswith("{"):
            return mock_compare(messages)
        service = json.loads(text)["context"]["service_type"]
        with lock:
            counts[service] += 1
            count = counts[service]
        if service in ("catering", "venue") and count == 1:
            if bad_output:
                return "not a valid ranking"
            raise LLMError("temporary timeout", code="timeout", retryable=True)
        return mock_compare(messages)

    source, supplier, request = make_event_demo(llm=MockLLMClient(model))
    agent = VendorProcurementManagerAgent(
        source.llm, source._vendor_service, quotation_service=supplier,
        llm_concurrency=3, retry_failed_llm=True)
    result = agent.procure_services(request)
    assert len(supplier.calls) == 15
    if bad_output:
        assert result["status"] == "error" and not result["data"]["selection_complete"]
        assert set(counts.values()) == {1}
    else:
        assert result["status"] == "success" and len(result["data"]["quotations"]) == 5
        assert counts == {"photography": 1, "catering": 2, "venue": 2, "sound": 1, "decoration": 1}


def test_shortlist_failure_summary_handles_legacy_unlabelled_results():
    summary = {
        "llm_mode": "live", "llm_concurrency": 2, "status": "error",
        "selection_complete": False, "elapsed_seconds": 60.0,
        "enquiry_count": 0, "selected_quotation_ids": [], "quotations": [],
        "message": "Cannot prepare all services.",
        "service_results": [{"status": "error", "message": "Shortlist failed.",
                             "data": {"llm_error": {"code": "timeout", "http_status": None}}}],
    }
    assert "service: error [timeout]" in format_summary(summary)
