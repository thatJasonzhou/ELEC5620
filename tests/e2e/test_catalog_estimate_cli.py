"""Fresh-process Planner precheck, including insufficient and malformed budgets."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("args,status", [
    ([], "within_budget_estimate"),
    (["--budget-cents", "50000"], "over_budget_estimate"),
])
def test_cli_outputs_estimates_without_any_live_configuration(args, status):
    run = subprocess.run(
        [sys.executable, "-m", "examples.catalog_estimate_example", *args],
        cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    assert result["status"] == status
    assert result["minimum_costs"]["customer_price_cents"] == 1026000
    assert result["estimate_only"] is result["finance_review_required"] is True


def test_cli_rejects_invalid_money():
    run = subprocess.run(
        [sys.executable, "-m", "examples.catalog_estimate_example", "--budget-cents", "-1"],
        cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert run.returncode != 0
    assert "budget_limit_cents" in run.stderr
