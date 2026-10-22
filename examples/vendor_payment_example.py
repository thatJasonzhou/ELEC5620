"""Offline full settlement demonstration using temporary SQLite and mock evidence."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from src.agents.financial_manager import FinancialManagerAgent
from src.llm import MockLLMClient
from src.services.mock_payment_service import MockPaymentService
from src.services.procurement_record_service import ProcurementRecordService
from src.services.vendor_booking_service import quotation_fingerprint
from src.services.vendor_payment_record_service import VendorPaymentRecordService
from src.services.vendor_settlement_service import VendorSettlementService

ROOT = Path(__file__).resolve().parents[1]


def demo_inputs(records):
    """Seed validated MOCK Procurement snapshots, not a new booking workflow."""
    quote = dict(event_id="EV001", proposal_id="P1", quotation_id="Q1", vendor_id="V1",
        offering_id="O1", service_type="catering", event_date="2026-10-21", guest_count=10,
        quoted_total_cents=10000, available=True, mock=True, scenario_id="MOCK-Q1",
        recommendation_reason="MOCK agreed quotation")
    records.save_quotations([quote])
    booking = {k: quote[k] for k in ("event_id", "proposal_id", "quotation_id", "vendor_id",
        "offering_id", "service_type", "event_date", "guest_count", "quoted_total_cents")}
    booking.update(booking_id="VB1", status="Confirmed", supplier_confirmation_id="MOCK-CONF1",
                   source_quotation_fingerprint=quotation_fingerprint([quote]), mock=True)
    records.save_booking(booking)
    return dict(event_id="EV001", proposal_id="P1",
        invoice=json.loads((ROOT / "data/mock_vendor_invoices.json").read_text())[0],
        completion=json.loads((ROOT / "data/mock_service_completions.json").read_text())[0])


def run_demo(path):
    procurement = ProcurementRecordService(path)
    request = demo_inputs(procurement)
    provider = MockPaymentService()
    service = VendorSettlementService(provider, procurement, VendorPaymentRecordService(path))
    worker = FinancialManagerAgent(MockLLMClient(), provider, settlement_service=service)
    pending = worker.handle({**request, "action": "prepare_vendor_payment_request"})
    payment = pending["data"]["vendor_payment"]
    execution = {**request, "action": "simulate_vendor_payment", "simulate": True,
                 "payment_id": payment["payment_id"], "amount_cents": payment["amount_cents"]}
    paid = worker.handle(execution)
    restarted = VendorSettlementService(MockPaymentService(vendor_outcome="failure"),
        ProcurementRecordService(path), VendorPaymentRecordService(path))
    again = restarted.simulate_payment(execution)
    assert paid["data"] == again["data"]
    return pending, paid, again


def main():
    with TemporaryDirectory(prefix="vendor-payment-demo-") as directory:
        for result in run_demo(Path(directory) / "demo.sqlite3"):
            print(json.dumps(result))


if __name__ == "__main__":
    main()
