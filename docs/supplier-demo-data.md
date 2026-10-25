# Shared supplier demo data (KAN-39)

The default shared catalogue now contains **50 fictional suppliers across 10 service categories**, with **five distinct suppliers in each category**:

| service_type | Suppliers | Offerings per city |
|---|---:|---:|
| photography | 5 | 5 |
| catering | 5 | 5 |
| venue | 5 | 5 |
| sound | 5 | 5 |
| decoration | 5 | 5 |
| videography | 5 | 5 |
| lighting | 5 | 5 |
| entertainment | 5 | 5 |
| transport | 5 | 5 |
| event_staff | 5 | 5 |

Each supplier has a Sydney and a Melbourne offering: **100 offerings** in total.
Names are fictional; all prices, ratings, capacities and availability are demo inputs.
Estimates vary between offerings; actual mock supplier prices may increase or decrease from the catalogue estimate.
Existing suppliers retain their original IDs, prices, ratings, capacities and historical date statuses.

## Common inputs for frontend and integration

- Location: `Sydney` or `Melbourne`.
- Date: `2026-12-16` or `2026-12-17`.
- Guest count: **50 or 80**.
- Services: choose **1-5 of the ten categories** above, with no repeats.
  The catalogue offers ten choices; an activity still uses at most five services.
- At these inputs, every category has five eligible suppliers before shortlisting.
- Higher headcounts are filtered against capacity; their quotation presets are not provided.
  Other dates retain historical or absent availability and are not covered by the new complete demo set.

The default `data/vendor_catalog.json`, `data/mock_vendor_quotations.json` and
`data/mock_vendor_bookings.json` are now matched:
**403 quotation scenarios** (400 new + 3 legacy) and **361 booking scenarios** (360 new + 1 legacy).
Quotes are explicitly keyed by supplier, offering, date and guest count; no random prices or automatic acceptance are generated at runtime.

On **16 December**, all five suppliers per service submit accepted quotes.
On **17 December**, supplier 005 per category explicitly declines; the other four accept.
Any top-three shortlist therefore has at least two accepted options, and no newly configured reply remains pending.
The historical 5 December pending/rejection cases remain available for exception demonstrations.

Every accepted new quotation has a matching final mock booking confirmation.
These presets do not bypass Financial, customer approval or deposit checks: continue using the existing gated booking entry.

## Run using the shared JSON files

From the repository root:

```powershell
py -3 -m examples.shared_catalog_procurement_example
py -3 -m examples.shared_catalog_procurement_example --city Melbourne --date 2026-12-17 --guests 80
```

Choose any combination of up to five catalogue categories:

```powershell
py -3 -m examples.shared_catalog_procurement_example --services videography lighting entertainment transport event_staff
py -3 -m examples.shared_catalog_procurement_example --city Melbourne --guests 80 --services photography venue lighting
```

The first two default commands use the shared catalogue and quote files, shortlist three per category
(15 enquiries), and return five selected quotes with `selection_complete=true`.
The old `examples.event_procurement_example` deliberately retains its separate small A/B/C/D fixtures.

To use the school LLM for recommendation and quotation comparison:

```powershell
# Configure ELEC5620_LLM_BASE_URL, ELEC5620_LLM_MODEL and ELEC5620_LLM_API_KEY first.
py -3 -m examples.shared_catalog_procurement_example --live
```

Live changes the model client only; suppliers/replies remain simulated.
Use actual school configuration on the demonstration machine. Full Live connectivity is not certified by the offline data checks.
Live may produce a different shortlist or winner. The script checks workflow success, not a fixed supplier.
The initial `mock:true` quotation flag describes the supplier-source simulation even when the LLM runs Live.

## Team usage

Frontend service options should be derived from the catalogue (as the existing
recommendation page already does); use the exact service_type values above.
Do not hard-code the original five or auto-select all ten.
The shared demo derives its --services choices from the catalogue too; its default
request retains the original five for backward compatibility. Three chosen
categories produce nine enquiries and three selected quotations.


The module API is unchanged: create `VendorProcurementManagerAgent` using these
JSON-backed services, then call `procure_services(request)`.
The first recommendation uses directory estimates; the second comparison uses submitted quotation totals.
Only the final activity-level `data.quotations` should go to Financial.
The old recommendation-only UI automatically reads the expanded catalogue,
but its existing `handle()` call still shows only initial recommendations.

For the API request/reply contract see [shortlisted-quotations.md](shortlisted-quotations.md).
