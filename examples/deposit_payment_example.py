"""Offline simulated customer click. Approval below is TEST FIXTURE input only."""
import json
from examples.customer_quotation_example import generate_customer_quotation
from src.agents.financial_manager import FinancialManagerAgent
from src.llm import MockLLMClient
from src.services.mock_payment_service import MockPaymentService
from src.services.vendor_booking_service import VendorBookingService, MockVendorBookingService


def run_demo():
    request, budget, result = generate_customer_quotation()
    quote = result["data"]["customer_quotation"]
    # Simulated external Planning/customer approval, never produced by Financial.
    approval_fixture = {k: quote[k] for k in (
        "event_id", "proposal_id", "quotation_fingerprint", "customer_quotation_id")}
    approval_fixture.update(approved=True, approved_quotation_ids=quote["selected_quotation_ids"])
    request.update(budget=budget, customer_quotation=quote, approval=approval_fixture,
                   customer_id="MOCK-CUSTOMER", due_date="2026-12-01")
    worker = FinancialManagerAgent(MockLLMClient(), MockPaymentService())
    pending = worker.handle({**request, "action": "prepare_deposit_request"})
    if pending["status"] != "success":
        raise ValueError(pending["message"])
    deposit = pending["data"]["deposit"]
    assert deposit["status"] == "pending"
    # This separate call represents the future user's Pay Deposit click.
    click = {**request, "action": "simulate_deposit_payment", "simulate": True,
             "deposit_request_id": deposit["deposit_request_id"], "amount_cents": deposit["amount_cents"]}
    paid = worker.handle(click)
    assert paid["data"]["deposit"]["status"] == "paid"
    assert worker.handle(click)["data"] == paid["data"]
    # Reuse existing KAN-20 validation, with NO configured supplier confirmation.
    # Reaching its unconfigured reply proves all budget/approval/deposit gates passed.
    verification = VendorBookingService(MockVendorBookingService([])).confirm_bookings({
        "event_id": request["event_id"], "proposal_id": quote["proposal_id"],
        "quotations": quote["vendor_cost_breakdown"], "approval": approval_fixture,
        **paid["data"]})
    assert verification["status"] == "blocked"
    assert verification["data"]["supplier_replies"][0]["status"] == "unconfigured"
    assert not verification["data"]["bookings"]
    return pending, paid, verification


if __name__ == "__main__":
    print("MOCK ONLY: external approval fixture; explicit simulated Pay Deposit click; no booking.")
    for result in run_demo():
        print(json.dumps(result, indent=2))
