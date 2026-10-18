"""Unit tests for the LLM base interface and MockLLMClient (KAN-16)."""
from __future__ import annotations

import pytest

from src.llm import LLMClient, LLMError, MockLLMClient


class TestInterfaceContract:
    def test_mock_is_llm_client(self):
        assert isinstance(MockLLMClient("x"), LLMClient)

    def test_llm_error_is_exception(self):
        assert issubclass(LLMError, Exception)


class TestMockResponses:
    def test_static_string(self):
        client = MockLLMClient("hello")
        assert client.complete([{"role": "user", "content": "hi"}]) == "hello"
        assert client.complete([{"role": "user", "content": "again"}]) == "hello"

    def test_queued_strings_in_order(self):
        client = MockLLMClient(["a", "b"])
        assert client.complete([{"role": "user", "content": "1"}]) == "a"
        assert client.complete([{"role": "user", "content": "2"}]) == "b"

    def test_queue_exhausted_raises(self):
        client = MockLLMClient(["a"])
        client.complete([{"role": "user", "content": "1"}])
        with pytest.raises(LLMError):
            client.complete([{"role": "user", "content": "2"}])

    def test_callable(self):
        client = MockLLMClient(lambda msgs: msgs[-1]["content"].upper())
        assert client.complete(
            [{"role": "system", "content": "s"}, {"role": "user", "content": "ab"}]
        ) == "AB"

    def test_invalid_constructor_raises_llm_error(self):
        with pytest.raises(LLMError):
            MockLLMClient(42)  # type: ignore[arg-type]


class TestMockCallRecording:
    def test_records_call_count_and_messages(self):
        client = MockLLMClient("ok")
        client.complete([{"role": "system", "content": "be brief"}])
        client.complete([{"role": "user", "content": "pick a vendor"}])
        assert len(client.calls) == 2
        assert client.calls[0] == [{"role": "system", "content": "be brief"}]
        assert client.calls[1][0]["content"] == "pick a vendor"

    def test_recorded_messages_are_copies(self):
        client = MockLLMClient("ok")
        original = [{"role": "user", "content": "x"}]
        client.complete(original)
        original[0]["content"] = "mutated"
        assert client.calls[0][0]["content"] == "x"


class TestMockRuntimeReconfiguration:
    def test_set_exception(self):
        client = MockLLMClient("ok")
        client.set_exception(LLMError("simulated outage"))
        with pytest.raises(LLMError, match="simulated outage"):
            client.complete([{"role": "user", "content": "1"}])

    def test_set_response_overrides_queue(self):
        client = MockLLMClient(["a", "b"])
        client.set_response("static")
        assert client.complete([{"role": "user", "content": "1"}]) == "static"
        assert client.complete([{"role": "user", "content": "2"}]) == "static"

    def test_set_response_after_exception(self):
        client = MockLLMClient()
        client.set_exception(LLMError("down"))
        client.set_response("recovered")
        assert client.complete([{"role": "user", "content": "1"}]) == "recovered"

    def test_setters_validate_input(self):
        client = MockLLMClient()
        with pytest.raises(LLMError):
            client.set_response(123)  # type: ignore[arg-type]
        with pytest.raises(LLMError):
            client.set_exception("not an exception")  # type: ignore[arg-type]


class TestQueuedExceptions:
    def test_exception_item_in_queue(self):
        client = MockLLMClient(["ok", LLMError("boom"), "fine"])
        assert client.complete([{"role": "user", "content": "1"}]) == "ok"
        with pytest.raises(LLMError, match="boom"):
            client.complete([{"role": "user", "content": "2"}])
        assert client.complete([{"role": "user", "content": "3"}]) == "fine"
        assert len(client.calls) == 3

    def test_invalid_queue_item_rejected(self):
        with pytest.raises(LLMError):
            MockLLMClient(["ok", 7])  # type: ignore[list-item]
