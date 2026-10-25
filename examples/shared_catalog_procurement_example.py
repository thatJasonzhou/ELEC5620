"""Shared catalogue demo: five suppliers per service; optional real LLM decisions.

Run from the repository root:
    python -m examples.shared_catalog_procurement_example
    python -m examples.shared_catalog_procurement_example --live
Supplier replies and booking presets remain fictional in either mode.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from examples.event_procurement_example import SERVICE_TYPES, mock_compare
from src.agents.vendor_procurement_manager import VendorProcurementManagerAgent
from src.llm import CampusQwenClient, MockLLMClient
from src.services.vendor_procurement_service import VendorProcurementService
from src.services.vendor_quotation_service import MockVendorQuotationService

ROOT = Path(__file__).resolve().parents[1]


def catalog_service_types():
    """Read available categories from the shared catalogue, not a fixed UI list."""
    catalog = VendorProcurementService.from_json_file(ROOT / "data/vendor_catalog.json")
    return sorted({o.service_type for vendor in catalog.catalog for o in vendor.service_offerings})


def build_agent(*, live=False):
    return VendorProcurementManagerAgent(
        llm=CampusQwenClient.from_env() if live else MockLLMClient(mock_compare),
        vendor_service=VendorProcurementService.from_json_file(ROOT / "data/vendor_catalog.json"),
        quotation_service=MockVendorQuotationService.from_json_file(
            ROOT / "data/mock_vendor_quotations.json"),
    )


def event_request(*, city="Sydney", date="2026-12-16", guests=50, services=None):
    selected_services = SERVICE_TYPES if services is None else services
    return {
        "event_id": "EV-SHARED-CATALOG", "proposal_id": "P-SHARED-CATALOG",
        "event_date": date, "guest_count": guests, "location": city,
        "customer_preferences": "Compare submitted price and rating; prefer value.",
        "services": [{"service_type": service} for service in selected_services],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                        help="Use CampusQwenClient; supplier replies stay MOCK.")
    parser.add_argument("--city", choices=("Sydney", "Melbourne"), default="Sydney")
    parser.add_argument("--date", choices=("2026-12-16", "2026-12-17"), default="2026-12-16")
    parser.add_argument("--guests", type=int, choices=(50, 80), default=50)
    parser.add_argument("--services", nargs="+", choices=catalog_service_types(),
                        help="Choose 1-5 services from the shared catalogue; defaults to the original five.")
    args = parser.parse_args()
    if args.services is not None and (len(args.services) > 5 or len(set(args.services)) != len(args.services)):
        parser.error("--services requires 1-5 distinct categories.")
    result = build_agent(live=args.live).procure_services(
        event_request(city=args.city, date=args.date, guests=args.guests, services=args.services))
    data = result.get("data") or {}
    rounds = data.get("service_rounds", [])
    print(json.dumps({
        "llm_mode": "live" if args.live else "mock", "supplier_source": "mock",
        "status": result["status"], "message": result["message"],
        "enquiry_count": sum(len(r["enquiries"]) for r in rounds),
        "selection_complete": data.get("selection_complete", False),
        "selected_quotation_ids": data.get("selected_quotation_ids", []),
        "quotations": data.get("quotations", []),
        "service_results": data.get("service_results", []),
    }, ensure_ascii=False, indent=2))
    if result["status"] != "success" or not data.get("selection_complete"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
