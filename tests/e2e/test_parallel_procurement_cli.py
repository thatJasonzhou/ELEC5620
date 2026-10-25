"""Fresh checkout CLI runs in Mock mode offline; Live is explicitly selected."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("workers", [1, 3, 5])
def test_cli_progress_stays_on_stderr_and_json_contains_timing(workers):
    run = subprocess.run(
        [sys.executable, "-m", "examples.shared_catalog_procurement_example",
         "--concurrency", str(workers), "--verbose"],
        cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    assert result["status"] == "success" and result["selection_complete"]
    assert result["llm_mode"] == "mock" and result["supplier_source"] == "mock"
    assert result["llm_concurrency"] == workers and result["elapsed_seconds"] >= 0
    assert len(result["selected_quotation_ids"]) == 5
    assert run.stderr.count(": submitted") == run.stderr.count(": received") == 10

def test_default_output_is_bounded_and_has_no_nested_debug_snapshots():
    run = subprocess.run(
        [sys.executable, "-m", "examples.shared_catalog_procurement_example"],
        cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert run.returncode == 0, run.stderr
    assert "LLM: MOCK" in run.stdout and "Status: success" in run.stdout
    assert "selection_complete: true" in run.stdout and "selected: 5" in run.stdout
    assert "Elapsed:" in run.stdout and "enquiries: 15" in run.stdout
    for service in ("photography", "catering", "venue", "sound", "decoration"):
        assert service in run.stdout
    assert len(run.stdout.splitlines()) <= 10
    assert len(run.stderr.splitlines()) <= 12
    assert "service_results" not in run.stdout and "enquiry_id" not in run.stdout
    assert "quotation_id" not in run.stdout
