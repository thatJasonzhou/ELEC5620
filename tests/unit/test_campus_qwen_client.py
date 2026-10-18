"""Offline unit tests for CampusQwenClient (KAN-16).

The client is exercised with ``urllib.request.urlopen`` mocked, so no
real API or network access happens. Covered:

- successful OpenAI-style response parsing;
- non-retryable HTTP statuses (401/403/404) — no retry, no secrets
  echoed;
- transient faults (URLError/TimeoutError/5xx) — retried exactly once;
- response failures: invalid JSON, bad structure, non-UTF-8 body;
- configuration errors: bad endpoint URL, bad timeout, missing env vars.

Every expected failure surfaces as ``LLMError`` so the Agent can return
an error envelope.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from unittest import mock

import pytest

from src.llm import CampusQwenClient, LLMError

_URL = "http://llm.example.com/v1/chat/completions"
_KEY = "test-key-never-echoed"
_MODEL = "qwen-test"


def _client(**overrides):
    kwargs = {"base_url": _URL, "api_key": _KEY, "model": _MODEL}
    kwargs.update(overrides)
    return CampusQwenClient(**kwargs)


def _http_error(status: int, reason: str = "reason") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(_URL, status, reason, {}, None)


def _mock_urlopen(monkeypatch, *outcomes) -> mock.Mock:
    """Mock ``urllib.request.urlopen`` with the given outcomes.

    Each outcome is an exception instance (raised) or a byte string /
    string (returned as the response body).
    """
    calls = []

    def fake_urlopen(request, timeout=None):
        calls.append({"request": request, "timeout": timeout})
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        body = outcome.encode("utf-8") if isinstance(outcome, str) else outcome
        return _response(body)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return mock.Mock(return_value=calls)


def _response(body: bytes):
    response = mock.Mock()
    response.read.return_value = body
    # Magic methods must be configured in the constructor, not via
    # attribute assignment on a plain Mock.
    return mock.Mock(
        __enter__=mock.Mock(return_value=response),
        __exit__=mock.Mock(return_value=False),
    )


def _ok_body(text: str = "recommended vendor: V-CAT-002-O1") -> bytes:
    return json.dumps(
        {"choices": [{"message": {"role": "assistant", "content": text}}]}
    ).encode("utf-8")


MESSAGES = [{"role": "user", "content": "pick a vendor"}]


# ---------------------------------------------------------------- success

class TestSuccess:
    def test_parses_openai_style_content(self, monkeypatch):
        _mock_urlopen(monkeypatch, _ok_body())
        assert _client().complete(MESSAGES) == "recommended vendor: V-CAT-002-O1"

    def test_timeout_forwarded_to_urlopen(self, monkeypatch):
        m = _mock_urlopen(monkeypatch, _ok_body())
        _client(timeout_seconds=3.5).complete(MESSAGES)
        assert m.return_value[0]["timeout"] == 3.5


# ---------------------------------------------------------------- no retry

class TestNoRetryStatuses:
    @pytest.mark.parametrize("status", [401, 403])
    def test_auth_failure_is_single_call_llm_error(self, monkeypatch, status):
        m = _mock_urlopen(monkeypatch, _http_error(status, "Unauthorized"))
        with pytest.raises(LLMError) as excinfo:
            _client().complete(MESSAGES)
        assert "authentication failed" in str(excinfo.value)
        assert len(m.return_value) == 1
        # No config value or credential may leak into the message.
        assert _KEY not in str(excinfo.value)
        assert _URL not in str(excinfo.value)

    def test_404_is_single_call_llm_error(self, monkeypatch):
        m = _mock_urlopen(monkeypatch, _http_error(404, "Not Found"))
        with pytest.raises(LLMError) as excinfo:
            _client().complete(MESSAGES)
        assert "HTTP 404" in str(excinfo.value)
        assert len(m.return_value) == 1


# ---------------------------------------------------------------- retrying

class TestTransientFaults:
    def test_network_fault_recovered_on_retry(self, monkeypatch):
        m = _mock_urlopen(monkeypatch, urllib.error.URLError("net down"), _ok_body())
        assert _client().complete(MESSAGES) == "recommended vendor: V-CAT-002-O1"
        assert len(m.return_value) == 2

    def test_network_fault_retried_at_most_once(self, monkeypatch):
        m = _mock_urlopen(
            monkeypatch, urllib.error.URLError("net down"), urllib.error.URLError("still down")
        )
        with pytest.raises(LLMError) as excinfo:
            _client().complete(MESSAGES)
        assert "failed after retry" in str(excinfo.value)
        assert len(m.return_value) == 2  # never a third attempt

    def test_timeout_recovered_on_retry(self, monkeypatch):
        m = _mock_urlopen(monkeypatch, TimeoutError(), _ok_body())
        _client().complete(MESSAGES)
        assert len(m.return_value) == 2

    def test_503_recovered_on_retry(self, monkeypatch):
        m = _mock_urlopen(monkeypatch, _http_error(503), _ok_body())
        _client().complete(MESSAGES)
        assert len(m.return_value) == 2

    def test_503_then_failure_is_single_retry(self, monkeypatch):
        m = _mock_urlopen(monkeypatch, _http_error(503), _http_error(502, "Bad Gateway"))
        with pytest.raises(LLMError) as excinfo:
            _client().complete(MESSAGES)
        assert "on retry" in str(excinfo.value)
        assert len(m.return_value) == 2


# ----------------------------------------------------- response handling

class TestResponseFailures:
    def test_invalid_json(self, monkeypatch):
        _mock_urlopen(monkeypatch, b"<html>502 Bad Gateway</html>")
        with pytest.raises(LLMError) as excinfo:
            _client().complete(MESSAGES)
        assert "not valid JSON" in str(excinfo.value)

    def test_missing_choices(self, monkeypatch):
        _mock_urlopen(monkeypatch, json.dumps({"error": "x"}).encode("utf-8"))
        with pytest.raises(LLMError) as excinfo:
            _client().complete(MESSAGES)
        assert "choices" in str(excinfo.value)

    def test_empty_choices(self, monkeypatch):
        _mock_urlopen(monkeypatch, json.dumps({"choices": []}).encode("utf-8"))
        with pytest.raises(LLMError) as excinfo:
            _client().complete(MESSAGES)
        assert "choices" in str(excinfo.value)

    def test_missing_message_content(self, monkeypatch):
        _mock_urlopen(
            monkeypatch, json.dumps({"choices": [{"message": {}}]}).encode("utf-8")
        )
        with pytest.raises(LLMError) as excinfo:
            _client().complete(MESSAGES)
        assert "content" in str(excinfo.value)

    def test_empty_content(self, monkeypatch):
        _mock_urlopen(
            monkeypatch,
            json.dumps({"choices": [{"message": {"content": "  "}}]}).encode("utf-8"),
        )
        with pytest.raises(LLMError) as excinfo:
            _client().complete(MESSAGES)
        assert "empty" in str(excinfo.value)

    def test_non_utf8_body(self, monkeypatch):
        _mock_urlopen(monkeypatch, b"\xff\xfe\x00invalid")
        with pytest.raises(LLMError) as excinfo:
            _client().complete(MESSAGES)
        assert "UTF-8" in str(excinfo.value)

    def test_non_utf8_body_is_not_retried(self, monkeypatch):
        m = _mock_urlopen(monkeypatch, b"\xff\xfe\x00invalid")
        with pytest.raises(LLMError):
            _client().complete(MESSAGES)
        assert len(m.return_value) == 1


# ------------------------------------------------------- config validation

class TestConfiguration:
    @pytest.mark.parametrize(
        "base_url",
        [
            "",
            "   ",
            None,
            123,
            "not a url",
            "ftp://llm.example.com/v1",
            "httpx://llm.example.com/v1",
            "localhost:8080/v1",
            "http://",
            "https:///v1/chat/completions",
            "http://:8080/v1",
        ],
    )
    def test_invalid_base_url(self, base_url):
        with pytest.raises(LLMError):
            _client(base_url=base_url)

    @pytest.mark.parametrize(
        "timeout", [True, False, "60", None, 0, -1, 0.0, float("nan"), float("inf")]
    )
    def test_invalid_timeout(self, timeout):
        with pytest.raises(LLMError):
            _client(timeout_seconds=timeout)

    @pytest.mark.parametrize("value", ["", None, 7])
    def test_invalid_api_key(self, value):
        with pytest.raises(LLMError):
            _client(api_key=value)

    @pytest.mark.parametrize("value", ["", "   ", None, 7])
    def test_invalid_model(self, value):
        with pytest.raises(LLMError):
            _client(model=value)

    def test_invalid_endpoint_message_contains_no_value(self):
        bad = "ftp://user:secret@llm.example.com/v1"
        with pytest.raises(LLMError) as excinfo:
            _client(base_url=bad)
        message = str(excinfo.value)
        assert bad not in message
        assert "secret" not in message

    def test_valid_url_with_credentials_is_accepted(self):
        # URL validation only checks scheme + host; it must not reject
        # (or echo) embedded credentials.
        client = _client(base_url="https://user:token@api.example.com/v1")
        assert client._base_url == "https://user:token@api.example.com/v1"


class TestFromEnv:
    ALL_ENV = {
        "ELEC5620_LLM_BASE_URL": "https://a.example.com/v1",
        "ELEC5620_LLM_API_KEY": "secret-key-value",
        "ELEC5620_LLM_MODEL": "model-name",
    }

    @pytest.mark.parametrize(
        "missing",
        [
            frozenset(),
            frozenset({"ELEC5620_LLM_BASE_URL"}),
            frozenset({"ELEC5620_LLM_API_KEY"}),
            frozenset({"ELEC5620_LLM_MODEL"}),
            frozenset(ALL_ENV),
        ],
    )
    def test_missing_vars_listed_without_values(self, monkeypatch, missing):
        for name, value in self.ALL_ENV.items():
            if name in missing:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        if not missing:
            client = CampusQwenClient.from_env()
            assert client._model == "model-name"
            assert client._timeout == 60.0
            return
        with pytest.raises(LLMError) as excinfo:
            CampusQwenClient.from_env()
        message = str(excinfo.value)
        for name in missing:
            assert name in message
        # Configured values must never be echoed into the error.
        for name, value in self.ALL_ENV.items():
            assert value not in message
