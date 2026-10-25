"""Offline CLI acceptance check for the shortlist/reply/re-rank demo."""
import json
from pathlib import Path
import subprocess
import sys


def test_shortlisted_quotation_cli():
    run = subprocess.run([sys.executable, "-m", "examples.shortlisted_quotation_example"],
                         cwd=Path(__file__).resolve().parents[2],
                         capture_output=True, text=True, timeout=20)
    assert run.returncode == 0, run.stderr
    heading, body = run.stdout.split("\n", 1)
    assert "MOCK DEMO" in heading
    result = json.loads(body)
    assert result["initial_order"] == ["A", "B", "C"]
    assert [r["vendor_id"] for r in result["quotation_ranking"]] == ["B", "A"]
    selected, = result["selected_quotations"]
    assert selected["vendor_id"] == "B" and selected["quoted_total_cents"] == 95000
    assert all(r["vendor_id"] != "D" for r in result["supplier_replies"])


def test_five_service_procurement_cli():
    run = subprocess.run([sys.executable, "-m", "examples.event_procurement_example"],
                         cwd=Path(__file__).resolve().parents[2],
                         capture_output=True, text=True, timeout=20)
    assert run.returncode == 0, run.stderr
    heading, body = run.stdout.split("\n", 1)
    assert "MOCK DEMO" in heading
    data = json.loads(body)
    assert data["status"] == "success" and data["selection_complete"]
    assert len(data["required_services"]) == len(data["quotations"]) == 5
    assert data["enquiry_count"] == 15
    assert len(data["selected_quotation_ids"]) == 5
    assert all(q["vendor_id"] == "B" for q in data["quotations"])
