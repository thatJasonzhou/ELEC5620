"""Offline Procurement -> Financial -> booking -> Operations integration demo.

Planner proposal, customer approval and deposit are explicitly MOCK fixtures.
Quotation, budget and booking use the real existing module implementations.
No external calls, real payments, database writes or LLM inference.
"""
import json
from pathlib import Path

from examples.budget_check_example import check_budget
from src.agents.event_operations import EventOperationsAgent
from src.agents.vendor_procurement_manager import VendorProcurementManagerAgent
from src.llm import MockLLMClient
from src.services.event_operations_service import InMemoryEventOperationsService
from src.services.vendor_booking_service import (MockVendorBookingService,
    VendorBookingService, quotation_fingerprint)
from src.services.vendor_procurement_service import VendorProcurementService
from src.services.vendor_quotation_service import MockVendorQuotationService

ROOT = Path(__file__).resolve().parents[1]


def build_demo_request():
    """Return fresh demo handoff data; never used implicitly for real imports."""
    llm = MockLLMClient()
    llm.set_exception(AssertionError("MVP must not call LLM"))
    vendor = VendorProcurementManagerAgent(llm,
        VendorProcurementService.from_json_file(ROOT / "data/vendor_catalog.json"),
        MockVendorQuotationService.from_json_file(ROOT / "data/mock_vendor_quotations.json"),
        VendorBookingService(MockVendorBookingService.from_json_file(ROOT / "data/mock_vendor_bookings.json")))
    enquiry = dict(event_id="EV001", proposal_id="P1", service_type="catering",
                   event_date="2026-12-05", guest_count=120, location="Melbourne")
    quotes_result = vendor.request_quotations(enquiry)
    if quotes_result["status"] != "success":
        raise RuntimeError("Demo mock quotations failed")
    quotations = quotes_result["data"]["quotations"]
    budget = check_budget(quotations, 3000000)
    if budget["status"] != "success":
        raise RuntimeError("Demo budget failed")
    linkage = dict(event_id="EV001", proposal_id="P1", quotation_fingerprint=quotation_fingerprint(quotations))
    confirmed = vendor.confirm_bookings({**enquiry, "quotations": quotations,
        "budget": {**budget["data"], "deposit_due_cents": 555000},
        "approval": {**linkage, "approved": True,
                     "approved_quotation_ids": [q["quotation_id"] for q in quotations]},
        "deposit": {**linkage, "payment_id": "MOCK-PAY1", "amount_cents": 555000,
                    "status": "paid", "mock": True}})
    proposal = {"event_id": "EV001", "proposal_id": "P1", "status": "Approved",
                "summary": "MOCK December event", "required_services": ["catering"],
                "timeline": [
                    {"title": "Guest welcome", "start_at": "2026-12-05T18:00:00+11:00",
                     "end_at": "2026-12-05T18:30:00+11:00"},
                    {"title": "Dinner service", "start_at": "2026-12-05T18:30:00+11:00",
                     "end_at": "2026-12-05T20:00:00+11:00"}]}
    return {"event_id": "EV001", "event_date": "2026-12-05", "proposal": proposal,
            "procurement_result": confirmed, "action": "generate_execution_plan"}


def run_demo():
    request = build_demo_request()
    agent = EventOperationsAgent(MockLLMClient(), InMemoryEventOperationsService())
    result = agent.handle(request)
    assert result["status"] == "success", result
    base = dict(event_id=request["event_id"], proposal_id=request["proposal"]["proposal_id"])
    tasks = result["data"]["execution_plan"]["tasks"]
    # Explicit owner choice in this MOCK scenario, not a guessed AI assignment.
    assigned = agent.handle({**base, "action": "assign_task", "task_id": tasks[1]["task_id"],
                            "booking_id": result["data"]["bookings"][0]["booking_id"]})
    assert assigned["status"] == "success"
    for task in tasks:
        for status in ("IN_PROGRESS", "COMPLETED"):
            result = agent.handle({**base, "action": "update_task_status",
                                  "task_id": task["task_id"], "status": status})
            assert result["status"] == "success"
    assert result["data"]["summary"]["execution_complete"]
    return result


if __name__ == "__main__":
    print("MOCK DEMO: proposal/approval/deposit and supplier replies simulated. No LLM/network/payment.")
    print(json.dumps(run_demo(), indent=2))
