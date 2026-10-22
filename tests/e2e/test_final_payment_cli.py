import json
import os
import subprocess
import sys


def test_offline_final_payment_cli():
    result = subprocess.run([sys.executable, '-B', '-m', 'examples.final_payment_example'],
                            env={**os.environ, 'ELEC5620_DEPOSIT_RATE': '0.30'},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout.split('\n', 1)[1])
    assert data['status'] == 'success' and data['mock'] is True
    assert data['before_final']['balance_cents'] == data['final_paid_cents']
    assert data['restored_balance']['balance_cents'] == 0
    assert data['payment_calls'] == 2 and data['restart_payment_calls'] == 0
