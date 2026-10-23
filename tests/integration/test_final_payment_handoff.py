from examples.final_payment_example import run_demo


def test_agent_deposit_final_and_restored_balance(monkeypatch):
    monkeypatch.setenv('ELEC5620_DEPOSIT_RATE', '0.30')
    result = run_demo()
    assert result['deposit_paid_cents'] + result['final_paid_cents'] == result['quotation_total_cents']
    assert result['restored_balance']['balance_cents'] == 0
    assert result['payment_calls'] == 2
    assert result['restart_payment_calls'] == 0
    assert result['final_execution_state'] == 'completed'
