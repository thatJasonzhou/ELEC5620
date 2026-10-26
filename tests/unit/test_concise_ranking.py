"""A real model still chooses rankings; concise replies cannot override facts."""
import json

import pytest

from src.llm import LLMError, MockLLMClient
from src.llm.concise_ranking import ConciseRankingClient


def messages(stage='comparison'):
    return [{'role': 'user', 'content': json.dumps({
        'stage': stage, 'service': 'photography', 'count': 3,
        'date': '2026-12-16', 'city': 'Sydney', 'guests': 50,
        'preferences': 'Prefer value; keep Candid Day if suitable.',
        'target_cents': 100000, 'hard_limit': False,
        'columns': ['i', 'name', 'price_cents', 'rating', 'capacity', 'ref', 'estimate_cents', 'supplier_note'],
        'candidate_rows': [[0, 'Candid Day', 89300, 4.7, 180, 'V-A/O1', 95000, 'Coverage includes editing.'],
                           [1, 'Silverlight', 147000, 4.9, 250, 'V-B/O1', 140000, 'Coverage includes editing.'],
                           [2, 'Lumen', 137500, 4.1, 100, 'V-C/O1', 110000, 'Coverage includes editing.']],
    })}]


@pytest.mark.parametrize('reply', ['B A C', '\n\nB A C\n', 'B > A > C', 'B,A,C'])
def test_model_order_is_retained_and_output_facts_are_code_generated(reply):
    backend = MockLLMClient(reply)
    result = json.loads(ConciseRankingClient(backend).complete(messages()))
    assert [row[0] for row in result['ranked']] == [1, 0, 2]
    assert result['ranked'][0][1] == 'Supplier quote AUD1470.00; rating 4.9/5.'
    prompt = backend.calls[0][-1]['content']
    assert 'Budget AUD1000.00 (soft target)' in prompt and 'V-A/O1' in prompt
    assert 'capacity 180' in prompt and 'Candid Day' in prompt
    assert 'previous estimate AUD950.00' in prompt
    assert prompt.count('Coverage includes editing.') == 1
    assert 'Reply only 3 supplied labels' in prompt
    assert 'candidate_rows' not in prompt and 'brief reason' not in prompt


@pytest.mark.parametrize('reply', ['A A C', 'A B', 'A B D', 'A B C D', 'A B C price=1',
                                  '{"ranked":[0,1,2]}', 'Ranking: A B C', ''])
def test_incomplete_duplicate_unknown_or_extra_output_fails_closed(reply):
    with pytest.raises(LLMError) as raised:
        ConciseRankingClient(MockLLMClient(reply)).complete(messages())
    assert raised.value.code == 'response_format' and not raised.value.retryable


def test_transport_errors_remain_the_original_typed_failure():
    failure = LLMError('safe failure', code='http_error', http_status=502, retryable=True)
    def fail(_):
        raise failure
    with pytest.raises(LLMError) as raised:
        ConciseRankingClient(MockLLMClient(fail)).complete(messages())
    assert raised.value is failure


def test_distinct_supplier_notes_and_hard_budget_remain_available():
    request = messages('shortlist')
    payload = json.loads(request[0]['content'])
    payload['hard_limit'] = True
    payload['candidate_rows'][1][-1] = 'Editing excluded.'
    request[0]['content'] = json.dumps(payload)
    backend = MockLLMClient('A B C')
    result = json.loads(ConciseRankingClient(backend).complete(request))
    prompt = backend.calls[0][-1]['content']
    assert 'hard limit' in prompt and 'Editing excluded.' in prompt
    assert 'prices are estimates' in prompt and 'Catalog estimate' in result['ranked'][0][1]


def test_live_cli_uses_bare_rankings_for_both_phases_and_mock_stays_unchanged(monkeypatch, capsys):
    from examples import shared_catalog_procurement_example as demo
    from src.llm import CampusQwenClient
    assert isinstance(demo.build_agent().llm, MockLLMClient)
    requests = []
    monkeypatch.setattr(CampusQwenClient, 'from_env', classmethod(
        lambda cls, **kw: cls('https://test.example/chat', 'test-key', 'test', **kw)))
    def transport(self, request):
        payload = json.loads(request.data)
        requests.append(payload)
        assert set(payload) == {'model', 'messages'}
        prompt = payload['messages'][-1]['content']
        assert not prompt.startswith('{') and 'Reply only 3 supplied labels' in prompt
        return '{"choices":[{"finish_reason":"stop","message":{"content":"A B C"}}]}'
    monkeypatch.setattr(CampusQwenClient, '_open_and_read', transport)
    monkeypatch.setattr('sys.argv', ['demo', '--live', '--concurrency', '2', '--verbose'])
    demo.main()
    summary = json.loads(capsys.readouterr().out)
    assert summary['selection_complete'] and len(summary['quotations']) == 5
    assert summary['enquiry_count'] == 15 and summary['llm_calls'] == len(requests) == 10
    assert sum('supplier quotes' in p['messages'][-1]['content'] for p in requests) == 5


def test_invalid_live_labels_cannot_become_a_mock_success(monkeypatch, capsys):
    from examples import shared_catalog_procurement_example as demo
    from src.llm import CampusQwenClient
    monkeypatch.setattr(CampusQwenClient, 'from_env', classmethod(
        lambda cls, **kw: cls('https://test.example/chat', 'test-key', 'test', **kw)))
    monkeypatch.setattr(CampusQwenClient, '_open_and_read', lambda self, request:
        '{"choices":[{"finish_reason":"stop","message":{"content":"A A C"}}]}')
    monkeypatch.setattr('sys.argv', ['demo', '--live', '--services', 'photography', '--verbose'])
    with pytest.raises(SystemExit) as raised:
        demo.main()
    result = json.loads(capsys.readouterr().out)
    assert raised.value.code == 1 and result['status'] == 'error'
    assert result['enquiry_count'] == 0 and not result['selection_complete']
