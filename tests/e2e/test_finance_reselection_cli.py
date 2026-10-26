import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def test_fresh_process_offline_demo_covers_reselection_and_infeasibility():
    run = subprocess.run(
        [sys.executable, "-m", "examples.finance_reselection_example"],
        cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert run.returncode == 0, run.stderr
    success, blocked = json.loads(run.stdout)
    assert success["initial_finance_status"] == blocked["initial_finance_status"] == "blocked"
    assert success["finance_recheck_status"] == "success"
    assert blocked["next_action"] == "planner_review"
    assert success["repeated_call_reused_result"] is blocked["repeated_call_reused_result"] is True
    assert success["finance_llm_calls"] == blocked["finance_llm_calls"] == 0
