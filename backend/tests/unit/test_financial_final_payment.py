import pytest

from src.services.financial_workflow_service import FinancialWorkflowService


def records() -> tuple[dict, dict, dict]:
    quotation = {
        "event_id": "EV-FINAL",
        "proposal_id": "PP-FINAL",
        "customer_quotation_id": "CQ-FINAL",
        "quotation_fingerprint": "verified-fingerprint",
        "estimated_total_cents": 1_000_000,
    }
    deposit = {
        "event_id": "EV-FINAL",
        "proposal_id": "PP-FINAL",
        "customer_quotation_id": "CQ-FINAL",
        "amount_cents": 300_000,
        "status": "paid",
        "mock": True,
    }
    operations = {
        "event_id": "EV-FINAL",
        "proposal_id": "PP-FINAL",
        "execution_plan_id": "EP-FINAL",
        "status": "COMPLETED",
        "finalized": True,
    }
    return quotation, deposit, operations


def test_final_payment_is_remaining_balance_after_operations() -> None:
    quotation, deposit, operations = records()
    service = FinancialWorkflowService(deposit_percent=30)

    payment = service.prepare_final_payment(quotation, deposit, operations)

    assert payment["total_amount_cents"] == 1_000_000
    assert payment["deposit_paid_cents"] == 300_000
    assert payment["amount_cents"] == 700_000
    assert payment["status"] == "pending"
    assert payment["mock"] is True

    paid = service.simulate_final_payment(payment)
    assert paid["status"] == "paid"
    assert paid["transaction_reference"].startswith("MOCK-FP-")


def test_final_payment_cannot_be_prepared_before_operations_finalization() -> None:
    quotation, deposit, operations = records()
    operations["finalized"] = False
    operations["status"] = "READY_TO_FINALIZE"

    with pytest.raises(ValueError, match="Operations must be finalized"):
        FinancialWorkflowService().prepare_final_payment(
            quotation, deposit, operations
        )
