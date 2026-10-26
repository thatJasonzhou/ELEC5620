"""Use the real Finance module before and after bounded quote reselection."""
from examples.finance_reselection_example import build_case, run_case
from src.services.customer_quotation_service import CustomerQuotationService


def test_revised_quotes_require_new_finance_review_before_customer_quotation():
    agent, supplier, _, _, handoff, original_review, finance, payload = build_case()
    revised = agent.reselect_after_finance(payload)
    new_handoff = {**handoff,
                   "quotations": revised["data"]["quotations"],
                   "selected_quotation_ids": revised["data"]["selected_quotation_ids"]}
    stale = CustomerQuotationService.quotation_content({
        **new_handoff, "budget": original_review["data"]})
    assert stale["status"] == "blocked"
    checked = finance.handle({**new_handoff, "action": "prepare_budget"})
    assert checked["status"] == "success"
    assert checked["data"]["estimated_total_cents"] == 954000
    customer = finance.handle({
        **new_handoff, "action": "generate_customer_quotation", "budget": checked["data"]})
    assert customer["status"] == "success"
    assert checked["data"]["quotation_fingerprint"] != original_review["data"]["quotation_fingerprint"]
    assert len(supplier.calls) == 15 and len(finance.llm.calls) == 0


def test_both_offline_paths_are_explicit_and_bounded():
    success = run_case(feasible=True)
    blocked = run_case(feasible=False)
    assert success["finance_recheck_status"] == "success"
    assert success["total_procurement_llm_calls"] == 2
    assert blocked["next_action"] == "planner_review"
    assert blocked["finance_recheck_status"] is None
    assert blocked["total_procurement_llm_calls"] == 1
    assert success["supplier_enquiry_count"] == blocked["supplier_enquiry_count"] == 15
