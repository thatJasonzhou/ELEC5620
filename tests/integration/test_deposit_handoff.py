from examples.deposit_payment_example import run_demo


def test_financial_to_existing_kan20_validation(monkeypatch):
    monkeypatch.setenv("ELEC5620_DEPOSIT_RATE", "0.30")
    pending, paid, verification = run_demo()
    assert pending["data"]["deposit"]["status"] == "pending"
    deposit = paid["data"]["deposit"]
    assert deposit["status"] == "paid" and deposit["mock"] is True
    assert deposit["amount_cents"] == paid["data"]["budget"]["deposit_due_cents"]
    assert verification["data"]["customer_payment"] == deposit
