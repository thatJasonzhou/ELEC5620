import json
import os
import subprocess
import sys


def test_offline_financial_persistence_cli():
    result = subprocess.run([sys.executable, '-B', '-m', 'examples.financial_persistence_example'],
        env={**os.environ, 'ELEC5620_DEPOSIT_RATE': '0.30'}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.split('\n', 1)[1])
    assert payload['status'] == 'success'
    assert payload['restart_payment_calls'] == 0
    assert payload['history']['deposits'][0]['execution_state'] == 'result_recorded'
