"""Quotation generation from actual Procurement snapshots, including SQLite reload."""
from examples.customer_quotation_example import generate_customer_quotation
from examples.budget_check_example import UnusedPayments
from src.agents.financial_manager import FinancialManagerAgent
from src.llm import MockLLMClient
from src.services.procurement_record_service import ProcurementRecordService


def test_persisted_procurement_to_customer_quotation(tmp_path):
    request, budget, original = generate_customer_quotation()
    path = tmp_path / "procurement.sqlite3"
    records = ProcurementRecordService(path)
    records.save_quotations(request["quotations"])
    request["quotations"] = ProcurementRecordService(path).get_quotations("EV001", "P1")
    worker = FinancialManagerAgent(MockLLMClient(), UnusedPayments())
    result = worker.handle({**request, "budget": budget, "action": "generate_customer_quotation"})
    assert result["status"] == "success"
    quote = result["data"]["customer_quotation"]
    assert quote["estimated_total_cents"] == original["data"]["customer_quotation"]["estimated_total_cents"]
    assert quote["budget_fingerprint"] == budget["budget_fingerprint"]
    request["quotations"][0]["quoted_total_cents"] += 1
    stale = worker.handle({**request, "budget": budget, "action": "generate_customer_quotation"})
    assert stale["status"] == "blocked" and not stale["data"]
