"""UC4 budget validation and selected quotation handling."""
from copy import deepcopy

import pytest

from src.agents.financial_manager import FinancialManagerAgent
from src.llm import MockLLMClient
from src.services.payment_service import PaymentService


class UnusedPayments(PaymentService):
    def process_payment(self, payment):
        pytest.fail("payment called")

    def verify_payment(self, transaction_reference):
        pytest.fail("payment called")

    def refund_payment(self, transaction_reference, amount_cents):
        pytest.fail("payment called")


def make_worker():
    llm = MockLLMClient()
    llm.set_exception(AssertionError("LLM must not calculate money"))
    return FinancialManagerAgent(llm, UnusedPayments())


def budget_request():
    quote = dict(event_id="E1", proposal_id="P1", quotation_id="Q1",
                 vendor_id="V1", offering_id="O1", service_type="catering",
                 event_date="2026-12-05", guest_count=120,
                 quoted_total_cents=10000, available=True, mock=True)
    return dict(event_id="E1", action="prepare_budget",
                event=dict(event_id="E1", event_date="2026-12-05", guest_count=120,
                           budget_limit_cents=13000),
                proposal=dict(event_id="E1", proposal_id="P1", required_services=["catering"]),
                quotations=[quote], selected_quotation_ids=["Q1"])


@pytest.mark.parametrize("limit,status,difference", [(13000,"success",0), (12000,"success",0), (11999,"blocked",1)])
def test_budget_boundaries_and_no_side_effects(limit, status, difference):
    request = budget_request()
    request["event"]["budget_limit_cents"] = limit
    before = deepcopy(request)
    worker = make_worker()
    result = worker.handle(request)
    assert result["status"] == status
    data = result["data"]
    assert (data["vendor_total_cents"], data["service_fee_cents"], data["contingency_cents"]) == (10000,1000,1000)
    assert data["estimated_total_cents"] == 12000
    assert data["over_budget_cents"] == difference
    assert data["within_budget"] is (difference == 0)
    assert data["budget_valid"]
    assert not worker.llm.calls and request == before


def test_missing_service_and_selected_quote():
    r = budget_request()
    r["proposal"]["required_services"].append("venue")
    assert make_worker().handle(r)["status"] == "blocked"
    r = budget_request()
    r["quotations"] = []
    assert make_worker().handle(r)["status"] == "blocked"


@pytest.mark.parametrize("field,value", [("event_id","other"), ("proposal_id","other"),
    ("event_date","2026-12-06"), ("guest_count",121), ("available",False),
    ("quoted_total_cents",True), ("quoted_total_cents",1.2),
    ("quoted_total_cents","100"), ("quoted_total_cents",-1)])
def test_invalid_selected_quote(field, value):
    r = budget_request()
    r["quotations"][0][field] = value
    assert make_worker().handle(r)["status"] == "error"


def test_duplicates_and_bad_selection():
    r = budget_request()
    r["quotations"].append(deepcopy(r["quotations"][0]))
    assert make_worker().handle(r)["status"] == "error"
    r = budget_request()
    r["selected_quotation_ids"] *= 2
    assert make_worker().handle(r)["status"] == "needs_input"


@pytest.mark.parametrize("field,value", [("budget_limit_cents",True), ("budget_limit_cents",1.1),
    ("budget_limit_cents","100"), ("budget_limit_cents",-1), ("event_id","wrong")])
def test_bad_event(field, value):
    r = budget_request()
    r["event"][field] = value
    assert make_worker().handle(r)["status"] == "needs_input"


def test_selected_only_changed_quote_requires_new_budget():
    r = budget_request()
    alternate = {**r["quotations"][0], "quotation_id":"Q2", "vendor_id":"V2", "quoted_total_cents":999999}
    r["quotations"].append(alternate)
    worker = make_worker()
    first = worker.handle(r)["data"]
    assert first["vendor_total_cents"] == 10000
    r["quotations"][0]["quoted_total_cents"] = 20000
    second = worker.handle(r)["data"]
    assert second["vendor_total_cents"] == 20000
    assert first["quotation_fingerprint"] != second["quotation_fingerprint"]
    assert first["within_budget"] and not second["within_budget"]


def test_half_cent_rounding_and_explicit_zero_tax():
    r = budget_request()
    r["quotations"][0]["quoted_total_cents"] = 5
    data = make_worker().handle(r)["data"]
    assert data["service_fee_cents"] == data["contingency_cents"] == 1
    assert data["estimated_total_cents"] == 7


def test_invalid_request_never_carries_valid_budget():
    request = budget_request()
    request["quotations"][0]["quoted_total_cents"] = True
    result = make_worker().handle(request)
    assert result["data"]["budget_valid"] is False
