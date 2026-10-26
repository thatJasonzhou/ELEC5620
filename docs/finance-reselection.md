# Finance feedback and Procurement reselection (KAN-42)

This additive Python interface builds on the catalogue precheck in PR #23.
It uses FinancialManagerAgent's existing FIN-01 result; Finance's interface and
calculation code are not changed.

## Existing FIN-01 feedback

Use the full envelope returned by Finance's prepare_budget action. Its over-budget
case has agent=finance, status=blocked, and data containing budget_valid=true,
within_budget=false, budget_limit_cents, over_budget_cents, the exact fee/total
breakdown, selected_quotation_ids, required_services, quotation_fingerprint,
source_fingerprint and budget_fingerprint.

This is structured data passed by the workflow, not two LLMs chatting.
Finance need not add a new supplier-limit field: the revision Service uses the
shared exact Finance policy to derive the allowance from the validated total
customer budget. It also retains any stricter stored supplier cap.

## Workflow call (Python code, not a PowerShell command)

After normal joint Procurement and Finance review:

```python
feedback = finance.handle({**financial_handoff, "action": "prepare_budget"})
if (
    feedback["status"] == "blocked"
    and feedback["data"].get("budget_valid") is True
    and feedback["data"].get("within_budget") is False
):
    revised = procurement.reselect_after_finance({
        "event_id": original_procurement["data"]["event_id"],
        "proposal_id": original_procurement["data"]["proposal_id"],
        "batch_id": original_procurement["data"]["batch_id"],
        "event": financial_handoff["event"],
        "proposal": financial_handoff["proposal"],
        "finance_result": feedback,
    })
```

The Procurement Agent must have compact_llm=True and joint_selection=True.
Pass the exact event/proposal snapshots that Finance reviewed, including optional
revision fields. The original batch must still exist in the same process.

The Service checks:
- Finance identity/status and an internally consistent positive overrun.
- Matching event/proposal, required services, date and guest count.
- Matching location when present in the Finance event.
- Selected quote IDs, immutable stored prices, stored hard service constraints.
- Source/quotation/budget fingerprints and exact current Finance fee arithmetic.
- Matching original total customer budget when that was stored during procurement.

Fingerprints are consistency references, not authentication signatures. The
application must supply its trusted internal Finance result rather than arbitrary
customer-provided JSON. Public API authorization belongs to the integrated app.

## Selection and result

The existing accepted replies and original preferences are reused. No supplier
is enquired again, no catalogue estimate substitutes for a quote, and no
requirement is silently changed. The copied selection context receives the
Finance-derived supplier cap; original rounds and batch context remain intact.

The normal exact feasibility check runs before the LLM:
- If a combination fits, one logical joint LLM decision proposes a new bundle.
- If even the cheapest eligible quotes cannot fit, no further LLM call is made.
- Existing explicit per-service hard caps and rating eligibility still apply.

The standard Procurement envelope contains:
- financial_revision: revision_id, attempt=1, source_batch_id,
  source_budget_fingerprint, previous selected IDs/costs and new supplier cap.
- finance_review_required=true.
- next_action=finance_review on success. Only the newly selected quotation
  list/IDs should be sent to Finance for a fresh prepare_budget call.
- next_action=planner_review if the cheapest eligible bundle is infeasible.
  minimum_customer_total_cents and minimum_budget_shortfall_cents explain the
  complete fee-inclusive gap. Selection remains empty.
- next_action=manual_review for a failed model/other comparison failure.
  No earlier successful selection is released as a new success.

A successful reselection is not an approved customer quotation or booking.
The old blocked budget cannot authorize the new quote set. Fresh Finance
validation, customer quotation/approval, deposit and supplier confirmation
remain separate existing steps. This feature changes no existing bookings.

Use the revision response for the next workflow step. Calling the ordinary
compare_event_quotations on the original batch still uses its original context;
the revision does not overwrite that historical enquiry batch.

## Bounds and recovery

One automatic attempt is reserved per event/proposal, including infeasible or
failed attempts. Identical feedback replays a deep copy of the stored result
with the same revision ID/timestamp; it does not count as fresh LLM reasoning.
Different feedback after consumption is blocked for explicit Planner/manual review.
Invalid feedback does not consume an attempt.

A configured transport-retry policy can still retry a failed LLM request inside
that one logical attempt; this interface adds no automatic workflow retry loop.
After a failed attempt, the workflow must handle the failure explicitly.

Like enquiry batches, revision state is process-local and assumes serialized
calls. It is not persistent idempotency across restarts or concurrent replicas.
A restarted Agent rejects the unknown batch before calling the LLM. Optional
quote persistence does not restore enquiry/revision state. The integration must
serialize operations per activity and use the separate approved change flow
for paid/booked activities; this pre-approval helper is not cancellation handling.

Planner/UI/Supervisor integration remains the team's separate task.

## Offline demonstration (PowerShell)

```powershell
py -3 -m examples.finance_reselection_example
```

Both supplier replies and model decisions are explicit synthetic MOCK fixtures:
- Feasible revision: customer budget AUD11,000; initial full cost AUD12,480;
  revised supplier cost AUD7,950 and full cost AUD9,540. Finance recheck passes.
- Infeasible revision: customer budget AUD8,000; cheapest full cost AUD9,120;
  return Planner review with an AUD1,120 gap and no second LLM call.

Each case uses 15 initial enquiries. Repeated revision calls do not add enquiries
or LLM calls. Finance uses no LLM and no payment is requested.
These cases validate orchestration and contracts, not school-model reasoning.
