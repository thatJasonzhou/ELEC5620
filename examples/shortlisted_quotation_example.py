"""Offline KAN-36 demo: catalogue shortlist -> simulated replies -> new ranking.

Run: python -m examples.shortlisted_quotation_example
The two LLM responses and supplier replies are scripted MOCK data. No real
vendor, payment provider or LLM is contacted. Future UI code calls the same
prepare_enquiries / submit_quotation_reply / compare_quotations methods.
"""
from __future__ import annotations

import json

from src.agents.vendor_procurement_manager import VendorProcurementManagerAgent
from src.llm import MockLLMClient
from src.services.vendor_procurement_service import VendorProcurementService
from src.shared.schemas import Vendor

DEMO_REQUEST = {
    "event_id": "EV-SHORTLIST", "proposal_id": "P-SHORTLIST",
    "service_type": "photography", "location": "Sydney",
    "event_date": "2026-12-16", "guest_count": 50,
    "customer_preferences": "Compare price and rating; prefer value.",
    "service_budget_cents": 100000, "budget_is_hard_limit": False,
}


def model_response(order, basis=None):
    """Explicit scripted model output, not a live AI decision."""
    return json.dumps({"recommendations": [
        {"vendor_id": name, "offering_id": name + "-PHOTO",
         "basis_codes": (basis or {}).get(name, []),
         "reason": "MOCK comparison based on the supplied price and rating."}
        for name in order]})


def make_demo_agent(*, llm=None, record_service=None):
    # Separate fictional fixture; the team's shared vendor catalog is untouched.
    vendors = [Vendor.from_dict({
        "vendor_id": name, "name": "MOCK Photographer " + name,
        "service_offerings": [{
            "offering_id": name + "-PHOTO", "service_type": "photography",
            "service_location": "Sydney", "guest_capacity": 100, "rating": rating,
            "total_price_cents": amount,
            "availability": [{"date": DEMO_REQUEST["event_date"], "available": True}],
        }],
    }) for name, amount, rating in
        [("A", 90000, 4.9), ("B", 95000, 4.7), ("C", 85000, 4.5), ("D", 110000, 4.0)]]
    if llm is None:
        llm = MockLLMClient([
            model_response(["A", "B", "C"]),
            model_response(["B", "A"], {"B": ["lowest_price"], "A": ["highest_rating"]}),
        ])
    return VendorProcurementManagerAgent(
        llm, VendorProcurementService(vendors), record_service=record_service)


def submit_demo_replies(agent, prepared):
    """These dictionaries are the future supplier form's input boundary."""
    context = prepared["data"]["context"]
    for enquiry in prepared["data"]["enquiries"]:
        vendor = enquiry["reply"]["vendor_id"]
        amount = {"A": 130000, "B": 95000, "C": None}[vendor]
        result = agent.submit_quotation_reply({
            "event_id": context["event_id"], "proposal_id": context["proposal_id"],
            "round_id": prepared["data"]["round_id"], "enquiry_id": enquiry["enquiry_id"],
            "mock": True, "status": "rejected" if vendor == "C" else "accepted",
            "quoted_total_cents": amount,
            "reason": "MOCK: date no longer available." if vendor == "C" else "MOCK: supplier-submitted AUD quote.",
        })
        assert result["status"] == "success", result["message"]


def run_shortlist_demo(*, record_service=None):
    agent = make_demo_agent(record_service=record_service)
    prepared = agent.prepare_enquiries(dict(DEMO_REQUEST))
    assert prepared["status"] == "success", prepared["message"]
    lookup = {n: prepared["data"]["context"][n] for n in ("event_id", "proposal_id")}
    lookup["round_id"] = prepared["data"]["round_id"]
    pending = agent.compare_quotations(lookup)
    assert pending["status"] == "blocked" and not pending["data"]["selected_quotation_ids"]
    submit_demo_replies(agent, prepared)
    compared = agent.compare_quotations(lookup)
    assert compared["status"] == "success", compared["message"]
    assert compared["data"]["selected_quotations"][0]["vendor_id"] == "B"
    return prepared, compared


if __name__ == "__main__":
    prepared, compared = run_shortlist_demo()
    print("MOCK DEMO: catalogue shortlist -> supplier replies -> quotation ranking")
    print(json.dumps({
        "initial_order": [r["vendor_id"] for r in prepared["data"]["recommendations"]],
        "supplier_replies": compared["data"]["supplier_replies"],
        "quotation_ranking": compared["data"]["quotation_ranking"],
        "selected_quotation_ids": compared["data"]["selected_quotation_ids"],
        "selected_quotations": compared["data"]["selected_quotations"],
    }, indent=2))
