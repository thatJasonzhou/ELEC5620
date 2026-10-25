"""Five-service Procurement workflow with simulated supplier quotation replies.

Run: python -m examples.event_procurement_example
All suppliers, prices and model responses here are explicit MOCK fixtures.
Production callers inject their catalogue, MockVendorQuotationService and the
central CampusQwenClient; the Procurement API is identical.
"""
from __future__ import annotations

from copy import deepcopy
import json

from src.agents.vendor_procurement_manager import VendorProcurementManagerAgent
from src.llm import MockLLMClient
from src.services.vendor_procurement_service import VendorProcurementService
from src.services.vendor_quotation_service import MockVendorQuotationService
from src.shared.schemas import Vendor

SERVICE_TYPES = ("photography", "catering", "venue", "sound", "decoration")
FACTORS = dict(zip(SERVICE_TYPES, (1, 2, 3, 1, 1)))


class RecordingMockQuotations(MockVendorQuotationService):
    """Only adds an enquiry log for the offline demo and assertions."""

    def __init__(self, scenarios):
        super().__init__(scenarios)
        self.calls = []

    def request_quotation(self, **request):
        self.calls.append(deepcopy(request))
        return super().request_quotation(**request)


def mock_compare(messages):
    """Offline model fixture, ranking supplied facts rather than inventing IDs."""
    text = messages[-1]["content"]
    if text.startswith("{"):
        payload = json.loads(text)
        if "candidate_rows" in payload:
            columns = payload["columns"]
            rows = [dict(zip(columns, row)) for row in payload["candidate_rows"]]
            if payload["stage"] == "shortlist":
                rows = sorted(rows, key=lambda row: -row["rating"])
            else:
                rows = sorted(rows, key=lambda row: (row["price_cents"], -row["rating"]))
            return json.dumps({"ranked": [[row["i"], "MOCK price and rating comparison"]
                                         for row in rows[:payload["count"]]]})
        candidates = payload["candidates"]
        candidates = sorted(candidates, key=lambda c: (c["total_price_cents"], -c["rating"]))
    else:
        marker = "Candidates (facts, already verified by code):\n"
        candidates = json.loads(text.split(marker, 1)[1].split("\n\nRespond with STRICT JSON", 1)[0])
        candidates = sorted(candidates, key=lambda c: -c["rating"])[:3]
    return json.dumps({"recommendations": [
        {"vendor_id": c["vendor_id"], "offering_id": c["offering_id"],
         "basis_codes": [], "reason": "MOCK comparison of supplied price and rating."}
        for c in candidates]})


def make_event_demo(*, services=SERVICE_TYPES, llm=None, record_service=None):
    """Separate fictional fixtures; the existing shared catalogue is unchanged."""
    vendors, scenarios = [], []
    for name, estimate, rating in (("A", 90000, 4.9), ("B", 95000, 4.7),
                                   ("C", 85000, 4.5), ("D", 110000, 4.0)):
        offerings = []
        for service in services:
            factor = FACTORS.get(service, 1)
            offering_id = name + "-" + service
            offerings.append({
                "offering_id": offering_id, "service_type": service,
                "service_location": "Sydney", "guest_capacity": 100, "rating": rating,
                "total_price_cents": estimate * factor,
                "availability": [{"date": "2026-12-16", "available": True}],
            })
            scenario = {
                "scenario_id": "MOCK-" + offering_id, "vendor_id": name,
                "offering_id": offering_id, "event_date": "2026-12-16", "guest_count": 50,
                "reply": "rejected" if name == "C" else "accepted",
                "reason": "MOCK: unavailable." if name == "C" else "MOCK: confirmed supplier quote.",
            }
            if name != "C":
                # D is deliberately very cheap but never enquired: it was not shortlisted.
                scenario["quoted_total_cents"] = {"A": 130000, "B": 95000, "D": 100}[name] * factor
            scenarios.append(scenario)
        vendors.append(Vendor.from_dict({
            "vendor_id": name, "name": "MOCK multi-service supplier " + name,
            "service_offerings": offerings,
        }))
    supplier = RecordingMockQuotations(scenarios)
    agent = VendorProcurementManagerAgent(
        llm or MockLLMClient(mock_compare), VendorProcurementService(vendors),
        quotation_service=supplier, record_service=record_service)
    request = {
        "event_id": "EV-FIVE", "proposal_id": "P-FIVE",
        "event_date": "2026-12-16", "guest_count": 50, "location": "Sydney",
        "customer_preferences": "Compare price and rating; prefer value.",
        "services": [{"service_type": s, "service_budget_cents": 100000 * FACTORS.get(s, 1)}
                     for s in services],
    }
    return agent, supplier, request


def run_event_demo(*, record_service=None):
    agent, supplier, request = make_event_demo(record_service=record_service)
    result = agent.procure_services(request)
    assert result["status"] == "success", result["message"]
    assert result["data"]["selection_complete"]
    assert len(result["data"]["quotations"]) == 5
    assert len(supplier.calls) == 15
    assert all(q["vendor_id"] == "B" for q in result["data"]["quotations"])
    return result, supplier


if __name__ == "__main__":
    result, supplier = run_event_demo()
    print("MOCK DEMO: five services -> 15 shortlisted enquiries -> five selected quotations")
    print(json.dumps({
        "status": result["status"], "required_services": result["data"]["required_services"],
        "enquiry_count": len(supplier.calls),
        "selection_complete": result["data"]["selection_complete"],
        "selected_quotation_ids": result["data"]["selected_quotation_ids"],
        "quotations": result["data"]["quotations"],
        "service_rankings": [
            {"service_type": r["service_type"], "ranking": r["data"]["quotation_ranking"]}
            for r in result["data"]["service_results"]],
    }, indent=2))
