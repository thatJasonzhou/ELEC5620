"""Run Procurement mock quotations through Financial Budget Check V1."""
from pathlib import Path

from src.agents.financial_manager import FinancialManagerAgent
from src.agents.vendor_procurement_manager import VendorProcurementManagerAgent
from src.llm import MockLLMClient
from src.services.payment_service import PaymentService
from src.services.vendor_procurement_service import VendorProcurementService
from src.services.vendor_quotation_service import MockVendorQuotationService


class UnusedPayments(PaymentService):
    def process_payment(self, payment):
        raise AssertionError("budget example must not process payments")

    def verify_payment(self, transaction_reference):
        raise AssertionError("budget example must not verify payments")

    def refund_payment(self, transaction_reference, amount_cents):
        raise AssertionError("budget example must not refund payments")


def run_budget_check():
    root = Path(__file__).resolve().parents[1]
    llm = MockLLMClient()
    llm.set_exception(AssertionError("budget example must not call LLM"))
    procurement = VendorProcurementManagerAgent(llm,
        VendorProcurementService.from_json_file(root / "data/vendor_catalog.json"),
        MockVendorQuotationService.from_json_file(root / "data/mock_vendor_quotations.json"))
    quotes = procurement.request_quotations(dict(event_id="EV001", proposal_id="P1",
        service_type="catering", event_date="2026-12-05", guest_count=120, location="Melbourne"))
    assert quotes["status"] == "success", quotes["message"]
    quotations = quotes["data"]["quotations"]
    within = check_budget(quotations, 3000000)
    assert within["status"] == "success"
    over = check_budget(quotations, within["data"]["estimated_total_cents"] - 1)
    assert over["status"] == "blocked" and over["data"]["over_budget_cents"] == 1
    assert not llm.calls
    return within, over


def check_budget(quotations, budget_limit_cents):
    """Construct the Financial request for the selected quotation snapshots."""
    first = quotations[0]
    llm = MockLLMClient()
    llm.set_exception(AssertionError("budget calculation must not call LLM"))
    worker = FinancialManagerAgent(llm, UnusedPayments())
    return worker.handle(dict(event_id=first["event_id"], action="prepare_budget",
        event=dict(event_id=first["event_id"], event_date=first["event_date"],
                   guest_count=first["guest_count"], budget_limit_cents=budget_limit_cents),
        proposal=dict(event_id=first["event_id"], proposal_id=first["proposal_id"],
                      required_services=list(dict.fromkeys(q["service_type"] for q in quotations))),
        quotations=quotations, selected_quotation_ids=[q["quotation_id"] for q in quotations]))


if __name__ == "__main__":
    import json
    print("GST-inclusive budget checks; supplier replies are MOCK.")
    for result in run_budget_check():
        print(json.dumps(result, indent=2))
