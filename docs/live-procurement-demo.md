# Fresh-download Live Procurement demo (KAN-40)

The demonstration runs freshly downloaded code and makes actual school LLM
requests. Supplier quotation replies remain simulated data. No cached model
rankings or automatic Mock fallback are used.

## One joint supplier decision (current opt-in trial)

Run a concrete five-service request with photography as the priority:

```powershell
py -3 -m examples.shared_catalog_procurement_example --live --joint-selection --request-file examples/requests/procurement_priority_request.json
```

The request is simulated structured Planner output, not an implemented Planner.
It requests Sydney, 16 December 2026, 50 guests, five services, a flexible AUD1,000
photography target, an AUD12,000 overall event limit and an explicitly supplied
AUD11,000 supplier allowance. The allowance is not inferred or automatically
deducted by Procurement. Edit the JSON to test different structured requirements.
Other event CLI options apply to the built-in request, not --request-file.

- Code checks service/date/location/capacity/minimum rating and selects up to
  three distinct offerings per service: cheap, highly rated, then balanced.
  No catalogue-price budget cutoff is applied: estimates are not confirmed quotes.
  These are enquiry priorities, not model recommendations.
- Existing mock suppliers reply through the same enquiry/submission interfaces.
  Future supplier forms can use submit_quotation_reply without changing selection.
- After all replies are terminal, one fresh school request receives every eligible
  accepted quote (at most 15), event priorities, per-service preferences/targets
  and any supplied supplier ceiling. It chooses one local index per service
  jointly and gives one brief bundle explanation. It does not select a fixed policy.
- Exact identities/amounts come from stored supplier replies. Hard service budgets
  are checked against actual quotes. Soft service targets can be exceeded using
  savings elsewhere. Code checks the selected subtotal against the smaller of an
  explicitly supplied supplier allowance and the overall event budget.
- If no feasible combination exists, no model call is made. Invalid/model failures
  return no selection. An over-ceiling model choice is blocked, never silently
  repaired by choosing a different supplier. No automatic re-prompt or Mock fallback.
- Normal successful full-event execution uses one client LLM call; existing
  transport retries and explicitly enabled --retry-failed can add attempts.
  An explicit later comparison makes a fresh decision without re-enquiring.
  No cross-event result cache is used.

The result preserves top-level quotations / selected_quotations as selected-only
Financial handoff. service_results[].data.quotation_ranking contains only the
selected item (ranking_scope="selected_only"); remaining eligible quote IDs are
unranked_quotation_ids. Alternatives are not falsely presented as LLM-ranked.
bundle_recommendation_reason is model-authored and not fact-verified.
budget_summary contains exact supplier subtotals/ceilings and
finance_review_required=true. Passing this necessary subtotal check does not
mean contingency, tax/fees or the final customer price passed Financial review.
Accepted quotation snapshots are not rewritten with the model explanation.

Integration: construct VendorProcurementManagerAgent with the raw CampusQwenClient,
compact_llm=True, joint_selection=True. Use the same activity-level
prepare_event_enquiries -> supplier submissions -> compare_event_quotations,
or procure_services. Store budgets/preferences at preparation; comparison reads the
stored event context, so later lookup fields cannot silently replace constraints.
Use the event comparison API even for one service. The optional mode cannot be
combined with policy_ranking or batch_services. Existing Agent and Mock defaults
are unchanged; --joint-selection without --live is an explicit cheapest-quote
offline fixture, not evidence of model reasoning.

Actual school latency for this joint mode remains unmeasured. One call and short
final output do not guarantee a short reasoning phase. The earlier two-call
grouped-ranking experiment failed at shortlisting; this trial instead performs
no model shortlisting and requests only final bundle choices after actual replies.

### Budget arithmetic moved out of the model

The original joint prompt failed with HTTP 502 at 60.66s. A same-input diagnostic
with max_tokens=1024 returned HTTP success at 10.92s but finish=length: all 1,024
completion tokens were reasoning and no final answer was available. The complete
workflow with max_tokens=2048 failed with response_format at 21.62s; that summary
does not expose enough metadata to prove the exact format failure. Increasing
token caps is not treated as a demonstrated speed optimization.

Code now computes the cheapest baseline, remaining supplier allowance and each
quote's extra cost / rating change against that baseline. It excludes an option
only when its amount plus every other service's minimum already exceeds the
supplied whole-event/supplier ceiling. This never creates a soft service-price
cutoff. Code enumerates the at-most-243 combinations and supplies the model with
all budget-feasible choice codes; no scoring policy or subjective ranking is used
to remove a feasible combination. If every combination fits (or no ceiling was
given), the redundant code list is omitted.

The model selects a choice code plus a short preference explanation. Code maps
each digit back to a stored quote and performs the existing exact final checks.
Older integer-list model fixtures are still accepted. The concrete priority
fixture retains 14 of 15 accepted quotes, with baseline AUD8,733, room AUD2,267
and all 62 feasible combinations. The prompt is 3,171 characters rather than
2,765: the hypothesis is less model-side budget search, not merely fewer input
characters. Actual school completion/latency for this revision remains unmeasured.

Same full-event trial, keeping the previously tested token budget:

```powershell
py -3 -m examples.shared_catalog_procurement_example --live --joint-selection --request-file examples/requests/procurement_priority_request.json --max-output-tokens 2048
```

## Earlier policy decision plus code ranking (performance baseline)

Run the complete five-service workflow:

```powershell
py -3 -m examples.shared_catalog_procurement_example --live --policy-ranking
```

This is the new trial after repeated direct-ranking failures. A single school
request classifies customer preferences into an explicit comparison policy. Code
then ranks initial estimates, enquires with the top three, and re-ranks received
supplier amounts under the same stored policy. Normal successful runs make one
client LLM call for the entire activity; transport/recovery retries may add attempts.
The LLM chooses the policy, not individual supplier order or arbitrary weights.

| Code | Policy | Price weight | Rating weight | Capacity weight |
|---|---|---:|---:|---:|
| P | Lowest price | 100 | 0 | 0 |
| Q | Highest rating | 0 | 100 | 0 |
| V | Value | 70 | 30 | 0 |
| B | Balanced | 50 | 50 | 0 |
| C | Largest capacity | 0 | 0 | 100 |

For each service and phase: price utility is min_price/price, rating utility is
rating/5, capacity utility is capacity/max_capacity. The weighted sum is a score
out of 100. Zero-price offers get price utility 1; positive-price offers get 0
if a zero-price offer exists. Equal scores use lower price, higher rating, higher
capacity and stable supplier/offer IDs as tie-breakers. Score, price source and
rating appear in the explanation. All weights/formula/version are visible in
ranking_policies and stored round context.

Hard eligibility and actual-quote budget filters remain in the existing services;
soft budget targets remain non-blocking. Historical estimates are never used as
actual second-phase prices. Financial still checks whole-event affordability.
Different per-service preferences are deduplicated and classified together in the
same one request. U means unsupported criteria: return needs_input before
supplier enquiries. Invalid output or API failure blocks; no default policy is
substituted. Supported policies cover price, rating and capacity only.

Use whole-activity procure_services/prepare_event_enquiries to get one policy
request across up to five services. Each new preparation gets a fresh decision;
existing enquiry rounds pin their policy. Pending replies and later comparisons
reuse it with no additional LLM call. Policies/rounds remain process-local, just
like the existing enquiry workflow; accepted quotes retain existing persistence.
The initial Mock path is unchanged. Opt-in Mock trial uses an explicit V fixture.

Module construction adds compact_llm=True, policy_ranking=True with the raw
CampusQwenClient (no concise adapter). policy_ranking and batch_services are
mutually exclusive. The public staged input/reply flow, maximum-five limit and
approval/deposit/booking gates stay unchanged. Jason measured successful school policy-mode runs at 1.34s and 1.00s. These
measurements validate the policy baseline, not direct supplier-selection capability.

Evidence motivating the trial: the minimal five-candidate test succeeded in
13.11s on one HTTP attempt, with 160 prompt tokens and 1,170 completion tokens,
1,166 of them reasoning. Earlier timings of 4.64s and 35.53s alone did not reveal
whether transport retries occurred. Direct concise ranking and grouped ranking
both failed at shortlisting around 60.6s with HTTP 502. These do not establish
that concurrency caused the failures, or that merely shortening prompts fixes them.

The individual/grouped modes below remain comparisons, not verified fast demos.
## Earlier individual Live comparison

Install requirements and set ELEC5620_LLM_BASE_URL (full chat-completions URL),
ELEC5620_LLM_MODEL and ELEC5620_LLM_API_KEY in the process environment. The key
stays outside the repository. The machine must reach the school API; OpenCode
configuration is not loaded automatically.

Start with a single service and its two complete business phases:

```powershell
py -3 -m examples.shared_catalog_procurement_example --live --concurrency 2 --services photography
```

Once successful, omit --services photography to measure the full five-service
workflow. Ordinary Live execution uses ConciseRankingClient when compact_llm=True
and batch_services=False. It asks the model to return local labels such as A B C,
validates them, then restores the existing compact factual response. No extra
run switch is needed. Shared Mock execution and Agent defaults are unchanged.

The model still chooses supplier order. The adapter retains price, rating,
capacity, name, referenced IDs, budgets/preferences, previous estimate references
and supplier notes. Common notes appear once. Code supplies price/rating facts as
recommendation reasons; these are factual summaries, not model-authored explanations.
Exact label count, uniqueness and membership are checked before the existing
identity/coverage/amount validation. Invalid replies fail without a Mock fallback.

Default CLI output budget uses server settings (--max-output-tokens 0 sends no
max_tokens override). No thinking extension or /no_think instruction is used by
this path. Normal output includes phase progress, status, total elapsed time,
client LLM call count and supplier prices. Internal HTTP retries are separate
from the client-call count. --verbose prints full snapshots. CLI exits nonzero
if a complete valid selection is not produced.

## Evidence and limits

- Original successful five-service Live run: 137.14s, ten client calls.
- Reconstructed two-worker schedule from those rounded logs: 50.8s shortlist plus
  86.4s comparison, totaling 137.2s. This accounts for almost all elapsed time but
  does not separate server inference, queueing or internal transport retries.
- Minimal real three-quote control: 4.64s, ranking A B C. This establishes that a
  small actual ranking can complete quickly, not that all workflow calls will.
- Same full photography shortlist input: 977 -> 652 characters after the concise
  adapter. It retains five candidates, so it is larger than the three-quote control.
- The complete concise Live workflow has not yet been measured on the school API.
  Ten small client calls remain; no full-event latency guarantee is made.

Experimental --batch-services combines all services in one request per phase.
Its school test failed at shortlisting with HTTP 502 after 60.59s and no enquiries.
It remains opt-in for comparison, but is not the current demonstration path.
The gateway explicitly rejected chat_template_kwargs as extra_forbidden; the
/no_think soft prompt also did not prevent reasoning. Neither is an optimization
prerequisite or a recommended demo setting. The 256-token cap experiment exhausted
its entire budget on reasoning; it is not the CLI default.

## Module integration

```python
from src.llm.concise_ranking import ConciseRankingClient

agent = VendorProcurementManagerAgent(
    llm=ConciseRankingClient(CampusQwenClient.from_env()),
    vendor_service=vendor_service,
    quotation_service=quotation_service,
    compact_llm=True,
    llm_concurrency=2,
)
```

The wrapper accepts individual compact table requests. Grouped requests use the
earlier JSON protocol without this wrapper. Existing injected module clients and
Agent defaults are unaffected. No public Procurement reply shape changes.

Activities still accept 1-5 distinct services. First-phase shortlists create at
most three enquiries per service; supplier replies arrive before second-phase
prompts are built. Quote comparisons use received amounts. Pending replies,
invalid rankings and failed calls block complete Financial handoff. Existing
approval/deposit/booking gates remain. Comparison can resume from accepted quotes
without re-enquiry. All enquiry/state/SQLite writes stay on the caller thread.
External requests to a shared Agent instance must still be serialized.

Optional --retry-failed retains bounded transient-only recovery after the phase
drains. Successful jobs and supplier enquiries are retained; permanent failures
and invalid rankings are not retried. The Campus transport also retries once,
so recovery can increase waiting time. Main/Mock integration remains isolated
until explicit merge and actual Live verification.
