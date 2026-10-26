"""Estimates reuse Finance's exact policy and leave procurement entry points untouched."""
import json
from pathlib import Path

import pytest

from examples.shared_catalog_procurement_example import build_agent
from src.services.vendor_procurement_service import VendorProcurementService
from src.shared.schemas import Budget

ROOT = Path(__file__).resolve().parents[2]


def test_estimate_costs_match_budget_calculation_for_the_same_catalogue_amounts():
    payload = json.loads((ROOT / "examples/requests/procurement_priority_request.json").read_text())
    service = VendorProcurementService.from_json_file(ROOT / "data/vendor_catalog.json")
    estimate = service.estimate_event(payload)
    budget = Budget("B-ESTIMATE-TEST", payload["event_id"], 0, 0, 0, 0, "Draft")
    # Test-only quote snapshots compare the same amounts; the service creates none.
    for item in estimate["service_estimates"]:
        candidate = service.filter_vendors(
            service_type=item["service_type"], date=payload["event_date"],
            guest_count=payload["guest_count"], location=payload["location"])[0]
        budget.add_vendor_quotation({
            "quotation_id": "Q-" + item["service_type"],
            "event_id": payload["event_id"], "proposal_id": payload["proposal_id"],
            "vendor_id": candidate["vendor_id"], "offering_id": candidate["offering_id"],
            "service_type": item["service_type"], "event_date": payload["event_date"],
            "guest_count": payload["guest_count"],
            "quoted_total_cents": candidate["total_price_cents"],
            "available": True, "mock": True,
        })
    assert budget.calculate_total() == estimate["minimum_costs"]["customer_price_cents"]
    assert budget.service_fee_cents == estimate["minimum_costs"]["service_fee_cents"]
    assert budget.contingency_amount_cents == estimate["minimum_costs"]["contingency_amount_cents"]


@pytest.mark.parametrize("budget_cents,proceed", [(50000, False), (1200000, True)])
def test_workflow_can_stop_before_enquiries_or_pass_the_derived_cap(budget_cents, proceed):
    payload = json.loads((ROOT / "examples/requests/procurement_priority_request.json").read_text())
    payload["budget_limit_cents"] = budget_cents
    agent = build_agent(joint_selection=True)
    service = VendorProcurementService.from_json_file(ROOT / "data/vendor_catalog.json")
    estimate = service.estimate_event(payload)
    assert not agent.llm.calls
    if estimate["status"] == "within_budget_estimate":
        payload["supplier_budget_limit_cents"] = estimate["supplier_budget_limit_cents"]
        result = agent.procure_services(payload)
        assert proceed and result["status"] == "success"
        assert len(result["data"]["selected_quotation_ids"]) == 5
        assert len(agent.llm.calls) == 1
    else:
        assert not proceed and estimate["status"] == "over_budget_estimate"
        assert not agent.llm.calls
