import subprocess
import sys
import json


def test_stub_reconciliation_cli():
    result = subprocess.run([sys.executable, '-B', '-m', 'examples.financial_reconciliation_example'],
                            capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    assert data['operations_source'] == 'STUB'
    assert data['before']['status'] == 'blocked'
    assert data['after']['data']['financial_check_passed'] is True
