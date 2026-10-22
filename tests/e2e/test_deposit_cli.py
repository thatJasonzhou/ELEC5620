import os
import subprocess
import sys


def test_mock_deposit_cli():
    result = subprocess.run([sys.executable, "-B", "-m", "examples.deposit_payment_example"],
        env={**os.environ, "ELEC5620_DEPOSIT_RATE": "0.30"}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '"status": "pending"' in result.stdout
    assert '"status": "paid"' in result.stdout
    assert '"status": "unconfigured"' in result.stdout
