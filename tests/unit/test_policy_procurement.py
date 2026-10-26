"""One LLM policy per activity; deterministic ranking still respects supplier facts."""
from copy import deepcopy
import json

import pytest

from examples.event_procurement_example import make_event_demo
from examples.shared_catalog_procurement_example import build_agent, event_request
from src.agents.vendor_procurement_manager import VendorProcurementManagerAgent
from src.llm import LLMError, MockLLMClient
from src.services.vendor_ranking_service import VendorRankingService


def fixture_agent(reply='V', workers=1):
    source, supplier, request = make_event_demo()
    agent = VendorProcurementManagerAgent(MockLLMClient(reply), source._vendor_service,
        quotation_service=supplier, compact_llm=True, policy_ranking=True, llm_concurrency=workers)
    return agent, supplier, request


@pytest.mark.parametrize('workers', [1, 2, 5])
@pytest.mark.parametrize('code,expected_vendor', [('V', 'B'), ('Q', 'A'), ('P', 'B')])
def test_one_policy_call_controls_both_stages_for_all_services(workers, code, expected_vendor):
    agent, supplier, request = fixture_agent(code, workers)
    result = agent.procure_services(request)
    assert result['status'] == 'success' and result['data']['selection_complete']
    assert len(agent.llm.calls) == 1 and len(supplier.calls) == 15
    assert len(result['data']['quotations']) == 5
    assert all(q['vendor_id'] == expected_vendor for q in result['data']['quotations'])
    assert all(policy['code'] == code for policy in result['data']['ranking_policies'].values())
    # An initial catalogue leader changes when the supplier submits a higher quote.
    if code == 'V':
        photo = result['data']['service_results'][0]['data']
        assert photo['context']['ranking_policy']['code'] == 'V'
        ranking = photo['quotation_ranking']
        assert ranking[0]['vendor_id'] == 'B' and ranking[0]['quoted_total_cents'] == 95000
        assert ranking[1]['vendor_id'] == 'A' and ranking[1]['quoted_total_cents'] == 130000


def test_highest_rating_policy_cannot_override_hard_quote_budget():
    agent, _, request = fixture_agent('Q')
    for item in request['services']:
        item['budget_is_hard_limit'] = True
    result = agent.procure_services(request)
    assert result['status'] == 'success'
    assert all(q['vendor_id'] == 'B' for q in result['data']['quotations'])
    assert len(agent.llm.calls) == 1


def test_per_service_preferences_are_decided_in_one_request():
    agent, _, request = fixture_agent('V Q')
    request['services'][1]['customer_preferences'] = 'Highest rating matters most.'
    result = agent.procure_services(request)
    assert result['status'] == 'success' and len(agent.llm.calls) == 1
    policies = result['data']['ranking_policies']
    assert policies['photography']['code'] == 'V' and policies['catering']['code'] == 'Q'
    assert result['data']['quotations'][0]['vendor_id'] == 'B'
    assert result['data']['quotations'][1]['vendor_id'] == 'A'


@pytest.mark.parametrize('reply', ['', 'default', '{"code":"V"}', 'V V', 'V because cheap', 'X'])
def test_invalid_policy_never_creates_supplier_enquiries(reply):
    agent, supplier, request = fixture_agent(reply)
    result = agent.procure_services(request)
    assert result['status'] == 'error' and not result['data']['selection_complete']
    assert result['data']['quotations'] == [] and supplier.calls == []
    assert len(agent.llm.calls) == 1


def test_unsupported_preferences_request_clarification_without_enquiries():
    agent, supplier, request = fixture_agent('U')
    request['customer_preferences'] = 'Only suppliers with certified aerial drone filming.'
    result = agent.procure_services(request)
    assert result['status'] == 'needs_input' and supplier.calls == []
    assert not result['data']['selection_complete']


def test_transport_failure_does_not_substitute_a_default_policy():
    def fail(_):
        raise LLMError('timeout', code='timeout', retryable=True)
    agent, supplier, request = fixture_agent(fail)
    result = agent.procure_services(request)
    assert result['status'] == 'error' and supplier.calls == []
    assert not result['data']['selection_complete'] and len(agent.llm.calls) == 1


def test_pending_and_repeated_comparison_reuse_stored_policy():
    agent, supplier, request = fixture_agent()
    prepared = agent.prepare_event_enquiries(request)
    lookup = {k: prepared['data'][k] for k in ('event_id', 'proposal_id', 'batch_id')}
    assert agent.compare_event_quotations(lookup)['status'] == 'blocked'
    assert len(agent.llm.calls) == 1
    assert agent.request_event_quotations(lookup)['status'] == 'success'
    first = agent.compare_event_quotations(lookup)
    second = agent.compare_event_quotations({**lookup, 'ranking_policy': {'code': 'Q'}})
    assert first['status'] == second['status'] == 'success'
    assert all(q['vendor_id'] == 'B' for q in second['data']['quotations'])
    assert len(agent.llm.calls) == 1 and len(supplier.calls) == 15


def test_new_event_gets_fresh_policy_and_old_event_keeps_its_decision():
    answers = iter(['V', 'Q'])
    agent, _, request = fixture_agent(lambda _: next(answers))
    first = agent.procure_services(request)
    changed = deepcopy(request)
    changed['event_id'] = 'NEW-EVENT'
    changed['proposal_id'] = 'NEW-PROPOSAL'
    second = agent.procure_services(changed)
    assert first['status'] == second['status'] == 'success' and len(agent.llm.calls) == 2
    lookup = {k: first['data'][k] for k in ('event_id', 'proposal_id', 'batch_id')}
    resumed = agent.compare_event_quotations(lookup)
    assert all(q['vendor_id'] == 'B' for q in resumed['data']['quotations'])
    assert all(q['vendor_id'] == 'A' for q in second['data']['quotations'])
    assert len(agent.llm.calls) == 2


def test_invalid_event_is_rejected_before_policy_call():
    agent, supplier, request = fixture_agent()
    request['services'] *= 2
    assert agent.procure_services(request)['status'] == 'needs_input'
    assert agent.llm.calls == [] and supplier.calls == []


def test_rule_scores_are_stable_and_tampered_weights_are_rejected():
    def candidate(vendor, price, rating, capacity):
        return {'vendor_id': vendor, 'offering_id': vendor + '-O', 'total_price_cents': price,
                'rating': rating, 'guest_capacity': capacity}
    candidates = [candidate('B', 10000, 4, 50), candidate('A', 10000, 4, 50), candidate('C', 0, 3, 100)]
    policy = VendorRankingService.policy('P')
    result = VendorRankingService.rank(candidates, policy, count=3, stage='shortlist')
    assert [candidates[i]['vendor_id'] for i, _ in result['ranked']] == ['C', 'A', 'B']
    capacity = VendorRankingService.rank(candidates, VendorRankingService.policy('C'), count=3, stage='comparison')
    assert capacity['ranked'][0][0] == 2
    policy['weights']['price'] = 1
    with pytest.raises(ValueError, match='supported definition'):
        VendorRankingService.rank(candidates, policy, count=3, stage='shortlist')


def test_constructor_policy_mode_is_explicit():
    assert isinstance(build_agent().llm, MockLLMClient)
    with pytest.raises(ValueError):
        build_agent(policy_ranking=True, compact_llm=False)
    with pytest.raises(ValueError):
        build_agent(policy_ranking=True, batch_services=True)
    with pytest.raises(TypeError):
        build_agent(policy_ranking='yes')


def test_live_policy_mode_makes_one_supported_request_and_runs_both_stages(monkeypatch, capsys):
    from examples import shared_catalog_procurement_example as demo
    from src.llm import CampusQwenClient
    payloads = []
    monkeypatch.setattr(CampusQwenClient, 'from_env', classmethod(
        lambda cls, **kw: cls('https://test.example/chat', 'test-key', 'test', **kw)))
    def transport(self, request):
        payload = json.loads(request.data)
        payloads.append(payload)
        assert set(payload) == {'model', 'messages'}
        prompt = payload['messages'][0]['content']
        assert 'candidate_rows' not in prompt and 'V-PHOTO' not in prompt
        return '{"choices":[{"finish_reason":"stop","message":{"content":"V"}}]}'
    monkeypatch.setattr(CampusQwenClient, '_open_and_read', transport)
    monkeypatch.setattr('sys.argv', ['demo', '--live', '--policy-ranking', '--verbose'])
    demo.main()
    result = json.loads(capsys.readouterr().out)
    assert result['selection_complete'] and result['llm_calls'] == len(payloads) == 1
    assert result['enquiry_count'] == 15 and len(result['quotations']) == 5
    assert result['policy_ranking'] and len(result['ranking_policies']) == 5


def test_policy_round_snapshots_and_sqlite_stay_on_caller_thread(tmp_path, monkeypatch):
    from threading import get_ident
    from src.services.procurement_record_service import ProcurementRecordService
    source, supplier, request = make_event_demo()
    records = ProcurementRecordService(tmp_path / 'policy.sqlite3')
    caller = get_ident()
    events = []
    def progress(event):
        assert get_ident() == caller
        events.append(event)
    agent = VendorProcurementManagerAgent(MockLLMClient('V'), source._vendor_service,
        quotation_service=supplier, record_service=records, compact_llm=True,
        policy_ranking=True, progress_callback=progress)
    original = records.save_quotations
    def save(*args, **kwargs):
        assert get_ident() == caller
        return original(*args, **kwargs)
    monkeypatch.setattr(records, 'save_quotations', save)
    prepared = agent.prepare_event_enquiries(request)
    lookup = {k: prepared['data'][k] for k in ('event_id', 'proposal_id', 'batch_id')}
    snapshot = prepared['data']['service_rounds'][0]
    snapshot['context']['ranking_policy']['code'] = 'Q'
    assert agent.request_event_quotations(lookup)['status'] == 'success'
    result = agent.compare_event_quotations(lookup)
    assert result['status'] == 'success'
    assert result['data']['ranking_policies']['photography']['code'] == 'V'
    assert len(records.get_quotations(request['event_id'], request['proposal_id'])) == 10
    assert [e['stage'] for e in events if e['state'] == 'submitted'] == ['policy']
    assert [e['stage'] for e in events if e['state'] == 'ranked_by_code'] == ['shortlist', 'comparison']
