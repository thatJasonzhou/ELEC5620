"""The Qwen extension is explicit, validated and never silently dropped."""
import json
import urllib.error

import pytest

from examples import diagnose_procurement_llm as diagnostic
from examples import shared_catalog_procurement_example as demo
from examples.event_procurement_example import mock_compare
from src.llm import CampusQwenClient, LLMError


@pytest.mark.parametrize('thinking', [None, False, True])
@pytest.mark.parametrize('cap', [None, 256])
def test_thinking_extension_is_opt_in_and_preserves_output_cap(monkeypatch, thinking, cap):
    captured = []
    client = CampusQwenClient('https://test.example/chat', 'test-key', 'test',
                              enable_thinking=thinking, max_output_tokens=cap)
    def transport(request):
        captured.append(json.loads(request.data))
        return '{"choices":[{"message":{"content":"OK"},"finish_reason":"stop"}]}'
    monkeypatch.setattr(client, '_send_with_retry', transport)
    assert client.complete([{'role': 'user', 'content': 'OK'}]) == 'OK'
    if thinking is None:
        assert 'chat_template_kwargs' not in captured[0]
    else:
        assert captured[0]['chat_template_kwargs'] == {'enable_thinking': thinking}
    assert captured[0].get('max_tokens') == cap
    assert 'reasoning_effort' not in captured[0]


@pytest.mark.parametrize('thinking', [0, 1, 'false', {}])
def test_invalid_thinking_option_is_rejected(thinking):
    with pytest.raises(LLMError) as raised:
        CampusQwenClient('https://test.example/chat', 'test-key', 'test', enable_thinking=thinking)
    assert raised.value.code == 'configuration'


def test_environment_factory_preserves_explicit_option(monkeypatch):
    for key, value in {'ELEC5620_LLM_BASE_URL': 'https://test.example/chat',
                       'ELEC5620_LLM_API_KEY': 'test-key', 'ELEC5620_LLM_MODEL': 'test'}.items():
        monkeypatch.setenv(key, value)
    assert CampusQwenClient.from_env(enable_thinking=False)._enable_thinking is False
    assert CampusQwenClient.from_env()._enable_thinking is None


def test_unsupported_backend_option_is_not_retried_or_silently_removed(monkeypatch):
    requests = []
    def transport(self, request):
        requests.append(json.loads(request.data))
        raise urllib.error.HTTPError('https://test.example/chat', 400, 'unsupported option', {}, None)
    monkeypatch.setattr(CampusQwenClient, '_open_and_read', transport)
    client = CampusQwenClient('https://test.example/chat', 'test-key', 'test', enable_thinking=False)
    with pytest.raises(LLMError) as raised:
        client.complete([{'role': 'user', 'content': 'OK'}])
    assert raised.value.http_status == 400 and len(requests) == 1
    assert requests[0]['chat_template_kwargs'] == {'enable_thinking': False}


def test_full_live_cli_passes_explicit_setting_to_all_ten_model_calls(monkeypatch, capsys):
    requests = []
    monkeypatch.setattr(CampusQwenClient, 'from_env', classmethod(
        lambda cls, **kw: cls('https://test.example/chat', 'test-key', 'test', **kw)))
    def transport(self, request):
        payload = json.loads(request.data)
        requests.append(payload)
        return json.dumps({'choices': [{'finish_reason': 'stop',
                          'message': {'content': mock_compare(payload['messages']) if payload['messages'][-1]['content'].startswith('{') else 'A B C'}}]})
    monkeypatch.setattr(CampusQwenClient, '_open_and_read', transport)
    monkeypatch.setattr('sys.argv', ['demo', '--live', '--concurrency', '2', '--disable-thinking', '--verbose'])
    demo.main()
    summary = json.loads(capsys.readouterr().out)
    assert summary['selection_complete'] and len(summary['quotations']) == 5
    assert summary['enable_thinking_requested'] is False
    assert len(requests) == 10
    assert all(r['chat_template_kwargs'] == {'enable_thinking': False} for r in requests)


def test_diagnostic_flag_reaches_transport_and_prints_request_intent(monkeypatch, capsys):
    requests = []
    monkeypatch.setattr(diagnostic.DiagnosticCampusClient, 'from_env', classmethod(
        lambda cls, **kw: cls('https://test.example/chat', 'test-key', 'test', **kw)))
    def transport(self, request):
        requests.append(json.loads(request.data))
        return '{"choices":[{"finish_reason":"stop","message":{"content":"OK","reasoning":""}}],"usage":{"completion_tokens_details":{"reasoning_tokens":0}}}'
    monkeypatch.setattr(CampusQwenClient, '_open_and_read', transport)
    monkeypatch.setattr('sys.argv', ['diagnostic', '--disable-thinking'])
    diagnostic.main()
    out = capsys.readouterr().out
    assert 'Thinking: disabled_requested' in out and 'reasoning_tokens=0' in out
    assert requests[0]['chat_template_kwargs'] == {'enable_thinking': False}
    assert requests[0]['max_tokens'] == 256
