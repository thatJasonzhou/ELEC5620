"""Shared catalogue demo: five suppliers per service; optional real LLM decisions.

Run from the repository root:
    python -m examples.shared_catalog_procurement_example
    python -m examples.shared_catalog_procurement_example --live
Supplier replies and booking presets remain fictional in either mode.
"""
from __future__ import annotations

import argparse
import json
import sys
from time import monotonic
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


def build_agent(*, live=False, llm_concurrency=1, progress_callback=None,
                retry_failed_llm=False, compact_llm=True, max_output_tokens=256,
                enable_thinking=None):
    return VendorProcurementManagerAgent(
        llm=CampusQwenClient.from_env(max_output_tokens=max_output_tokens, enable_thinking=enable_thinking) if live else MockLLMClient(mock_compare),
        llm_concurrency=llm_concurrency, progress_callback=progress_callback,
        retry_failed_llm=retry_failed_llm, compact_llm=compact_llm,
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



def format_summary(summary):
    """Keep the normal terminal view short; detailed snapshots are opt-in."""
    lines = [
        f"LLM: {summary['llm_mode'].upper()} | suppliers: MOCK | concurrency: {summary['llm_concurrency']}",
        f"Status: {summary['status']} | selection_complete: {str(summary['selection_complete']).lower()}",
        f"Elapsed: {summary['elapsed_seconds']:.2f}s | enquiries: {summary['enquiry_count']} | selected: {len(summary['selected_quotation_ids'])}",
    ]
    if summary["quotations"]:
        lines.append(f"{'Service':<18} {'Supplier':<16} Quote (AUD)")
        for quote in summary["quotations"]:
            lines.append(f"{quote['service_type']:<18} {quote['vendor_id']:<16} {quote['quoted_total_cents'] / 100:,.2f}")
    if summary["status"] != "success" or not summary["selection_complete"]:
        lines.append(" ".join(summary["message"].split())[:180])
        for item in summary["service_results"]:
            if item["status"] != "success":
                reason = " ".join(item["message"].split())[:160]
                error = (item.get("data") or {}).get("llm_error") or {}
                detail = error.get("code", "")
                if error.get("http_status") is not None:
                    detail += f" HTTP {error['http_status']}"
                label = f" [{detail}]" if detail else ""
                lines.append(f"{item.get('service_type', 'service')}: {item['status']}{label} - {reason}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                        help="Use CampusQwenClient; supplier replies stay MOCK.")
    parser.add_argument("--city", choices=("Sydney", "Melbourne"), default="Sydney")
    parser.add_argument("--date", choices=("2026-12-16", "2026-12-17"), default="2026-12-16")
    parser.add_argument("--guests", type=int, choices=(50, 80), default=50)
    parser.add_argument("--services", nargs="+", choices=catalog_service_types(),
                        help="Choose 1-5 services from the shared catalogue; defaults to the original five.")
    parser.add_argument("--concurrency", type=int, choices=range(1, 6), default=3,
                        help="Maximum simultaneous LLM calls per stage (default 3; use 1 for serial).")
    parser.add_argument("--verbose", action="store_true",
                        help="Print complete diagnostic JSON snapshots instead of the short summary.")
    parser.add_argument("--retry-failed", action="store_true",
                        help="After a phase drains, retry only transient failed LLM jobs once, serially.")
    parser.add_argument("--max-output-tokens", type=int, default=256,
                        help="Maximum generated tokens per Live request (default 256; 0 uses server default).")
    parser.add_argument('--disable-thinking', action='store_true',
                        help='Request Qwen non-thinking mode; backend support must be verified.')
    args = parser.parse_args()
    if args.max_output_tokens < 0:
        parser.error("--max-output-tokens must be nonnegative.")
    if args.services is not None and (len(args.services) > 5 or len(set(args.services)) != len(args.services)):
        parser.error("--services requires 1-5 distinct categories.")
    announced_stages = set()

    def report(event):
        if event["state"] == "submitted" and not args.verbose:
            if event["stage"] in announced_stages:
                return
            announced_stages.add(event["stage"])
            print(f"[{event['stage']}] LLM requests queued/running...", file=sys.stderr, flush=True)
            return
        duration = (f" ({event['elapsed_seconds']:.1f}s)"
                    if "elapsed_seconds" in event else "")
        detail = ""
        if event.get("error_code"):
            detail = f" [{event['error_code']}"
            if event.get("http_status") is not None:
                detail += f" HTTP {event['http_status']}"
            detail += "]"
        print(f"[{event['stage']}] {event['service_type']}: {event['state']}{duration}{detail}",
              file=sys.stderr, flush=True)

    started = monotonic()
    result = build_agent(live=args.live, llm_concurrency=args.concurrency,
                         progress_callback=report, retry_failed_llm=args.retry_failed,
                         max_output_tokens=args.max_output_tokens or None,
                         enable_thinking=False if args.disable_thinking else None).procure_services(
        event_request(city=args.city, date=args.date, guests=args.guests, services=args.services))
    data = result.get("data") or {}
    rounds = data.get("service_rounds", [])
    summary = {
        "llm_mode": "live" if args.live else "mock", "supplier_source": "mock",
        "llm_concurrency": args.concurrency, "retry_failed_llm": args.retry_failed,
        "compact_llm": True, "max_output_tokens": args.max_output_tokens or None,
        "enable_thinking_requested": False if args.disable_thinking else None,
        "elapsed_seconds": round(monotonic() - started, 2),
        "status": result["status"], "message": result["message"],
        "enquiry_count": sum(len(r["enquiries"]) for r in rounds),
        "selection_complete": data.get("selection_complete", False),
        "selected_quotation_ids": data.get("selected_quotation_ids", []),
        "quotations": data.get("quotations", []),
        "service_results": data.get("service_results", []),
    }
    if args.verbose:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(format_summary(summary))
    if result["status"] != "success" or not data.get("selection_complete"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
