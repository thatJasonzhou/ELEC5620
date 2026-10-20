"""Independent example inputs for the vendor filtering demo (KAN-15).

Run with:  py -3 -m examples.vendor_filtering_example
"""
from __future__ import annotations

from pathlib import Path

from src.services.vendor_procurement_service import VendorProcurementService

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = REPO_ROOT / "data" / "vendor_catalog.json"

# Example 1: 120 guests, Melbourne, 2026-12-05, catering.
EXAMPLE_CATERING = {
    "service_type": "catering",
    "date": "2026-12-05",
    "guest_count": 120,
    "location": "Melbourne",
}

# Example 2: 80 guests, Melbourne, 2026-12-05, photography.
EXAMPLE_PHOTOGRAPHY = {
    "service_type": "photography",
    "date": "2026-12-05",
    "guest_count": 80,
    "location": "Melbourne",
}


def main() -> None:
    service = VendorProcurementService.from_json_file(CATALOG_PATH)

    for example in (EXAMPLE_CATERING, EXAMPLE_PHOTOGRAPHY):
        print("\n=== Filtering request ===")
        for key, value in example.items():
            print(f"  {key}: {value}")

        results = service.filter_vendors(**example)

        print(f"=== {len(results)} match(es) ===")
        for item in results:
            price_aud = item["total_price_cents"] / 100
            print(
                f"  {item['vendor_id']} | {item['vendor_name']} | "
                f"{item['service_type']} @ {item['service_location']} | "
                f"capacity {item['guest_capacity']} | "
                f"rating {item['rating']} | "
                f"price AUD {price_aud:,.2f} | {item['date']}"
            )
        if not results:
            print("  (no matching vendors)")


if __name__ == "__main__":
    main()
