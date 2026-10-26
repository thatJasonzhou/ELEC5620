"""Diagnostics preserve retries and exclude raw server/model text."""
import json
import urllib.error

import pytest

from examples import diagnose_procurement_llm as probe
from src.llm import CampusQwenClient


def test_metadata_drops_server_text_and_preserves_truncation_evidence():
    raw = json.dumps({"secret": "private", "usage": {"prompt_tokens": 213, "completion_tokens": 256,
        "total_tokens": 469, "secret": "private", "completion_tokens_details": {"reasoning_tokens": 256}},
        "choices": [{"finish_reason": "length", "message": {"content": "", "reasoning_content": "private"}}]})
    metadata = probe.response_metadata(raw)
    assert metadata == {"envelope": "empty_content", "finish": "length", "content_chars": 0,
                        "reasoning_content_chars": 7, "prompt_tokens": 213,
                        "completion_tokens": 256, "total_tokens": 469, "reasoning_tokens": 256}
    assert "private" not in json.dumps(metadata)


@pytest.mark.parametrize("raw,expected", [
    ("private invalid JSON", "invalid_json"), ('[]', "invalid_choice"),
    ('{"choices":[null]}', "invalid_choice"),
    ('{"choices":[{"message":{}}]}', "missing_content"),
    ('{"choices":[{"message":{"content":null}}]}', "non_string_content"),
])
def test_bad_envelope_diagnostics_are_bounded(raw, expected):
    assert probe.response_metadata(raw)["envelope"] == expected


def test_unknown_finish_and_malformed_usage_never_echo_values():
    raw = json.dumps({"choices": [{"finish_reason": "private", "message": {"content": "private"}}],
                      "usage": {"prompt_tokens": True, "completion_tokens": "private", "total_tokens": -1}})
    assert probe.response_metadata(raw) == {"envelope": "valid_json", "content_chars": 7, "finish": "unknown"}


def test_probe_reveals_internal_retry_without_printing_http_reason(monkeypatch, capsys):
    attempts = []
    def transport(self, request):
        attempts.append(request)
        raise urllib.error.HTTPError("https://private.example/secret", 502, "PRIVATE KEY", {}, None)
    monkeypatch.setattr(CampusQwenClient, "_open_and_read", transport)
    monkeypatch.setattr(probe.DiagnosticCampusClient, "from_env", classmethod(
        lambda cls, **kw: cls("https://test.example/chat", "private-key", "test", **kw)))
    monkeypatch.setattr("sys.argv", ["probe"])
    with pytest.raises(SystemExit) as raised:
        probe.main()
    out = capsys.readouterr().out
    assert raised.value.code == 1 and len(attempts) == 2
    assert "Attempt 1: HTTP 502" in out and "Attempt 2: HTTP 502" in out
    assert "code=http_error" in out and len(out.splitlines()) == 7
    assert "PRIVATE" not in out and "private" not in out and "https://" not in out
    payload = json.loads(attempts[0].data)
    assert payload["max_tokens"] == 256
    assert "candidate_rows" in payload["messages"][-1]["content"]


def test_empty_truncated_reply_is_diagnosed_without_echoing_reasoning(monkeypatch, capsys):
    monkeypatch.setattr(CampusQwenClient, "_open_and_read", lambda self, request:
        '{"choices":[{"finish_reason":"length","message":{"content":"","reasoning_content":"PRIVATE"}}]}')
    monkeypatch.setattr(probe.DiagnosticCampusClient, "from_env", classmethod(
        lambda cls, **kw: cls("https://test.example/chat", "private-key", "test", **kw)))
    monkeypatch.setattr("sys.argv", ["probe"])
    with pytest.raises(SystemExit):
        probe.main()
    out = capsys.readouterr().out
    assert "detail=output_limit" in out and "content_chars=0" in out
    assert "reasoning_content_chars=7" in out and "PRIVATE" not in out


def test_uncapped_baseline_sends_only_ok_prompt(monkeypatch, capsys):
    captured = []
    def transport(self, request):
        captured.append(json.loads(request.data))
        return '{"choices":[{"finish_reason":"stop","message":{"content":"OK"}}]}'
    monkeypatch.setattr(CampusQwenClient, "_open_and_read", transport)
    monkeypatch.setattr(probe.DiagnosticCampusClient, "from_env", classmethod(
        lambda cls, **kw: cls("https://test.example/chat", "private-key", "test", **kw)))
    monkeypatch.setattr("sys.argv", ["probe", "--baseline", "--max-output-tokens", "0"])
    probe.main()
    assert "max_tokens" not in captured[0]
    assert captured[0]["messages"] == [{"role": "user", "content": "Reply with exactly OK."}]
    assert "response_received" in capsys.readouterr().out


def test_no_think_prompt_uses_no_extension_and_preserves_fixture(monkeypatch, capsys):
    from examples.shared_catalog_procurement_example import build_agent, event_request
    requests = []
    agent = build_agent()
    agent.prepare_event_enquiries(event_request(services=['photography']))
    original = [dict(message) for message in agent.llm.calls[0]]
    monkeypatch.setattr(probe, 'build_agent', lambda: agent)
    monkeypatch.setattr(probe.DiagnosticCampusClient, 'from_env', classmethod(
        lambda cls, **kw: cls('https://test.example/chat', 'test-key', 'test', **kw)))
    def transport(self, request):
        requests.append(json.loads(request.data))
        return '{"choices":[{"finish_reason":"stop","message":{"content":"OK"}}]}'
    monkeypatch.setattr(CampusQwenClient, '_open_and_read', transport)
    monkeypatch.setattr('sys.argv', ['probe', '--no-think-prompt'])
    probe.main()
    assert set(requests[0]) == {'model', 'messages', 'max_tokens'}
    assert requests[0]['max_tokens'] == 256
    assert requests[0]['messages'][:-1] == original[:-1]
    assert requests[0]['messages'][-1]['content'] == original[-1]['content'] + '\n/no_think'
    assert agent.llm.calls[0] == original
    assert 'Thinking: prompt_no_think_requested' in capsys.readouterr().out


def test_thinking_controls_are_mutually_exclusive(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['probe', '--disable-thinking', '--no-think-prompt'])
    with pytest.raises(SystemExit) as raised:
        probe.main()
    assert raised.value.code == 2
    assert 'Choose only one thinking control' in capsys.readouterr().err
