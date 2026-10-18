"""Independent example inputs for the vendor recommendation demo (KAN-16).

Uses the scripted MockLLMClient by default, so NO real LLM/API call is
made. The banner and the recommendations block are explicitly marked
MOCK; the model's free-text reasons are shown as AI-generated and NOT
fully fact-verified (facts are backfilled from the catalog).

Pass ``--live`` to make ONE real call to the Campus Qwen proxy via
``CampusQwenClient.from_env()``. Credentials and endpoint come ONLY from
environment variables (never from this file):

    ELEC5620_LLM_API_KEY   API key for the proxy (required)
    ELEC5620_LLM_BASE_URL  full endpoint, e.g.
                           http://<host>:<port>/v1/chat/completions
    ELEC5620_LLM_MODEL     model id, e.g. campus-qwen

Run (default, mock):  py -3 -m examples.vendor_recommendation_example
Run (real call):       py -3 -m examples.vendor_recommendation_example --live
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.agents import VendorProcurementManagerAgent
from src.llm import CampusQwenClient, LLMError, LLMClient, MockLLMClient
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


def _build_llm(live: bool) -> LLMClient:
    """Return the LLM client for this run.

    Mock (default) — scripted MockLLMClient, no network.
    Live — CampusQwenClient built ONLY from ELEC5620_LLM_* env vars.
    Missing/invalid configuration raises LLMError (names the missing
    variables, never their values); the caller decides how to present it.
    """
    if not live:
        return MockLLMClient(MOCK_RESPONSE)
    return CampusQwenClient.from_env()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Vendor recommendation demo (KAN-16). "
        "Mock by default; --live makes one real Campus Qwen call "
        "configured via ELEC5620_LLM_* environment variables."
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Make ONE real LLM call (CampusQwenClient.from_env) "
        "instead of the scripted MockLLMClient.",
    )
    args = parser.parse_args()

    if args.live:
        try:
            llm: LLMClient = _build_llm(True)
        except LLMError as exc:
            print("LIVE MODE FAILED — could not build the LLM client:")
            print(f"  {exc}")
            print(
                "Required environment variables: ELEC5620_LLM_API_KEY, "
                "ELEC5620_LLM_BASE_URL (full endpoint), ELEC5620_LLM_MODEL. "
                "Re-run without --live for the offline mock demo."
            )
            raise SystemExit(1)
        mode = "LIVE"
        print("=" * 62)
        print("LIVE RUN — real Campus Qwen call via CampusQwenClient")
        print("  (endpoint/model/key from ELEC5620_LLM_* env vars only)")
        print("=" * 62)
    else:
        llm = _build_llm(False)
        mode = "MOCK"
        print("=" * 62)
        print("MOCK RUN — scripted MockLLMClient, no real LLM/API call made")
        print("=" * 62)

    service = VendorProcurementService.from_json_file(CATALOG_PATH)

    print("=== Request (independent example input) ===")
    for key, value in EXAMPLE_REQUEST.items():
        print(f"  {key}: {value}")

    agent = VendorProcurementManagerAgent(llm=llm, vendor_service=service)
    env = agent.handle(dict(EXAMPLE_REQUEST))

    print("=== Envelope ===")
    for key in ("event_id", "agent", "timestamp", "status", "message"):
        print(f"  {key}: {env[key]}")

    if env["status"] != "success":
        print("=== No recommendations (see status/message above) ===")
        return

    recs = env["data"].get("recommendations", [])
    print(f"=== {len(recs)} recommendation(s) [{mode}] ===")
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

    if isinstance(llm, MockLLMClient):
        print(f"\nLLM client used: MockLLMClient ({len(llm.calls)} scripted call(s))")
    else:
        print(
            "\nLLM client used: CampusQwenClient (real call) — "
            "endpoint/model from ELEC5620_LLM_* env vars; key never printed."
        )


if __name__ == "__main__":
    main()
