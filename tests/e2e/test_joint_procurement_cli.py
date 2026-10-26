"""Fresh-source joint demo and explicit strategy selection."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def test_joint_demo_loads_concrete_request_and_keeps_output_bounded():
    run = subprocess.run(
        [sys.executable, "-m", "examples.shared_catalog_procurement_example", "--joint-selection",
         "--request-file", "examples/requests/procurement_priority_request.json"],
        cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert run.returncode == 0, run.stderr
    assert "Status: success" in run.stdout and "LLM calls: 1" in run.stdout
    assert "code shortlist + one LLM bundle selection" in run.stdout
    assert "enquiries: 15" in run.stdout and "selected: 5" in run.stdout
    assert "ceiling: AUD11,000.00" in run.stdout and "Finance review: pending" in run.stdout
    assert len(run.stdout.splitlines()) <= 12 and len(run.stderr.splitlines()) == 3


def test_joint_and_policy_modes_cannot_be_combined():
    run = subprocess.run(
        [sys.executable, "-m", "examples.shared_catalog_procurement_example",
         "--joint-selection", "--policy-ranking"],
        cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert run.returncode != 0 and "Choose only one" in run.stderr
