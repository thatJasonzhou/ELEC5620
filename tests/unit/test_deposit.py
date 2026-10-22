"""Explicit, fail-closed mock deposit requests and payments."""
from copy import deepcopy
import pytest
from test_customer_quotation import quotation_request
from test_budget_check import make_worker
from src.agents.financial_manager import FinancialManagerAgent
from src.llm import MockLLMClient
from src.services.deposit_service import DepositService
from src.services.mock_payment_service import MockPaymentService


def deposit_request():
    r = quotation_request()
    q = make_worker().handle(r)["data"]["customer_quotation"]
    r.update(customer_quotation=q, customer_id="C1", due_date="2026-12-01",
             action="prepare_deposit_request",
             approval={**{k: q[k] for k in ("event_id", "proposal_id", "customer_quotation_id",
                                           "quotation_fingerprint")},
                       "approved": True, "approved_quotation_ids": q["selected_quotation_ids"]})
    return r


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("ELEC5620_DEPOSIT_RATE", "0.30")
    r = deposit_request()
    service = DepositService(MockPaymentService())
    return service, r


def pay_request(service, r):
    prepared = service.prepare(r)
    assert prepared["status"] == "success", prepared
    d = prepared["data"]["deposit"]
    return {**deepcopy(r), "simulate": True, "deposit_request_id": d["deposit_request_id"],
            "amount_cents": d["amount_cents"], "action": "simulate_deposit_payment"}


def test_pending_explicit_payment_and_retries(setup):
    service, r = setup
    before = deepcopy(r)
    pending = service.prepare(r)
    assert pending["data"]["deposit"]["status"] == "pending"
    assert service.records == []
    assert service.prepare(r) == pending
    p = pay_request(service, r)
    result = service.simulate_payment(p)
    assert result["data"]["deposit"]["status"] == "paid"
    assert service.simulate_payment(p) == result
    assert len(service.records) == 1 and r == before
    assert result["data"]["budget"]["deposit_due_cents"] == 362
    result["data"]["deposit"]["status"] = "failed"
    assert service.records[0]["status"] == "paid"


@pytest.mark.parametrize("change", ["missing-approval", "revoked", "fingerprint", "price",
    "proposal", "cq-price", "cq-id", "amount", "unknown", "no-click", "customer", "selection"])
def test_invalid_payments_never_record_success(setup, change):
    service, r = setup
    p = pay_request(service, r)
    if change == "missing-approval": p.pop("approval")
    if change == "revoked": p["approval"]["approved"] = False
    if change == "fingerprint": p["approval"]["quotation_fingerprint"] = "old"
    if change == "price": p["quotations"][0]["quoted_total_cents"] += 1
    if change == "proposal": p["proposal"]["revision"] = 2
    if change == "cq-price": p["customer_quotation"]["estimated_total_cents"] += 1
    if change == "cq-id": p["customer_quotation"]["customer_quotation_id"] = "other"
    if change == "amount": p["amount_cents"] += 1
    if change == "unknown": p["deposit_request_id"] = "unknown"
    if change == "no-click": p.pop("simulate")
    if change == "customer": p["customer_id"] = "other"
    if change == "selection": p["approval"]["approved_quotation_ids"] = []
    assert service.simulate_payment(p)["status"] == "blocked"
    assert service.records == []


@pytest.mark.parametrize("rate", ["", "0", "-1", "1.01", "nan", "Infinity", "wrong"])
def test_invalid_config(setup, monkeypatch, rate):
    service, r = setup
    monkeypatch.setenv("ELEC5620_DEPOSIT_RATE", rate)
    result = service.prepare(r)
    assert result["status"] == "blocked" and "ELEC5620_DEPOSIT_RATE" in result["message"]


def test_config_file_and_environment_precedence(monkeypatch, tmp_path):
    from src import financial_config as config
    from decimal import Decimal
    root = tmp_path / "src"
    root.mkdir()
    monkeypatch.setattr(config, "__file__", str(root / "financial_config.py"))
    monkeypatch.delenv("ELEC5620_DEPOSIT_RATE", raising=False)
    with pytest.raises(ValueError, match="required"):
        config.deposit_rate()
    (tmp_path / ".env").write_text('OTHER=ignored\nELEC5620_DEPOSIT_RATE="0.25" # example\n')
    assert config.deposit_rate() == Decimal("0.25")
    monkeypatch.setenv("ELEC5620_DEPOSIT_RATE", "1")
    assert config.deposit_rate() == Decimal("1")


def test_agent_workflow_does_not_call_llm(setup):
    _, r = setup
    llm = MockLLMClient()
    llm.set_exception(AssertionError("No LLM payment decisions"))
    worker = FinancialManagerAgent(llm, MockPaymentService())
    result = worker.handle(r)
    d = result["data"]["deposit"]
    result = worker.handle({**r, "action": "simulate_deposit_payment", "simulate": True,
        "deposit_request_id": d["deposit_request_id"], "amount_cents": d["amount_cents"]})
    assert result["data"]["deposit"]["status"] == "paid" and not llm.calls


def test_revocation_checked_even_on_retry(setup):
    service, r = setup
    p = pay_request(service, r)
    service.simulate_payment(p)
    p["approval"]["approved"] = False
    assert service.simulate_payment(p)["status"] == "blocked"
    assert len(service.records) == 1


def test_failed_mock_reply_does_not_mark_paid(setup, monkeypatch):
    service, r = setup
    p = pay_request(service, r)
    monkeypatch.setattr(service._payments, "process_payment", lambda payment: {"status": "failed"})
    assert service.simulate_payment(p)["status"] == "error"
    assert not service.records


@pytest.mark.parametrize("approval", [None, {}, {"approved": False}, {"approved": "true"}])
def test_prepare_requires_external_approval(setup, approval):
    service, r = setup
    r["approval"] = approval
    assert service.prepare(r)["status"] == "blocked"
    assert service._requests == {} and service.records == []


def test_half_up_and_full_rate(setup, monkeypatch):
    service, r = setup
    # Quotation total is 1207 cents; 50% = 603.5 -> 604, not bankers rounding.
    monkeypatch.setenv("ELEC5620_DEPOSIT_RATE", "0.5")
    assert service.prepare(r)["data"]["deposit"]["amount_cents"] == 604
    monkeypatch.setenv("ELEC5620_DEPOSIT_RATE", "1")
    other = DepositService(MockPaymentService())
    assert other.prepare(r)["data"]["deposit"]["amount_cents"] == 1207


def test_paid_request_cannot_prepare_second_payment(setup):
    service, r = setup
    p = pay_request(service, r)
    service.simulate_payment(p)
    assert service.prepare(r)["data"]["deposit"]["status"] == "paid"
    assert len(service.records) == 1
