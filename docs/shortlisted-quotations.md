# Procurement quotation workflow (KAN-36)

This is the updated Procurement business flow for the team's full-version
integration: service requirements -> top-three shortlists -> simulated supplier
quotation replies -> quotation-based comparison -> selected supplier quotes.
Only Procurement is changed. Team members pull the update and connect their own
Planner, Supervisor, Financial and Operations code.

## Activity-level entry point

    result = procurement.procure_services({
        "event_id": "EV001", "proposal_id": "P1",
        "event_date": "2026-12-16", "guest_count": 50, "location": "Sydney",
        "customer_preferences": "Prefer value and good ratings.",
        "services": [
            {"service_type": "photography", "service_budget_cents": 100000},
            {"service_type": "catering", "service_budget_cents": 200000},
        ],
    })

- The complete activity proposal contains 1-5 service items, one per category.
  Categories are not restricted to the five example names; the injected catalogue
  determines which offerings actually exist. Duplicate categories are rejected.
  Each item may override shared date, headcount, location, preferences and rating
  requirements, but cannot change event_id or proposal_id.
- Optional service_budget_cents is a soft reference target in integer AUD cents.
  budget_is_hard_limit=true makes that service target a hard limit on received
  quotes. This does not allocate the customer's whole-event budget.
- All service inputs are validated before model/supplier calls. More than five
  items are rejected without truncation. Lower-level re-enquiries reuse the
  category's slot; a sixth category in the same proposal is also rejected.
  Changed proposal versions have separate service lists.
- Each service gets exactly min(3, eligible candidate count) initial
  recommendations. Initial facts use catalogue estimates and preliminary
  availability. There are at most 15 enquiry objects per activity batch.
- The configured MockVendorQuotationService supplies actual simulated replies for
  only these shortlisted offerings. No source means no automatic quote; a missing
  preset remains pending. Catalogue prices never silently become supplier quotes.
- Accepted replies are compared again using the received amounts, catalogue
  rating/capacity and customer preferences. Pending suppliers are awaited;
  rejected suppliers cannot rank. Hard caps are checked by code before comparison.
  Facts/identities and ranking coverage are checked against real input snapshots;
  LLM prose explanations are not fully fact-verified.
- If any required service is pending, unfulfillable, over its hard cap or fails
  comparison, the whole activity has selection_complete=false and empty top-level
  quotations/selected_quotation_ids. Partial results remain visible for diagnosis.
- Success returns one selected quotation per service, at most five. The same
  vendor may supply several different services; distinct offerings and quotation
  IDs retain their separate contracts.

## Outputs for team integration

All calls return the existing Agent envelope: event_id, agent, timestamp,
status, message and data.

At the ACTIVITY level (procure_services / compare_event_quotations):

- data.required_services preserves the requested service list.
- data.service_rounds contains each initial shortlist, enquiries and supplier replies.
- data.service_results contains each service's quotation_ranking and choice reasons.
- data.candidate_quotations contains all accepted alternatives after comparison.
- data.quotations and data.selected_quotations contain ONLY the proposed selected
  snapshots when selection_complete=true.
- data.selected_quotation_ids identifies those selected snapshots.

These selected quotations use the existing quotation shape, including
event_id, proposal_id, quotation_id, vendor_id, offering_id, service_type,
event_date, guest_count, quoted_total_cents, available=true, mock=true,
scenario_id and recommendation_reason. Extra status/reason fields describe the
supplier reply. All money follows the current GST-inclusive integer-cents convention.

The team can pass activity data.quotations and selected_quotation_ids to Financial.
Financial still computes the whole-event total, company fee and contingency.
A successful Procurement selection is not financial approval, customer approval,
a paid deposit, or a confirmed booking. Existing confirm_bookings gates remain.

Existing handle(), request_quotations() and confirm_bookings() signatures remain
compatible. The old recommendation-only interface still performs its original
job; procure_services is the updated multi-service Procurement workflow.

## Supplier response interface, ready for a later UI

The current mock source and a future supplier input page share the same
submit_quotation_reply boundary:

1. prepare_event_enquiries(full_request) creates all shortlists and returns
   event_id, proposal_id, batch_id and per-service enquiries.
2. Current simulation: request_event_quotations({event_id, proposal_id, batch_id})
   asks the configured mock source and submits its replies.
   Future supplier UI: skip that collector, display the prepared enquiries and
   call submit_quotation_reply for each form submission.
3. compare_event_quotations({event_id, proposal_id, batch_id}) re-compares the
   whole original service list. Client-supplied round subsets cannot silently
   remove required services.

Example reply (IDs come from a prepared enquiry):

    procurement.submit_quotation_reply({
        "event_id": "EV001", "proposal_id": "P1",
        "round_id": round_id, "enquiry_id": enquiry_id,
        "mock": True, "status": "accepted",
        "quoted_total_cents": 95000,  # AUD 950.00
        "reason": "MOCK supplier can provide the requested service.",
    })

accepted requires an integer amount; pending/rejected carry no accepted price.
Identity/date/headcount are bound to the stored enquiry and any echoed fields
must match. This method calls no LLM and does not book anything. Accepted quotes
optionally use the existing record_service for SQLite storage. Same final replies
replay safely; changed final prices need a new round and fresh downstream review.

The single-service prepare_enquiries / get_enquiry_round / compare_quotations
methods remain available. At that LOWER level, data.quotations includes all
accepted candidates, while data.selected_quotations contains only the proposed
selection. Use the activity-level entry for a complete Financial handoff.

## Run the examples

    python -m examples.event_procurement_example

The five-service offline MOCK example submits 15 enquiries and selects five
quotes. A is initially first, then quotes AUD 1,300 instead of the AUD 900 estimate;
B quotes AUD 950 and wins; C declines. Prices scale by service in this fixture.
The same vendor B handles all five different offerings, demonstrating that the
limit is five services, not five distinct companies.

    python -m examples.shortlisted_quotation_example

The smaller single-service example still demonstrates direct supplier input.
Examples use separate fictional catalogues and explicit offline model fixtures;
pass the central CampusQwenClient for live model comparisons. Supplier facts
continue to come from the mock quotation source, not the procurement LLM.

## Runtime boundaries

The module does not modify team orchestration or add a supplier UI/HTTP route.
Use the same Agent/backend instance across prepare, supplier reply and comparison.
Batches, pending rounds, replies and rankings are process-local; only accepted
quotation snapshots optionally survive restart via the existing SQLite service.
There is no enquiry timeout or automatic next-batch fallback yet. Requests must
be serialized; supplier login, concurrent UI writes, service-time windows,
negotiation, automatic replacement and durable enquiry recovery are outside this update.
The team still owns current proposal/approval authority.

## Shared catalogue expansion (KAN-39)

The default shared JSON files now provide ten service choices, each with five
distinct suppliers: photography, catering, venue, sound, decoration, videography,
lighting, entertainment, transport and event_staff. Select 1-5 per activity;
the catalogue category count does not raise the activity service limit. Use Sydney / Melbourne, 2026-12-16 / 2026-12-17,
and 50 / 80 guests for complete reply coverage. The new
`python -m examples.shared_catalog_procurement_example` uses these shared files;
its `--live` switch changes the LLM only. See [supplier demo data](supplier-demo-data.md).

## Optional bounded LLM concurrency (KAN-40)

Pass `llm_concurrency=3` (integer 1-5) and optionally `progress_callback=callable`
when constructing the Agent to overlap LLM requests within each activity phase.
Agent default is 1; shared-data CLI default is 3 and accepts `--concurrency`.
The CLI prints a short summary by default; add `--verbose` for complete diagnostic JSON.
Only model calls run in worker threads, while input snapshots, state writes,
SQLite and output validation remain sequential. Request ordering and complete-selection
gates are preserved. The same Agent must still receive external requests serially.
See [live Procurement demo](live-procurement-demo.md) for fresh-download setup,
progress events, client requirements and performance measurement.

Safe transport diagnostics now appear in failed service data.llm_error and
progress events (code/status only). Optional retry_failed_llm=True retries only
transient failed model jobs once after the phase drains; successes and supplier
enquiries are retained. It defaults to False. The CLI exposes --retry-failed.

The shared CLI also opts into compact_llm=True: a small candidate table and
index/short-reason response, with full public snapshots backfilled/validated by
code. Agent default remains False for legacy injected clients. Compact mode
returns empty basis_codes and still validates identity, coverage and prices.
Use CampusQwenClient.from_env() with compact module callers. The CLI defaults to
server output settings; --max-output-tokens optionally sets a cap (0 omits it).
Truncated output fails. Optional batch_services=True (requires compact_llm=True)
groups all services into one model call per phase; --batch-services selects this
in the shared-data CLI. Supplier replies still separate the two phases.
