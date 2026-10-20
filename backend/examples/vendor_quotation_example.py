"""Independent offline example for the mock vendor quotation step (KAN-19).

Demonstrates all three preset mock vendor replies — accepted (with an
integer-AUD-cents quote), rejected (with a reason) and pending
(unconfirmed) — plus the no-default-acceptance rule for a request with
no configured scenario.

Runs fully offline: no LLM, no database, no network. Every reply is
explicitly marked ``mock: true`` and echoes the original request.

Run with:  py -3 -m examples.vendor_quotation_example
"""
from __future__ import annotations

from pathlib import Path

from src.services.vendor_quotation_service import MockVendorQuotationService

REPO_ROOT = Path(__file__).resolve().parents[1]
SCENARIO_PATH = REPO_ROOT / "data" / "mock_vendor_quotations.json"

# One event, three quotation requests to three different offerings.
EVENT_ID = "EV001"
PROPOSAL_ID = "P-001"

# Accept: Golden Whisker confirms capacity and returns a quote.
REQUEST_ACCEPT = {
    "event_id": EVENT_ID,
    "proposal_id": PROPOSAL_ID,
    "vendor_id": "V-CAT-001",
    "offering_id": "V-CAT-001-O1",
    "event_date": "2026-12-05",
    "guest_count": 120,
}

# Reject: Shutter & Frame is already booked on that Sydney date.
REQUEST_REJECT = {
    "event_id": EVENT_ID,
    "proposal_id": PROPOSAL_ID,
    "vendor_id": "V-PHOTO-001",
    "offering_id": "V-PHOTO-001-O2",
    "event_date": "2026-12-05",
    "guest_count": 80,
}

# Pending: Bayside Bite Co has not replied yet (unconfirmed).
REQUEST_PENDING = {
    "event_id": EVENT_ID,
    "proposal_id": PROPOSAL_ID,
    "vendor_id": "V-CAT-002",
    "offering_id": "V-CAT-002-O1",
    "event_date": "2026-12-05",
    "guest_count": 120,
}

# No scenario is configured for this request (Lumen Lens, Melbourne,
# 2026-12-07) — the service must NOT default to acceptance.
REQUEST_NO_SCENARIO = {
    "event_id": EVENT_ID,
    "proposal_id": PROPOSAL_ID,
    "vendor_id": "V-PHOTO-002",
    "offering_id": "V-PHOTO-002-O1",
    "event_date": "2026-12-07",
    "guest_count": 100,
}


def print_reply(reply: dict[str, object]) -> None:
    cents = reply["quoted_total_cents"]
    price = (
        f"AUD {cents / 100:,.2f}" if isinstance(cents, int) else "n/a"
    )
    print(f"  quotation_id : {reply['quotation_id']}")
    print(f"  scenario_id  : {reply['scenario_id']}")
    print(f"  mock         : {reply['mock']}")
    print(f"  status       : {reply['status']}")
    print(f"  available    : {reply['available']}")
    print(f"  quote        : {price}")
    print(f"  reason       : {reply['reason']}")
    print("  trace (request echo):")
    for key in (
        "event_id",
        "proposal_id",
        "vendor_id",
        "offering_id",
        "event_date",
        "guest_count",
    ):
        print(f"    {key}: {reply[key]}")


def main() -> None:
    service = MockVendorQuotationService.from_json_file(SCENARIO_PATH)

    print("=== Mock vendor quotation replies (MOCK, offline) ===")

    for label, request in (
        ("1. accepted", REQUEST_ACCEPT),
        ("2. rejected", REQUEST_REJECT),
        ("3. pending", REQUEST_PENDING),
    ):
        print(f"\n--- {label} ---")
        print_reply(service.request_quotation(**request))

    print("\n--- 4. no configured scenario (must NOT default to acceptance) ---")
    try:
        service.request_quotation(**REQUEST_NO_SCENARIO)
        print("  UNEXPECTED: a reply was returned")
    except ValueError as exc:
        print(f"  ValueError (expected): {exc}")


if __name__ == "__main__":
    main()
