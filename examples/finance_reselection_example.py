"""Offline Finance -> Procurement reselection; no school API or payments."""
from copy import deepcopy
import json

from examples.event_procurement_example import make_event_demo
from src.agents.financial_manager import FinancialManagerAgent
from src.agents.vendor_procurement_manager import VendorProcurementManagerAgent
from src.llm import MockLLMClient
from src.services.mock_payment_service import MockPaymentService


def build_case(*, feasible=True, responder=None):
    source, supplier, request = make_event_demo()
    request["budget_limit_cents"] = 1100000 if feasible else 800000
    request["customer_preferences"] = "Photography quality is the priority; save on other services."
    request["services"][0]["customer_preferences"] = "Keep the best photographer when affordable."
    calls = []

    def choose(messages):
        facts = json.loads(messages[-1]["content"].split("\n", 1)[1])
        calls.append(facts)
        selections = []
        for service in facts["services"]:
            quality = feasible and (len(calls) == 1 or service["service"] == "photography")
            row = min(service["quotes"], key=(
                (lambda r: (-r[3], r[2])) if quality else (lambda r: (r[2], -r[3]))))
            selections.append(row[0])
        return json.dumps({"choices": selections, "reason": "MOCK: retain photography quality and save elsewhere."})

    procurement = VendorProcurementManagerAgent(
        MockLLMClient(responder or choose), source._vendor_service,
        quotation_service=supplier, compact_llm=True, joint_selection=True)
    first = procurement.procure_services(request)
    assert first["status"] == "success", first["message"]
    finance_llm = MockLLMClient()
    finance_llm.set_exception(AssertionError("Finance uses exact code, not an LLM"))
    finance = FinancialManagerAgent(finance_llm, MockPaymentService())
    handoff = {
        "event_id": request["event_id"],
        "event": {k: deepcopy(request[k]) for k in
                  ("event_id", "event_date", "location", "guest_count", "budget_limit_cents")},
        "proposal": {"event_id": request["event_id"], "proposal_id": request["proposal_id"],
                     "required_services": [s["service_type"] for s in request["services"]]},
        "quotations": first["data"]["quotations"],
        "selected_quotation_ids": first["data"]["selected_quotation_ids"],
    }
    review = finance.handle({**handoff, "action": "prepare_budget"})
    assert review["status"] == "blocked" and review["data"]["budget_valid"] is True
    revision_request = {
        **{k: first["data"][k] for k in ("event_id", "proposal_id", "batch_id")},
        "event": handoff["event"], "proposal": handoff["proposal"], "finance_result": review,
    }
    return procurement, supplier, request, first, handoff, review, finance, revision_request


def run_case(*, feasible=True):
    procurement, supplier, request, first, handoff, review, finance, revision_request = build_case(feasible=feasible)
    revised = procurement.reselect_after_finance(revision_request)
    assert procurement.reselect_after_finance(revision_request) == revised
    recheck = None
    if revised["status"] == "success":
        recheck = finance.handle({
            **handoff, "action": "prepare_budget", "quotations": revised["data"]["quotations"],
            "selected_quotation_ids": revised["data"]["selected_quotation_ids"],
        })
        assert recheck["status"] == "success", recheck["message"]
    return {
        "scenario": "reselection_possible" if feasible else "planner_review_needed",
        "initial_finance_status": review["status"],
        "initial_customer_total_cents": review["data"]["estimated_total_cents"],
        "customer_budget_cents": request["budget_limit_cents"],
        "reselection_status": revised["status"],
        "next_action": revised["data"]["next_action"],
        "revised_supplier_total_cents": revised["data"].get("budget_summary", {}).get("proposed_supplier_total_cents"),
        "finance_recheck_status": recheck["status"] if recheck else None,
        "revised_customer_total_cents": recheck["data"]["estimated_total_cents"] if recheck else None,
        "minimum_budget_shortfall_cents": revised["data"].get("minimum_budget_shortfall_cents"),
        "supplier_enquiry_count": len(supplier.calls),
        "total_procurement_llm_calls": len(procurement.llm.calls),
        "finance_llm_calls": len(finance.llm.calls),
        "repeated_call_reused_result": True,
        "mock": True,
    }


def main():
    print(json.dumps([run_case(feasible=True), run_case(feasible=False)], indent=2))


if __name__ == "__main__":
    main()
