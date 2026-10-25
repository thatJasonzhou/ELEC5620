"""Concurrency is proven with barriers, not wall-clock speed assertions."""
import json
from threading import Barrier, Lock, get_ident

import pytest

from examples.event_procurement_example import SERVICE_TYPES, make_event_demo, mock_compare
from src.agents.vendor_procurement_manager import VendorProcurementManagerAgent
from src.llm import LLMClient, LLMError, MockLLMClient
from src.llm.batch import complete_jobs
from src.services.procurement_record_service import ProcurementRecordService


class BarrierModel(LLMClient):
    """Require three overlapping requests in each phase or fail the test."""
    def __init__(self):
        self.lock = Lock()
        self.barriers = {phase: Barrier(3) for phase in ("shortlist", "comparison")}
        self.counts = {phase: 0 for phase in self.barriers}
        self.active = 0
        self.peak = 0
        self.threads = set()

    def complete(self, messages):
        phase = "comparison" if messages[-1]["content"].startswith("{") else "shortlist"
        with self.lock:
            index = self.counts[phase]
            self.counts[phase] += 1
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.threads.add(get_ident())
        try:
            if index < 3:
                self.barriers[phase].wait(timeout=5)
            return mock_compare(messages)
        finally:
            with self.lock:
                self.active -= 1


def parallel_agent(llm=None, *, workers=3, progress=None, records=None):
    source, supplier, request = make_event_demo(llm=llm)
    agent = VendorProcurementManagerAgent(
        source.llm, source._vendor_service, quotation_service=supplier,
        record_service=records, llm_concurrency=workers, progress_callback=progress)
    return agent, supplier, request


def selection(result):
    return [(q["service_type"], q["vendor_id"], q["offering_id"], q["quoted_total_cents"])
            for q in result["data"]["quotations"]]


def test_pool_overlaps_caps_three_and_keeps_result_order_and_callback_thread():
    barrier = Barrier(3)
    lock = Lock()
    caller = get_ident()
    active = peak = 0
    callback_threads = []
    events = []

    def reply(messages):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            barrier.wait(timeout=5)
            return messages[0]["content"]
        finally:
            with lock:
                active -= 1

    def progress(event):
        callback_threads.append(get_ident())
        events.append(event)

    jobs = [(str(i), [{"role": "user", "content": str(i)}]) for i in range(6)]
    results = complete_jobs(MockLLMClient(reply), jobs, max_workers=3,
                            stage="test", progress=progress)
    assert [r.text for r in results] == [str(i) for i in range(6)]
    assert all(not r.failed for r in results)
    assert peak == 3 and active == 0
    assert set(callback_threads) == {caller}
    assert len([e for e in events if e["state"] == "received"]) == 6


def test_parallel_workflow_keeps_all_mutations_and_sqlite_on_caller_thread(tmp_path, monkeypatch):
    model = BarrierModel()
    records = ProcurementRecordService(tmp_path / "parallel.sqlite3")
    caller = get_ident()
    events = []

    def progress(event):
        assert get_ident() == caller
        events.append(event)

    agent, supplier, request = parallel_agent(model, records=records, progress=progress)
    mutations = []
    for owner, names in ((agent._enquiry_service, ("create_round", "create_batch", "submit_reply")),
                         (records, ("save_quotations",))):
        for name in names:
            original = getattr(owner, name)

            def guarded(*args, _original=original, _name=name, **kwargs):
                assert get_ident() == caller, _name
                mutations.append(_name)
                return _original(*args, **kwargs)

            monkeypatch.setattr(owner, name, guarded)
    result = agent.procure_services(request)
    assert result["status"] == "success"
    assert model.peak == 3 and caller not in model.threads
    assert model.counts == {"shortlist": 5, "comparison": 5}
    assert [q["service_type"] for q in result["data"]["quotations"]] == list(SERVICE_TYPES)
    assert len(supplier.calls) == 15
    assert len(records.get_quotations(request["event_id"], request["proposal_id"])) == 10
    assert {"create_round", "create_batch", "submit_reply", "save_quotations"} <= set(mutations)
    assert len(events) == 20
    assert all(set(e) <= {"stage", "service_type", "state", "elapsed_seconds"} for e in events)


@pytest.mark.parametrize("workers", [1, 2, 3, 5])
def test_parallel_and_serial_selections_have_same_facts(workers):
    baseline, _, request = make_event_demo()
    expected = baseline.procure_services(request)
    agent, _, request = parallel_agent(workers=workers)
    result = agent.procure_services(request)
    assert result["status"] == "success"
    assert selection(result) == selection(expected)


def test_comparison_failure_blocks_handoff_and_can_retry_without_reenquiry():
    def reply(messages):
        text = messages[-1]["content"]
        if text.startswith("{") and json.loads(text)["context"]["service_type"] == "catering":
            raise LLMError("transport unavailable")
        return mock_compare(messages)

    agent, supplier, request = parallel_agent(MockLLMClient(reply))
    result = agent.procure_services(request)
    assert result["status"] == "error"
    assert not result["data"]["selection_complete"]
    assert result["data"]["quotations"] == result["data"]["selected_quotation_ids"] == []
    failed = [r for r in result["data"]["service_results"] if r["status"] == "error"]
    assert [r["service_type"] for r in failed] == ["catering"]
    assert len(result["data"]["candidate_quotations"]) == 10
    agent.llm = MockLLMClient(mock_compare)
    lookup = {k: result["data"][k] for k in ("event_id", "proposal_id", "batch_id")}
    retry = agent.compare_event_quotations(lookup)
    assert retry["status"] == "success" and len(retry["data"]["quotations"]) == 5
    assert len(supplier.calls) == 15


@pytest.mark.parametrize("kind", ["transport", "invalid_output"])
def test_failed_shortlist_never_requests_suppliers(kind):
    def reply(messages):
        if "- service_type: catering" in messages[-1]["content"]:
            if kind == "transport":
                raise LLMError("unavailable")
            return '{"recommendations": []}'
        return mock_compare(messages)

    agent, supplier, request = parallel_agent(MockLLMClient(reply))
    result = agent.procure_services(request)
    assert result["status"] == "error"
    assert not result["data"]["selection_complete"]
    assert not result["data"]["quotations"]
    assert not supplier.calls


def test_pending_blocks_all_second_phase_llm_requests(monkeypatch):
    agent, supplier, request = parallel_agent()
    original = supplier.request_quotation

    def pending(**kwargs):
        result = original(**kwargs)
        if kwargs["offering_id"] == "A-catering":
            result.update(status="pending", available=None, quoted_total_cents=None)
        return result

    monkeypatch.setattr(supplier, "request_quotation", pending)
    result = agent.procure_services(request)
    assert result["status"] == "blocked"
    assert not result["data"]["selection_complete"]
    assert len(agent.llm.calls) == 5


def test_invalid_activity_has_no_calls_or_progress():
    events = []
    agent, supplier, request = parallel_agent(progress=events.append)
    result = agent.procure_services({**request, "services": request["services"] * 2})
    assert result["status"] == "needs_input"
    assert not agent.llm.calls and not supplier.calls and not events


@pytest.mark.parametrize("workers", [0, 6, True, 2.5, "3"])
def test_concurrency_requires_one_to_five_integer(workers):
    with pytest.raises(ValueError, match="llm_concurrency"):
        parallel_agent(workers=workers)


def test_progress_must_be_callable():
    with pytest.raises(TypeError, match="progress_callback"):
        parallel_agent(progress="print")
