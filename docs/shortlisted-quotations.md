# Shortlisted enquiries and quotation comparison (KAN-36)

Opt-in Python interface for one service category per round. Existing handle(),
request_quotations() and confirm_bookings() calls and their output contracts remain
unchanged. The team can keep integrating those entry points until ready to adopt
this workflow. No FastAPI route or supplier UI is added.

## Try it

Run from the repository root:

    python -m examples.shortlisted_quotation_example

This offline MOCK demo starts with A/B/C recommended from four fictional
photographers. A's catalog estimate is AUD 900, but its submitted quote is AUD
1,300; B submits AUD 950; C declines. The second comparison proposes B, and D
receives no enquiry. Both model responses in the example are explicitly scripted.
Pass the existing CampusQwenClient to the Agent for live model comparisons;
supplier input remains explicitly simulated and no LLM generates supplier facts.

## Calls and data

1. prepare_enquiries(request)
   - Existing event_id, service_type, event_date, guest_count, location,
     customer_preferences and optional min_rating, plus required proposal_id.
   - Optional service_budget_cents (nonnegative integer AUD cents) is a soft
     service target. budget_is_hard_limit defaults to false; true requires a target.
     This is not the whole-event budget and does not change Financial policy.
   - Returns the standard Agent envelope with data.round_id, context,
     recommendations and enquiries. Each enquiry includes enquiry_id,
     initial_rank, read-only catalog candidate facts and a pending reply.
   - Exactly min(3, eligible candidate count) are shortlisted. No synthetic filler
     suppliers if fewer than three qualify. Invalid/incomplete LLM rankings fail.
     Catalog availability and price are preliminary, never supplier confirmation.

2. submit_quotation_reply(request)
   - Required: event_id, proposal_id, round_id, enquiry_id, mock=true,
     status (accepted/rejected/pending), and nonempty reason.
   - accepted requires quoted_total_cents; pending/rejected must omit it or use null.
   - Supplier identity, date, headcount and quote IDs come from the stored enquiry.
     Echoed identity fields must match. This method calls no LLM.
   - Accepted quotation snapshots optionally use the Agent's existing
     record_service for SQLite storage. Failed saves do not accept the reply locally.
   - Replaying the same final reply is safe. A changed final price/rejection needs
     a new round and normal downstream review; it never overwrites an approved quote.

Example supplier form submission (IDs come from prepare_enquiries):

    result = agent.submit_quotation_reply({
        "event_id": "EV-SHORTLIST", "proposal_id": "P-SHORTLIST",
        "round_id": round_id, "enquiry_id": enquiry_id,
        "mock": True, "status": "accepted",
        "quoted_total_cents": 95000,  # AUD 950.00, GST-inclusive under current V1 convention
        "reason": "MOCK: can provide the requested photography service.",
    })

3. get_enquiry_round({event_id, proposal_id, round_id})
   - Returns detached enquiry/reply/quotation snapshots for UI polling.
     Do not edit the returned dictionaries to update supplier state.

4. compare_quotations({event_id, proposal_id, round_id})
   - Uses the original stored requirements, not new requirements in a lookup request.
   - Blocks while any shortlisted reply is pending; does not guess missing prices.
     There is no timeout or automatic next-batch fallback in this increment.
   - Rejected quotes cannot rank. Hard service budget exclusions run before the
     LLM; soft over-target quotes remain eligible and show over_target_cents.
   - The model ranks every eligible accepted quote, using received prices, catalog
     rating/capacity, and customer preferences. Code verifies identities, unique
     coverage and any lowest-price/highest-rating/highest-capacity basis codes.
     Money and identity always come from facts; prose reasons are not fully verified.
   - data.quotations retains ALL accepted snapshots in the existing quotation
     format, including alternatives excluded by a hard limit.
   - data.quotation_ranking contains the new ranking and reasons.
   - data.selected_quotation_ids and data.selected_quotations identify ONE proposed
     supplier for this service. This is not customer approval or a booking.

## Financial and booking handoff

Run one independent round per service category. Supervisor combines the proposed
selected_quotations from completed rounds and hands only the selected snapshots
and IDs to Financial. Never add all same-service alternatives together as costs.
Financial still checks the whole-event supplier total, company fee and contingency.

After Financial review, customer approval and deposit, pass the same selected
quote snapshots to existing confirm_bookings(). Existing fingerprints and gates
still apply. There is no bypass or automatic payment, booking or owner approval.
The integration test checks real Financial totals and the existing booking gates.

## Demo scope

Rounds, pending enquiries and their replies are in memory, per Agent instance.
A future supplier UI must share that backend instance (not a separate Agent per
browser session) or introduce a durable enquiry store before relying on restart
recovery. Only accepted quotes are optionally saved through existing SQLite
storage; pending rounds and final rankings are not recovered after restart.

The caller owns current event/proposal authority, as in the existing handoff.
The simulated supplier form is not authenticated proof from a real supplier.
Use a new round when requirements change, use its newly selected quote IDs, and
obtain fresh Financial/customer review. No service-time windows, supplier login,
expiry, concurrent submissions, negotiation or automatic replacement are added.
