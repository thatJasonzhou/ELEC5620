import subprocess
import sys
from pathlib import Path


def test_operations_cli_offline():
    process = subprocess.run([sys.executable, "-m", "examples.operations_example"],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=20)
    assert process.returncode == 0, process.stderr
    assert "MOCK DEMO" in process.stdout
    assert '"execution_complete": true' in process.stdout
