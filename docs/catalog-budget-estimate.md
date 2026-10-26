# Planner catalogue budget precheck (KAN-41)

This is a Python Service interface on the shared VendorProcurementService,
before enquiries or any Procurement LLM decision. It reads the existing JSON
catalogue and creates no rounds, quotations, bookings, payments or database writes.
It does not add a separate HTTP server or change the integrated Planner branch.

## Call from Planner's workflow

```python
from src.services.vendor_procurement_service import VendorProcurementService

catalog = VendorProcurementService.from_json_file("data/vendor_catalog.json")
request = {
    "event_date": "2026-12-16",
    "location": "Sydney",
    "guest_count": 50,
    "budget_limit_cents": 1200000,
    "customer_preferences": "Photography quality is the priority.",
    "services": [
        {"service_type": "photography"},
        {"service_type": "catering"},
        {"service_type": "venue"},
        {"service_type": "sound"},
        {"service_type": "decoration"},
    ],
}
estimate = catalog.estimate_event(request)
```

All amounts are integer AUD cents. Required fields are event_date (real
YYYY-MM-DD), location (nonempty text), guest_count (nonnegative integer),
budget_limit_cents (nonnegative integer), and services (1-5 unique service
objects). Booleans, float money, duplicate normalized service names and invalid
ratings are rejected with ValueError. No event/proposal ID is needed yet.

Optional min_rating (0-5, finite) may be global or per service. Both apply:
a service cannot weaken the global minimum. Optional supplier_budget_limit_cents
can further restrict the Finance-derived supplier allowance. The returned
allowance never reserves less than the current Finance policy.

The integrated Planner currently emits required_services as a string list.
Its workflow must adapt this to services objects before calling:

```python
request["services"] = [
    {"service_type": kind} for kind in planner_requirements["required_services"]
]
```

Preserve date, location, guests, total budget and customer preferences in the
same request. This adapter is documented here; the separate Planner branch is
not modified by this feature.

## Result and decisions

The result is JSON-compatible Service data, not an Agent envelope. A workflow
can place it in its existing Agent/API response.

| status | Meaning | Suggested workflow action |
|---|---|---|
| within_budget_estimate | All service categories have matches and the cheapest catalogue subtotal plus fees fits the limits. | Show the estimate; proceed to formal enquiries when appropriate. |
| over_budget_estimate | The catalogue minimum exceeds the customer budget or a stricter supplier cap. | Ask about scope, specifications or budget before formal enquiries. |
| no_candidates | At least one category has no date/location/capacity/rating match. | Clarify requirements or explain catalogue coverage; do not treat the missing service as free. |

Every result includes:
- estimate_only=true, finance_review_required=true, preferences_evaluated=false.
- Normalized event_date/location/guest_count, budget_limit_cents and effective
  supplier_budget_limit_cents.
- service_estimates: service_type, candidate_count, min_rating and minimum /
  maximum_catalog_price_cents. Prices are null for an unmatched category.
- missing_services: names of unmatched categories.
- minimum_costs: vendor_cost_cents, service_fee_cents,
  contingency_amount_cents, tax_amount_cents, customer_price_cents.
- budget_shortfall_cents: amount by which the complete reference cost exceeds
  the customer's total budget (zero if it fits).
- supplier_budget_shortfall_cents: amount by which the catalogue subtotal exceeds
  the effective supplier cap (zero if it fits).

If any service is unmatched, minimum_costs and both shortfalls are null.
Partial totals are not presented as complete event costs. A stricter supplier
cap can produce over_budget_estimate with zero customer shortfall; use
supplier_budget_shortfall_cents to explain that case.

Example for the Sydney, 50-person, 16 December 2026 five-service fixture:
minimum prices are photography 95000, catering 380000, venue 250000, sound
70000, decoration 60000. Supplier subtotal is 855000; service fee and
contingency are 85500 each; customer reference total is 1026000.
At a 1200000 customer budget the supplier allowance is 1000000, even if the
input fixture supplies 1100000. At a 50000 customer budget the status is
over_budget_estimate and customer shortfall is 976000.

## Passing the allowance to Procurement

Only after handling the estimate and creating the normal event/proposal context,
the workflow can set the Procurement request's supplier_budget_limit_cents to
the returned value and preserve customer_preferences and per-service preferences.
Continue through the existing staged supplier UI calls or procure_services()
for the explicit simulated-supplier shortcut. Estimation itself calls neither.

This remains a workflow decision, not an automatic cross-Agent call inside
VendorProcurementService. A catalogue estimate is not a permanent rejection
rule: actual quotations can differ, and the customer may revise the request.

## Financial rule and limitations

src/shared/costing.py holds the same exact policy now used by
Budget.calculate_total(): independently rounded 10% service fee and 10%
contingency, GST-inclusive vendor costs, no additional tax.
supplier_budget_ceiling() finds the largest whole-cent supplier subtotal whose
full cost fits the customer budget; it accounts for rounding at the boundary.
Financial's selected-quote validation, approvals and payment gates are unchanged.

Whole-event catalogue prices are used as stored. Guest count filters capacity;
it does not multiply a per-person price. There are no hourly rates, duration
adjustments or arrival/setup charges. Availability is by date, not exact time.
Each service minimum is independent; no new cross-service resource-conflict
solver is introduced.

Soft allocations and text preferences do not change this minimum. For example,
"better photography" can require more than the minimum even when the estimate
fits. Let Planner clarify a hard rating requirement where appropriate, then
let Procurement compare real quotation bundles. Hard service quote caps continue
to be enforced on actual replies by the existing enquiry workflow.

The maximum in each range is the most expensive eligible catalogue entry,
not a prediction, average, suggested allocation or promise of quality.
within_budget_estimate is not Financial clearance or a supplier commitment.

## Offline demo

```powershell
py -3 -m examples.catalog_estimate_example
py -3 -m examples.catalog_estimate_example --budget-cents 50000
```

Use --request-file for another structured request and --catalog for a custom
catalogue. A valid estimate (including over-budget/no-candidates) is printed as
JSON with exit code 0; invalid input produces a CLI error and nonzero exit.
No school API credentials are required.
