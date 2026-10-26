# Fresh-download Live Procurement demo (KAN-40)

The demonstration runs freshly downloaded code and makes actual school LLM
requests. Supplier quotation replies remain simulated data. No cached model
rankings or automatic Mock fallback are used.

## Current Live comparison

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
