"""Joint Procurement still hands only selected, unmodified quotes to Finance."""
from examples.budget_check_example import check_budget
from examples.event_procurement_example import make_event_demo
from examples.shared_catalog_procurement_example import mock_bundle_selection
from src.agents.vendor_procurement_manager import VendorProcurementManagerAgent
from src.llm import MockLLMClient
from src.services.procurement_record_service import ProcurementRecordService


def test_joint_selected_quotes_keep_persisted_identity_and_finance_can_still_block(tmp_path):
    source, supplier, request = make_event_demo()
    records = ProcurementRecordService(tmp_path / "joint.sqlite3")
    agent = VendorProcurementManagerAgent(
        MockLLMClient(mock_bundle_selection), source._vendor_service,
        quotation_service=supplier, record_service=records, compact_llm=True, joint_selection=True)
    request["budget_limit_cents"] = 800000
    result = agent.procure_services(request)
    assert result["status"] == "success" and result["data"]["selection_complete"]
    quotes = result["data"]["quotations"]
    stored = records.get_quotations(request["event_id"], request["proposal_id"])
    assert len(quotes) == 5 and len(stored) == 10 and all(q in stored for q in quotes)
    assert result["data"]["budget_summary"]["proposed_supplier_total_cents"] == 760000
    assert result["data"]["budget_summary"]["finance_review_required"] is True
    checked = check_budget(quotes, 800000)
    assert checked["status"] == "blocked"  # Financial includes contingency/other existing costs.
    assert checked["data"]["vendor_total_cents"] == 760000
    assert checked["data"]["estimated_total_cents"] == 912000
    assert check_budget(quotes, 1000000)["status"] == "success"
    assert len(agent.llm.calls) == 1 and len(supplier.calls) == 15
