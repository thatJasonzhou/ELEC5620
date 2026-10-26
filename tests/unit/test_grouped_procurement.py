"""Grouped phases reduce calls while preserving supplier facts and handoff gates."""
from copy import deepcopy
import json
from threading import get_ident

import pytest

from examples.event_procurement_example import SERVICE_TYPES, make_event_demo
from examples.shared_catalog_procurement_example import build_agent, event_request, mock_service_group_compare
from src.agents.vendor_procurement_manager import VendorProcurementManagerAgent
from src.llm import LLMError, MockLLMClient
from src.services.procurement_record_service import ProcurementRecordService


def facts(result):
    return [(q['service_type'], q['vendor_id'], q['offering_id'], q['quoted_total_cents'])
            for q in result['data']['quotations']]


@pytest.mark.parametrize('workers', [1, 2, 5])
@pytest.mark.parametrize('city', ['Sydney', 'Melbourne'])
def test_grouped_and_individual_phases_select_same_supplied_facts(workers, city):
    request = event_request(city=city)
    serial = build_agent(llm_concurrency=workers)
    grouped = build_agent(batch_services=True, llm_concurrency=workers)
    baseline = serial.procure_services(request)
    result = grouped.procure_services(request)
    assert result['status'] == 'success' and result['data']['selection_complete']
    assert facts(result) == facts(baseline)
    assert len(serial.llm.calls) == 10 and len(grouped.llm.calls) == 2
    assert sum(len(r['enquiries']) for r in result['data']['service_rounds']) == 15
    assert [json.loads(call[-1]['content'])['stage'] for call in grouped.llm.calls] == ['shortlist', 'comparison']
    assert all(len(json.loads(call[-1]['content'])['services']) == 5 for call in grouped.llm.calls)


def test_single_service_keeps_two_existing_individual_requests():
    agent = build_agent(batch_services=True)
    result = agent.procure_services(event_request(services=['photography']))
    assert result['status'] == 'success' and len(agent.llm.calls) == 2
    assert all('candidate_rows' in json.loads(call[-1]['content']) for call in agent.llm.calls)


def test_reversed_service_results_map_to_original_order_and_quote_prices(tmp_path, monkeypatch):
    records = ProcurementRecordService(tmp_path / 'grouped.sqlite3')
    _, suppliers, request = make_event_demo()
    caller = get_ident()
    observed_stages = []
    def model(messages):
        payload = json.loads(messages[-1]['content'])
        observed_stages.append(payload['stage'])
        assert len(suppliers.calls) == (0 if payload['stage'] == 'shortlist' else 15)
        if payload['stage'] == 'comparison':
            photo = next(s for s in payload['services'] if s['service'] == 'photography')
            rows = [dict(zip(photo['columns'], row)) for row in photo['candidate_rows']]
            assert sorted(r['price_cents'] for r in rows) == [95000, 130000]
            assert sorted(r['estimate_cents'] for r in rows) == [90000, 95000]
        parsed = json.loads(mock_service_group_compare(messages))
        parsed['services'].reverse()
        return json.dumps(parsed)
    fixture, _, _ = make_event_demo()
    agent = VendorProcurementManagerAgent(MockLLMClient(model), fixture._vendor_service,
        quotation_service=suppliers, record_service=records, compact_llm=True, batch_services=True)
    for owner, method in ((agent._enquiry_service, 'create_round'),
                          (agent._enquiry_service, 'submit_reply'), (records, 'save_quotations')):
        original = getattr(owner, method)
        def guarded(*args, _original=original, **kwargs):
            assert get_ident() == caller
            return _original(*args, **kwargs)
        monkeypatch.setattr(owner, method, guarded)
    result = agent.procure_services(request)
    assert result['status'] == 'success' and observed_stages == ['shortlist', 'comparison']
    assert [q['service_type'] for q in result['data']['quotations']] == list(SERVICE_TYPES)
    assert all(q['vendor_id'] == 'B' for q in result['data']['quotations'])
    assert len(records.get_quotations(request['event_id'], request['proposal_id'])) == 10


@pytest.mark.parametrize('fault', ['missing_service', 'duplicate_service', 'unknown_service', 'extra_field', 'bad_json',
                                    'boolean_index', 'missing_candidate', 'unknown_index', 'invented_price'])
def test_invalid_group_output_never_releases_complete_selection(fault):
    def model(messages):
        parsed = json.loads(mock_service_group_compare(messages))
        if fault == 'missing_service':
            parsed['services'].pop()
        elif fault == 'duplicate_service':
            parsed['services'][1] = deepcopy(parsed['services'][0])
        elif fault == 'unknown_service':
            parsed['services'][0]['service'] = 'not_requested'
        elif fault == 'extra_field':
            parsed['override'] = 1
        elif fault == 'bad_json':
            return 'not JSON'
        elif fault == 'boolean_index':
            parsed['services'][0]['ranked'][0][0] = True
        elif fault == 'missing_candidate':
            parsed['services'][0]['ranked'].pop()
        elif fault == 'unknown_index':
            parsed['services'][0]['ranked'][0][0] = 999
        else:
            parsed['services'][0]['quoted_total_cents'] = 1
        return json.dumps(parsed)
    agent = build_agent(batch_services=True)
    agent.llm = MockLLMClient(model)
    result = agent.procure_services(event_request())
    assert result['status'] == 'error' and not result['data']['selection_complete']
    assert result['data']['quotations'] == [] and len(agent.llm.calls) == 1


def test_comparison_failure_preserves_quotes_and_can_resume_without_reenquiry():
    _, suppliers, request = make_event_demo()
    fixture, _, _ = make_event_demo()
    def model(messages):
        payload = json.loads(messages[-1]['content'])
        if payload['stage'] == 'comparison':
            raise LLMError('timeout', code='timeout', retryable=True)
        return mock_service_group_compare(messages)
    agent = VendorProcurementManagerAgent(MockLLMClient(model), fixture._vendor_service,
        quotation_service=suppliers, compact_llm=True, batch_services=True)
    failed = agent.procure_services(request)
    assert failed['status'] == 'error' and not failed['data']['selection_complete']
    assert failed['data']['quotations'] == [] and len(failed['data']['candidate_quotations']) == 10
    assert len(suppliers.calls) == 15
    agent.llm = MockLLMClient(mock_service_group_compare)
    lookup = {k: failed['data'][k] for k in ('event_id', 'proposal_id', 'batch_id')}
    recovered = agent.compare_event_quotations(lookup)
    assert recovered['status'] == 'success' and len(agent.llm.calls) == 1
    assert len(suppliers.calls) == 15


def test_pending_reply_blocks_second_model_phase():
    agent = build_agent(batch_services=True)
    prepared = agent.prepare_event_enquiries(event_request())
    lookup = {k: prepared['data'][k] for k in ('event_id', 'proposal_id', 'batch_id')}
    result = agent.compare_event_quotations(lookup)
    assert result['status'] == 'blocked' and len(agent.llm.calls) == 1
    assert not result['data']['selection_complete']


def test_batching_requires_explicit_compact_protocol():
    with pytest.raises(ValueError, match='compact_llm'):
        build_agent(batch_services=True, compact_llm=False)
    with pytest.raises(TypeError, match='batch_services'):
        build_agent(batch_services='yes')


def test_grouped_live_workflow_uses_two_supported_shape_requests(monkeypatch, capsys):
    from examples import shared_catalog_procurement_example as demo
    from src.llm import CampusQwenClient
    payloads = []
    monkeypatch.setattr(CampusQwenClient, 'from_env', classmethod(
        lambda cls, **kw: cls('https://test.example/chat', 'test-key', 'test', **kw)))
    def transport(self, request):
        payload = json.loads(request.data)
        payloads.append(payload)
        return json.dumps({'choices': [{'finish_reason': 'stop', 'message': {
            'content': mock_service_group_compare(payload['messages'])}}]})
    monkeypatch.setattr(CampusQwenClient, '_open_and_read', transport)
    monkeypatch.setattr('sys.argv', ['demo', '--live', '--batch-services', '--verbose'])
    demo.main()
    summary = json.loads(capsys.readouterr().out)
    assert summary['selection_complete'] and summary['llm_calls'] == 2
    assert len(payloads) == 2 and all(set(p) == {'model', 'messages'} for p in payloads)


def test_grouped_expanded_categories_and_rejected_suppliers_preserve_valid_selection():
    services = ['videography', 'lighting', 'entertainment', 'transport', 'event_staff']
    agent = build_agent(batch_services=True)
    result = agent.procure_services(event_request(services=services, date='2026-12-17'))
    assert result['status'] == 'success' and len(agent.llm.calls) == 2
    assert [q['service_type'] for q in result['data']['quotations']] == services
    for service in result['data']['service_results']:
        assert len(service['data']['selected_quotations']) == 1
        assert all(q['status'] == 'accepted' for q in service['data']['selected_quotations'])
