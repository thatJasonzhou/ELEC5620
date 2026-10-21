"""Approved GST-inclusive V1 acceptance and Procurement gates."""
from copy import deepcopy
import pytest
from test_budget_check import budget_request, make_worker
from test_vendor_bookings import request as booking_request, service, quote


def v1_request(cents=1005, limit=1207):
    request = budget_request()
    request["quotations"][0]["quoted_total_cents"] = cents
    request["event"]["budget_limit_cents"] = limit
    return request


@pytest.mark.parametrize("limit,status,over", [(1300,"success",0),(1207,"success",0),(1206,"blocked",1)])
def test_rounding_gst_and_boundaries(limit,status,over):
    request = v1_request(limit=limit)
    before = deepcopy(request)
    worker = make_worker()
    result = worker.handle(request)
    assert result["status"] == status
    data = result["data"]
    assert data["vendor_total_cents"] == 1005
    assert data["service_fee_cents"] == data["contingency_cents"] == 101
    assert data["estimated_total_cents"] == 1207
    assert data["tax_amount_cents"] == 0
    assert data["price_basis"] == "GST-inclusive"
    assert data["budget_valid"] is True
    assert data["over_budget_cents"] == over
    assert request == before and not worker.llm.calls


@pytest.mark.parametrize("cents,fee", [(0,0),(1000,100),(1004,100),(1005,101),(1006,101),(10**40+5,10**39+1)])
def test_exact_independent_ten_percent(cents,fee):
    data = make_worker().handle(v1_request(cents,10**50))["data"]
    assert data["service_fee_cents"] == data["contingency_cents"] == fee
    assert data["estimated_total_cents"] == cents+2*fee


def formal_booking():
    item = booking_request()
    req = v1_request()
    req["event"].update(event_id="EV001", budget_limit_cents=3000000)
    req["event_id"] = "EV001"
    req["proposal"].update(event_id="EV001",proposal_id="P1")
    req["quotations"] = [quote()]
    req["selected_quotation_ids"] = ["Q1"]
    item["budget"] = make_worker().handle(req)["data"]
    item["budget"]["deposit_due_cents"] = 555000  # separate existing trusted handoff
    return item


def test_v1_can_pass_all_existing_booking_gates():
    booking,supplier = service()
    result = booking.confirm_bookings(formal_booking())
    assert result["status"] == "success" and len(supplier.calls) == 1


@pytest.mark.parametrize("change", ["amount","fingerprint","approval","deposit","fee","marker"])
def test_v1_rejects_stale_tampered_or_unapproved(change):
    item = formal_booking()
    if change == "amount": item["quotations"][0]["quoted_total_cents"] += 1
    if change == "fingerprint": item["budget"]["quotation_fingerprint"] = "OLD"
    if change == "approval": item["approval"]["approved"] = False
    if change == "deposit": item["deposit"]["amount_cents"] = 0
    if change == "fee": item["budget"]["service_fee_cents"] += 1
    if change == "marker": item["budget"]["budget_valid"] = "true"
    booking,supplier = service()
    assert booking.confirm_bookings(item)["status"] in ("blocked","needs_input")
    assert not supplier.calls


def test_formal_recalculation_changes_fingerprint():
    request = v1_request()
    worker = make_worker()
    first = worker.handle(request)["data"]
    request["quotations"][0]["quoted_total_cents"] += 10
    second = worker.handle(request)["data"]
    assert first["quotation_fingerprint"] != second["quotation_fingerprint"]
    assert first["estimated_total_cents"] != second["estimated_total_cents"]


@pytest.mark.parametrize("change", ["missing-service","duplicate","event","proposal","float","bool","string","negative"])
def test_v1_rejects_invalid_inputs(change):
    request = v1_request()
    if change == "missing-service": request["proposal"]["required_services"].append("venue")
    if change == "duplicate": request["quotations"].append(deepcopy(request["quotations"][0]))
    if change == "event": request["quotations"][0]["event_id"] = "OTHER"
    if change == "proposal": request["quotations"][0]["proposal_id"] = "OTHER"
    for name, value in [("float",1.1),("bool",True),("string","1005"),("negative",-1)]:
        if change == name: request["quotations"][0]["quoted_total_cents"] = value
    result = make_worker().handle(request)
    assert result["status"] in ("blocked", "error")
    assert result["data"]["budget_valid"] is False
    assert "estimated_total_cents" not in result["data"]


@pytest.mark.parametrize("field", ["budget_valid", "price_basis", "service_fee_cents",
    "selected_quotation_ids", "required_services", "quotation_fingerprint"])
def test_incomplete_budget_cannot_authorize_booking(field):
    item = formal_booking()
    del item["budget"][field]
    booking, supplier = service()
    assert booking.confirm_bookings(item)["status"] == "needs_input"
    assert not supplier.calls


def test_budget_owns_detached_selected_quotation_snapshots():
    from src.shared.schemas import Budget
    selected = quote(cents=1005)
    budget = Budget(budget_id="B1", event_id="EV001", vendor_cost_cents=0,
        contingency_amount_cents=0, tax_amount_cents=0, customer_price_cents=0,
        status="Calculated")
    budget.add_vendor_quotation(selected)
    selected["quoted_total_cents"] = 9000
    assert budget.calculate_total() == 1207
    with pytest.raises(ValueError, match="duplicate"):
        budget.add_vendor_quotation(selected)
    assert budget.calculate_total() == 1207
