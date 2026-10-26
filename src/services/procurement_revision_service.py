"""Validate FIN-01 feedback and bound process-local Procurement reselection."""
from copy import deepcopy
from uuid import uuid4

from src.services.customer_quotation_service import budget_fingerprint, source_fingerprint
from src.services.vendor_booking_service import quotation_fingerprint
from src.shared.costing import calculate_event_costs, supplier_budget_ceiling
from src.shared.schemas import require_int, require_non_empty_str


class RevisionConflict(ValueError):
    """Stale/inconsistent feedback or an already consumed automatic revision."""


class ProcurementRevisionService:
    """One automatic attempt per event/proposal; no supplier or LLM calls.

    This is serialized process-local workflow state, like the enquiry batches.
    Results are copied on storage/replay. It is not durable idempotency or
    authentication; callers must use their trusted Finance workflow result.
    """

    def __init__(self, enquiries):
        self._enquiries = enquiries
        self._attempts = {}

    def begin(self, request):
        if not isinstance(request, dict):
            raise ValueError("request must be an object")
        ref = {k: require_non_empty_str(request.get(k), k)
               for k in ("event_id", "proposal_id", "batch_id")}
        batch = self._enquiries.get_batch(**ref)
        event, proposal, review = (request.get(k) for k in ("event", "proposal", "finance_result"))
        if not all(isinstance(value, dict) for value in (event, proposal, review)):
            raise ValueError("event, proposal and finance_result must be objects")
        data = review.get("data")
        if (review.get("agent") != "finance" or review.get("status") != "blocked"
                or review.get("event_id") != ref["event_id"] or not isinstance(data, dict)
                or data.get("budget_valid") is not True or data.get("within_budget") is not False):
            raise RevisionConflict("A valid over-budget FIN-01 result is required")
        if any(record.get("event_id") != ref["event_id"] for record in (event, proposal, data)):
            raise RevisionConflict("Finance event_id does not match the enquiry batch")
        if any(record.get("proposal_id") != ref["proposal_id"] for record in (proposal, data)):
            raise RevisionConflict("Finance proposal_id does not match the enquiry batch")
        if data.get("source_fingerprint") != source_fingerprint(event, proposal):
            raise RevisionConflict("Finance event/proposal source has changed")

        required = batch["required_services"]
        if (not isinstance(proposal.get("required_services"), list)
                or not isinstance(data.get("required_services"), list)
                or set(proposal["required_services"]) != set(required)
                or set(data["required_services"]) != set(required)
                or len(proposal["required_services"]) != len(required)
                or len(data["required_services"]) != len(required)):
            raise RevisionConflict("Finance required services differ from the stored batch")
        if any(r["awaiting_replies"] for r in batch["service_rounds"]):
            raise RevisionConflict("Wait for every stored supplier reply before reselection")
        for current in batch["service_rounds"]:
            context = current["context"]
            if (event.get("event_date") != context["event_date"]
                    or type(event.get("guest_count")) is not int
                    or event["guest_count"] != context["guest_count"]):
                raise RevisionConflict("Finance date/guest count differs from stored enquiries")
            if "location" in event and event["location"].strip().lower() != context["location"].strip().lower():
                raise RevisionConflict("Finance location differs from stored enquiries")

        selected = data.get("selected_quotation_ids")
        if not isinstance(selected, list) or len(selected) != len(required):
            raise ValueError("Finance must identify one selected quote per service")
        for identity in selected:
            require_non_empty_str(identity, "selected quotation ID")
        if len(set(selected)) != len(selected):
            raise ValueError("Finance selected quotation IDs must be unique")
        quotes = {q["quotation_id"]: q for r in batch["service_rounds"] for q in r["quotations"]}
        if any(identity not in quotes for identity in selected):
            raise RevisionConflict("Finance selected quotes are not from this enquiry batch")
        chosen = [quotes[identity] for identity in selected]
        if {q["service_type"] for q in chosen} != set(required):
            raise RevisionConflict("Finance selection does not cover each required service")
        if data.get("quotation_fingerprint") != quotation_fingerprint(chosen):
            raise RevisionConflict("Finance quotation prices or identities have changed")
        eligible = {
            c["quotation_id"]
            for r in batch["service_rounds"]
            for c in self._enquiries.comparison(ref["event_id"], ref["proposal_id"], r["round_id"])[1]
        }
        if any(identity not in eligible for identity in selected):
            raise RevisionConflict("Finance selected quotes violate stored hard service constraints")

        limit = require_int(data.get("budget_limit_cents"), "budget_limit_cents")
        if type(event.get("budget_limit_cents")) is not int or event["budget_limit_cents"] != limit:
            raise RevisionConflict("Finance customer budget differs from current event")
        context = batch.get("selection_context")
        if not isinstance(context, dict):
            raise RevisionConflict("A stored joint-selection batch is required")
        if context.get("budget_limit_cents") is not None and context["budget_limit_cents"] != limit:
            raise RevisionConflict("Customer budget changed; Planner review/new proposal required")

        expected = calculate_event_costs(sum(q["quoted_total_cents"] for q in chosen))
        for field, cost_field in (
            ("vendor_total_cents", "vendor_cost_cents"),
            ("service_fee_cents", "service_fee_cents"),
            ("contingency_cents", "contingency_amount_cents"),
            ("tax_amount_cents", "tax_amount_cents"),
            ("estimated_total_cents", "customer_price_cents"),
        ):
            if require_int(data.get(field), field) != expected[cost_field]:
                raise RevisionConflict("Finance amounts do not match the current exact cost policy")
        over = require_int(data.get("over_budget_cents"), "over_budget_cents")
        if over <= 0 or over != expected["customer_price_cents"] - limit:
            raise RevisionConflict("Finance does not show a consistent positive budget overrun")
        if data.get("price_basis") != "GST-inclusive":
            raise RevisionConflict("Unsupported Finance price basis")
        if data.get("budget_fingerprint") != budget_fingerprint(data):
            raise RevisionConflict("Finance budget contents changed after validation")

        key = (ref["event_id"], ref["proposal_id"])
        signature = (ref["batch_id"], data["budget_fingerprint"])
        previous = self._attempts.get(key)
        if previous is not None:
            if previous["signature"] != signature:
                raise RevisionConflict("One automatic reselection is allowed per proposal; Planner review required")
            if previous["result"] is None:
                raise RevisionConflict("This automatic reselection is already running")
            return {"cached_result": deepcopy(previous["result"])}

        ceiling = supplier_budget_ceiling(limit)
        if context.get("supplier_budget_limit_cents") is not None:
            ceiling = min(ceiling, context["supplier_budget_limit_cents"])
        # Only narrow a copied snapshot; original enquiry facts/preferences remain intact.
        batch["selection_context"]["budget_limit_cents"] = limit
        batch["selection_context"]["supplier_budget_limit_cents"] = ceiling
        metadata = {
            "revision_id": "PRV-" + uuid4().hex,
            "attempt": 1,
            "source_batch_id": ref["batch_id"],
            "source_budget_fingerprint": data["budget_fingerprint"],
            "previous_selected_quotation_ids": list(selected),
            "previous_vendor_total_cents": data["vendor_total_cents"],
            "previous_customer_total_cents": data["estimated_total_cents"],
            "supplier_budget_limit_cents": ceiling,
        }
        self._attempts[key] = {"signature": signature, "metadata": deepcopy(metadata), "result": None}
        return {"cached_result": None, "key": key, "batch": batch, "revision": metadata}

    def finish(self, prepared, result):
        result = deepcopy(result)
        data = result["data"]
        data["financial_revision"] = deepcopy(prepared["revision"])
        data["finance_review_required"] = True
        if result["status"] == "success":
            data["next_action"] = "finance_review"
        elif data.get("budget_summary", {}).get("supplier_bundle_feasible") is False:
            data["next_action"] = "planner_review"
            minimum = data["budget_summary"]["minimum_supplier_total_cents"]
            total = calculate_event_costs(minimum)["customer_price_cents"]
            data["minimum_customer_total_cents"] = total
            data["minimum_budget_shortfall_cents"] = max(
                0, total - data["budget_summary"]["budget_limit_cents"])
        else:
            data["next_action"] = "manual_review"
        self._attempts[prepared["key"]]["result"] = deepcopy(result)
        return result
