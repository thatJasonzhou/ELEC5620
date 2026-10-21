"""Offline financial skeleton contracts; no budget or payment implementation."""
from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime, timezone
import inspect
import socket

import pytest

from src.agents.base import AIAgent
from src.agents.financial_manager import FinancialManagerAgent
from src.llm import MockLLMClient
from src.services.payment_service import PaymentService
from src.shared.schemas import Budget, CustomerPayment, Payment, VendorPayment


ACTIONS = (
    "prepare_budget", "update_proposal_cost", "record_customer_payment",
    "settle_vendor_payment", "reconcile_payments",
)
NOW = datetime(2026, 10, 21, 0, 0, tzinfo=timezone.utc)


class UnusedPaymentService(PaymentService):
    """Test-only tripwire: the foundation must not call a payment provider."""

    def process_payment(self, payment):
        pytest.fail("Foundation called process_payment")

    def verify_payment(self, transaction_reference):
        pytest.fail("Foundation called verify_payment")

    def refund_payment(self, transaction_reference, amount_cents):
        pytest.fail("Foundation called refund_payment")


@pytest.fixture
def worker(monkeypatch):
    def no_network(*args, **kwargs):
        pytest.fail("Foundation attempted network access")
    monkeypatch.setattr(socket, "socket", no_network)
    llm = MockLLMClient([])
    llm.set_exception(AssertionError("Foundation called LLM"))
    return FinancialManagerAgent(llm, UnusedPaymentService())


def customer(**changes):
    return CustomerPayment(**{
        "payment_id": "CP1", "event_id": "EV1", "amount_cents": 123,
        "created_at": NOW, "status": "caller-defined",
        "customer_id": "C1", "payment_type": "caller-defined",
        "due_date": date(2026, 11, 1), **changes,
    })


def vendor(**changes):
    return VendorPayment(**{
        "payment_id": "VP1", "event_id": "EV1", "amount_cents": 123,
        "created_at": NOW, "status": "caller-defined", "vendor_id": "V1",
        "vendor_booking_id": "VB1", "invoice_number": "INV1", **changes,
    })


def budget(**changes):
    # Caller-supplied independent values deliberately imply no pricing formula.
    return Budget(**{
        "budget_id": "B1", "event_id": "EV1", "vendor_cost_cents": 123,
        "contingency_amount_cents": 7, "tax_amount_cents": 9,
        "customer_price_cents": 501, "status": "caller-defined", **changes,
    })


def test_inheritance_and_abstract_contracts(worker):
    assert isinstance(worker, AIAgent)
    assert isinstance(customer(), Payment) and isinstance(vendor(), Payment)
    assert inspect.isabstract(Payment) and inspect.isabstract(PaymentService)
    for cls in (Payment, PaymentService):
        with pytest.raises(TypeError):
            cls()


def test_incomplete_service_cannot_be_instantiated():
    class IncompleteService(PaymentService):
        def process_payment(self, payment):
            raise NotImplementedError
    with pytest.raises(TypeError):
        IncompleteService()


@pytest.mark.parametrize("llm,service", [
    (object(), UnusedPaymentService()), (MockLLMClient(), object()),
])
def test_invalid_dependencies(llm, service):
    with pytest.raises(TypeError):
        FinancialManagerAgent(llm, service)


@pytest.mark.parametrize("action", ACTIONS)
def test_legal_actions_return_error_without_side_effects(worker, action):
    request = {"event_id": "EV1", "action": action, "extra": {"items": [1]}}
    before = deepcopy(request)
    result = worker.handle(request)
    assert set(result) == {"event_id", "agent", "timestamp", "status", "message", "data"}
    assert result["event_id"] == "EV1" and result["agent"] == "finance"
    assert result["status"] == "error" and "NOT_IMPLEMENTED" in result["message"]
    assert result["data"] == {} and request == before and not worker.llm.calls
    assert datetime.fromisoformat(result["timestamp"]).utcoffset() is not None


@pytest.mark.parametrize("payload,expected_id", [
    ({}, None), ({"event_id": 1, "action": "prepare_budget"}, None),
    ({"event_id": " ", "action": "prepare_budget"}, None),
    ({"event_id": "EV1"}, "EV1"),
    ({"event_id": "EV1", "action": ""}, "EV1"),
    ({"event_id": "EV1", "action": "unknown"}, "EV1"),
    ({"event_id": "EV1", "action": []}, "EV1"),
])
def test_invalid_outer_input_needs_input(worker, payload, expected_id):
    result = worker.handle(payload)
    assert result["status"] == "needs_input" and result["event_id"] == expected_id
    assert result["data"] == {} and not worker.llm.calls


@pytest.mark.parametrize("payload", [None, [], "request", 1])
def test_non_object_request_errors(worker, payload):
    result = worker.handle(payload)
    assert result["status"] == "error" and result["event_id"] is None


@pytest.mark.parametrize("name,args", [
    ("prepare_budget", (None, [])), ("update_proposal_cost", (None, None)),
    ("record_customer_payment", (None,)), ("settle_vendor_payment", (None,)),
    ("reconcile_payments", ("EV1",)),
])
def test_direct_agent_business_methods_are_unimplemented(worker, name, args):
    with pytest.raises(NotImplementedError, match="NOT_IMPLEMENTED"):
        getattr(worker, name)(*args)


def test_optional_facts_remain_absent_and_states_are_caller_supplied():
    c, v, b = customer(), vendor(), budget()
    assert c.paid_at is None and c.transaction_reference is None
    assert v.approved_at is None and v.paid_at is None and v.transaction_reference is None
    assert c.status == v.status == b.status == c.payment_type == "caller-defined"
    assert c.created_at == NOW and c.due_date == date(2026, 11, 1)
    assert b.customer_price_cents == 501  # No automatic total/recalculation.


@pytest.mark.parametrize("factory,field", [
    (budget, "vendor_cost_cents"), (budget, "contingency_amount_cents"),
    (budget, "tax_amount_cents"), (budget, "customer_price_cents"),
    (customer, "amount_cents"), (vendor, "amount_cents"),
])
@pytest.mark.parametrize("value", [True, 1.5, "100", -1, None])
def test_invalid_cents_are_rejected(factory, field, value):
    with pytest.raises(ValueError):
        factory(**{field: value})


@pytest.mark.parametrize("factory,field", [
    (budget, "budget_id"), (budget, "event_id"), (budget, "status"),
    (customer, "payment_id"), (customer, "event_id"), (customer, "customer_id"),
    (customer, "status"), (customer, "payment_type"),
    (customer, "transaction_reference"), (vendor, "vendor_id"),
    (vendor, "vendor_booking_id"), (vendor, "invoice_number"),
])
@pytest.mark.parametrize("value", [" ", 1, False])
def test_invalid_text_fields_are_rejected(factory, field, value):
    with pytest.raises(ValueError):
        factory(**{field: value})


@pytest.mark.parametrize("factory,field", [
    (customer, "created_at"), (customer, "paid_at"), (vendor, "approved_at"),
])
@pytest.mark.parametrize("value", [datetime(2026, 10, 21), "2026-10-21", date(2026, 10, 21)])
def test_datetime_fields_require_timezone(factory, field, value):
    with pytest.raises(ValueError):
        factory(**{field: value})


@pytest.mark.parametrize("value", [None, "2026-11-01", NOW])
def test_due_date_requires_date_only(value):
    with pytest.raises(ValueError):
        customer(due_date=value)


@pytest.mark.parametrize("factory,methods", [
    (budget, [("add_vendor_quotation", (None,)), ("calculate_total", ()),
              ("approve", ()), ("revise", ())]),
    (customer, [("initiate", ()), ("confirm", ()), ("fail", ("reason",)),
                ("record_payment", ()), ("verify_amount", ())]),
    (vendor, [("initiate", ()), ("confirm", ()), ("fail", ("reason",)),
              ("validate_invoice", ()), ("approve_settlement", ()), ("mark_paid", ())]),
])
def test_domain_methods_raise_without_mutating_records(factory, methods):
    record = factory()
    before = asdict(record)
    for name, args in methods:
        with pytest.raises(NotImplementedError, match="NOT_IMPLEMENTED"):
            getattr(record, name)(*args)
        assert asdict(record) == before


def test_service_verify_signature_preserves_class_diagram():
    assert list(inspect.signature(PaymentService.verify_payment).parameters) == [
        "self", "transaction_reference",
    ]
