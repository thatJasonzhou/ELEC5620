"""Offline Planner precheck: python -m examples.catalog_estimate_example."""
import argparse
import json
from pathlib import Path

from src.services.vendor_procurement_service import VendorProcurementService

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-file", type=Path,
                        default=ROOT / "examples/requests/procurement_priority_request.json")
    parser.add_argument("--budget-cents", type=int,
                        help="Override the customer total budget, in integer AUD cents.")
    parser.add_argument("--catalog", type=Path, default=ROOT / "data/vendor_catalog.json")
    args = parser.parse_args()
    try:
        request = json.loads(args.request_file.read_text(encoding="utf-8"))
        if not isinstance(request, dict):
            raise ValueError("request must be an object")
        if args.budget_cents is not None:
            request["budget_limit_cents"] = args.budget_cents
        result = VendorProcurementService.from_json_file(args.catalog).estimate_event(request)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
