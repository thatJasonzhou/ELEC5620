# Fresh-download Live Procurement demo (KAN-40)

The school demonstration runs freshly downloaded code and makes actual school
LLM requests. Supplier quotation replies remain simulated data. No saved model
rankings or automatic Mock fallback are used.

## Run and compare

Install requirements and set the three existing process environment variables:
ELEC5620_LLM_BASE_URL (full chat-completions URL), ELEC5620_LLM_MODEL and
ELEC5620_LLM_API_KEY. Keep the key outside the repository. The computer must be
able to reach the school API. OpenCode configuration is not loaded automatically.

Existing individual-service execution, with at most two requests in parallel:

```powershell
py -3 -m examples.shared_catalog_procurement_example --live --concurrency 2
```

New opt-in grouped execution:

```powershell
py -3 -m examples.shared_catalog_procurement_example --live --batch-services
```

Grouping sends all requested service shortlists in one model request, collects
supplier replies normally, then compares all requested services in a second
request. Each service is ranked independently, with up to three enquiries and
one proposed selection. The event still accepts 1-5 distinct service categories.
A single service retains its existing two-request protocol. The concurrency flag
controls individual-service execution; grouped execution has one request per phase.

The CLI's default output cap is now 0, meaning no max_tokens override is sent.
This restores the original successful transport setting: the later 256-token
cap was exhausted by reasoning before an answer. An explicit
--max-output-tokens value is still available, but it limits the complete generated
output, including reasoning reported by the school service. Do not use
--disable-thinking for this school endpoint: the gateway rejected its extension.
The /no_think prompt probe also did not prevent reasoning. Neither control is
part of this optimization.

Normal output stays short: phase progress, status, total elapsed time, client LLM
call count, enquiry/selection counts, and five supplier/price rows. Internal HTTP
transport retries are not included in the client-call count. Add --verbose only
for full snapshots. A received progress event means text arrived, before ranking
validation. CLI exits nonzero when no complete valid selection is produced.

Omit --live to run the explicit offline Mock. Without --batch-services the
existing Mock execution remains individual-service based. The feature branch
is isolated from teammates' main/Mock integration until Live validation and merge.

## Why group the requests

Jason's successful individual-service Live run took 137.14s. Reconstructing the
two-worker schedule from its rounded request durations gives:

- Shortlisting: 50.8s.
- Quotation comparison: 86.4s.
- Total: 137.2s, close to the observed total within log rounding.

This attributes almost all observed elapsed time to the ten client LLM jobs and
their scheduling. It does not distinguish server inference, queueing or internal
transport retries within each job. Increasing concurrency previously produced
some 61s failures, so raising concurrency alone is not assumed reliable.

On the same offline five-service shared-catalogue fixture:

| Protocol | Model calls | Total input characters |
|---|---:|---:|
| Original full prompts | 10 | 30,190 |
| Compact individual prompts | 10 | 10,670 |
| Compact grouped prompts | 2 | 6,294 |

These are call and character counts, not measured Live speedups. One grouped
request can take longer than one individual request. The Live event must succeed
and its elapsed time must be measured before choosing this mode for demonstration.

## Module integration and validation

Existing constructor defaults preserve individual-service execution. Opt in with:

```python
agent = VendorProcurementManagerAgent(
    llm=CampusQwenClient.from_env(),
    vendor_service=vendor_service,
    quotation_service=quotation_service,
    compact_llm=True,
    batch_services=True,
)
```

Grouping requires compact_llm=True. Dates, city, guest count, preferences and
phase instructions are shared only when equal. Candidate indices are local to
each service. The grouped response must name every requested service exactly
once; original per-service identity, index, coverage, reason and price validation
then applies. IDs and amounts come from stored facts. Compact basis_codes remain
empty; AI reasons are not fully fact-verified.

All enquiry creation, reply submission and SQLite writes stay on the caller
thread. Second-phase prompts are constructed only after supplier replies arrive.
Pending replies, invalid/missing rankings and failed model requests block complete
Financial handoff. Existing approval/deposit/booking gates remain. On comparison
failure, accepted replies remain available for an explicit comparison retry.
A grouped failure can affect all services in that phase; there is no automatic
split into smaller requests or switch to Mock.

Optional --retry-failed retains its existing bounded transient-only recovery:
once after the phase drains, with successful jobs and supplier enquiries retained.
Permanent failures and invalid rankings are not retried. The Campus client has
its own one-HTTP-retry policy; recovery may increase total waiting time.
External requests to a shared Agent instance must still be serialized.
