from examples.vendor_payment_example import run_demo


def test_persisted_procurement_to_finance(tmp_path):
    pending, paid, reloaded = run_demo(tmp_path / "workflow.sqlite3")
    assert pending["data"]["vendor_payment"]["status"] == "pending"
    payment = paid["data"]["vendor_payment"]
    assert payment["status"] == "paid" and payment["approved_at"] is None
    assert payment["transaction_reference"].startswith("MOCK-")
    assert reloaded["data"]["vendor_payment"] == payment
