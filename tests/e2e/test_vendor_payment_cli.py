import subprocess
import sys


def test_vendor_payment_cli():
    result = subprocess.run([sys.executable, "-B", "-m", "examples.vendor_payment_example"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '"status": "pending"' in result.stdout
    assert '"status": "paid"' in result.stdout
    assert 'MOCK-' in result.stdout
