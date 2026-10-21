"""Offline executable UC4 V1 smoke test."""
import subprocess
import sys
from pathlib import Path


def test_budget_v1_cli():
    result = subprocess.run([sys.executable, "-B", "-m", "examples.budget_check_example"],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert '"status": "success"' in result.stdout
    assert '"status": "blocked"' in result.stdout
    assert '"budget_valid": true' in result.stdout
    assert '"estimated_total_cents": 2220000' in result.stdout
