"""Independent example inputs for the vendor recommendation demo (KAN-16).

Uses the scripted MockLLMClient by default, so NO real LLM/API call is
made. The banner and the recommendations block are explicitly marked
MOCK; the model's free-text reasons are shown as AI-generated and NOT
fully fact-verified (facts are backfilled from the catalog).

Run with:  py -3 -m examples.vendor_recommendation_example
"""
from __future__ import annotations

import json
from pathlib import Path

from src.agents import VendorProcurementManagerAgent
from src.llm import MockLLMClient
from src.services.vendor_procurement_service import VendorProcurementService

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = REPO_ROOT / "data" / "vendor_catalog.json"

# Independent example input. Catering, Melbourne, 2026-12-05, 120 guests.
EXAMPLE_REQUEST = {
    "event_id": "EV-2026-1205-EXAMPLE",
    "service_type": "catering",
    "event_date": "2026-12-05",
    "guest_count": 120,
    "location": "Melbourne",
    "customer_preferences": "Prefer outdoor-friendly service.",
    "min_rating": 4.0,
}

# Scripted mock response (what a real model call would return).
MOCK_RESPONSE = json.dumps(
    {
        "recommendations": [
            {
                "vendor_id": "V-CAT-002",
                "offering_id": "V-CAT-002-O1",
                "basis_codes": ["lowest_price"],
                "reason": "Cheapest catering option that fits the venue.",
            },
            {
                "vendor_id": "V-CAT-001",
                "offering_id": "V-CAT-001-O1",
                "basis_codes": ["highest_rating", "highest_capacity"],
                "reason": "Highest rated and largest capacity among the candidates.",
            },
        ]
    }
)


def main() -> None:
    service = VendorProcurementService.from_json_file(CATALOG_PATH)

    print("=" * 62)
    print("MOCK RUN — scripted MockLLMClient, no real LLM/API call made")
    print("=" * 62)

    print("=== Request (independent example input) ===")
    for key, value in EXAMPLE_REQUEST.items():
        print(f"  {key}: {value}")

    llm = MockLLMClient(MOCK_RESPONSE)
    agent = VendorProcurementManagerAgent(llm=llm, vendor_service=service)
    env = agent.handle(dict(EXAMPLE_REQUEST))

    print("=== Envelope ===")
    for key in ("event_id", "agent", "timestamp", "status", "message"):
        print(f"  {key}: {env[key]}")

    recs = env["data"].get("recommendations", [])
    print(f"=== {len(recs)} recommendation(s) [MOCK] ===")
    for rec in recs:
        price_aud = rec["total_price_cents"] / 100
        print(
            f"  rank {rec['rank']}: {rec['vendor_name']} "
            f"({rec['vendor_id']} / {rec['offering_id']})"
        )
        print(
            f"    {rec['service_type']} @ {rec['service_location']} | "
            f"capacity {rec['guest_capacity']} | rating {rec['rating']} | "
            f"price AUD {price_aud:,.2f} | {rec['event_date']}"
        )
        codes = ", ".join(rec["basis_codes"]) or "(none)"
        print(f"    basis (code-verified): {codes}")
        print(
            "    reason (AI-generated, not fully fact-verified): "
            f"{rec['recommendation_reason']}"
        )
    if not recs:
        print("  (no recommendations — see status/message above)")

    print(f"\nLLM client used: MockLLMClient ({len(llm.calls)} scripted call(s))")


if __name__ == "__main__":
    main()
