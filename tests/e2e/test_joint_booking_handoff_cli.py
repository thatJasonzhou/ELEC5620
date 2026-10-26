"""Offline complete-handoff command is bounded and needs no school credentials."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def test_full_handoff_cli_needs_no_credentials_and_runs_all_three_cases():
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("ELEC5620_LLM_") and key != "ELEC5620_DEPOSIT_RATE"}
    run = subprocess.run(
        [sys.executable, "-m", "examples.joint_booking_handoff_example"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
    assert run.returncode == 0, run.stderr
    assert "OFFLINE MOCK" in run.stdout and "30% deposit" in run.stdout
    assert run.stdout.count(": success | selected=5") == 3
    assert run.stdout.count("| bookings=5") == 3
    assert "no duplicate payment or booking calls" in run.stdout
    assert len(run.stdout.splitlines()) == 5
