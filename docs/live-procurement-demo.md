# Fresh-download live Procurement demo (KAN-40)

The demonstration must run submitted code after a fresh download.
The shared catalogue example makes fresh model calls when `--live` is selected;
it does not load saved rankings or precomputed model results.

## Setup on the demonstration computer

1. Download the submitted repository, open a terminal in its root, and install requirements:
   `py -3 -m pip install -r requirements.txt`.
2. Set `ELEC5620_LLM_BASE_URL` (full chat-completions URL),
   `ELEC5620_LLM_MODEL` and `ELEC5620_LLM_API_KEY` in that process environment.
   Use actual school values; no credentials or local OpenCode configuration are bundled.
3. Ensure that computer can reach the school API (including school network/VPN if required).
4. Run:

```powershell
py -3 -m examples.shared_catalog_procurement_example --live --concurrency 3
```

The CLI now defaults to three concurrent calls per stage; `--concurrency 1` is
serial and `--concurrency 5` permits five. Supplier quotes and final responses
remain explicit simulated data; the LLM performs live recommendation/comparison.
Choose 1-5 services with `--services` as before.

Default progress announces each stage once and then reports each response.
Verbose mode also reports every submission. Progress goes to stderr, e.g. `[shortlist] photography: submitted`, then
`received (13.5s)` or `error`; `submitted` includes queued work.
The comparison stage appears after all shortlists and mock replies are ready.
`received` only means model text arrived; the usual output validation still follows.
The default stdout view is a short summary: mode, status, total elapsed time,
enquiry/selection counts and one row per selected supplier/price. A normal five-service
run prints nine result lines plus at most twelve progress lines.
Add `--verbose` only when full diagnostic JSON is needed; it includes `llm_mode`,
`supplier_source`, `llm_concurrency`, `elapsed_seconds` and full quotation/service snapshots.
CLI exits nonzero if a complete valid selection was not obtained.

## Implementation and team integration

```python
procurement = VendorProcurementManagerAgent(
    llm=CampusQwenClient.from_env(),
    vendor_service=vendor_service,
    quotation_service=quotation_service,
    llm_concurrency=3,
    progress_callback=on_progress,  # optional callable(event)
)
result = procurement.procure_services(request)
```

The Agent defaults to **1** for backward compatibility with sequential/custom clients.
The demo explicitly selects **3**. Set the keyword in team integration to opt in.
Only `llm.complete(messages)` enters worker threads. Catalogue/snapshot preparation,
round creation, reply mutation, SQLite persistence, validation and final aggregation
stay on the caller thread. Returned services remain in request order even when
responses complete in a different order.

The existing single-service and staged APIs still work. Parallelization applies
within the two activity-level stages; it does not run whole Agent/HTTP requests
concurrently, relax the five-service limit, or bypass financial/approval/booking gates.
The injected client must support concurrent `complete()` calls (the stateless
Campus client does); scripted response queues should stay serial or use a
prompt-based callable fixture. External requests to the same prototype Agent remain serialized.

Progress callbacks run on the caller thread with:
`stage` (shortlist/comparison), `service_type`, `state` (submitted/received/error),
and terminal `elapsed_seconds`. They contain no prompt, URL, key or model response.
Callbacks should return quickly and must not raise. Team frontend/backend code
can forward these events using its chosen transport; this change adds no SSE/WebSocket/UI endpoint.

A failed model call keeps that service failed and blocks complete financial handoff;
valid other snapshots remain available. It does not silently use Mock. After comparison
failure, the caller may explicitly rerun `compare_event_quotations(batch_ref)` on the
same instance to compare saved replies again; the provider is not re-enquired.
Initial shortlist failure needs a fresh preparation attempt. There is no cached live result.

## Performance validation

There are still ten normal LLM requests for five services (five per phase).
Parallelism overlaps independent network waiting; it does not guarantee faster
server inference or reduce request/token consumption. A queued/rate-limited school
server can negate the gain. Existing transport retries/timeouts remain unchanged.

On the demonstration network compare `--concurrency 1`, `3` and `5`,
checking both `elapsed_seconds` and successful complete output. Select the best
stable limit before presentation. Each run is fresh and may choose different suppliers.
Offline tests prove overlap with synchronization barriers, enforce a three-worker cap,
verify caller-thread state/SQLite writes and serial/parallel selection parity.
They do not claim a measured live school-server speedup.

## Diagnosing intermittent failures under load

A real three-way run completed shortlisting but two comparison calls failed
after about 61 seconds (90.08 seconds total). This is compatible with timeout,
network or proxy/server faults, but duration alone does not identify the cause.
Progress and failed service snapshots now expose a safe error code
(timeout, network, authentication, rate_limit, http_error, response_format,
or llm_error), plus an HTTP status where known. Raw exception reasons/URLs,
response bodies and credentials are not copied into these diagnostics.

Try a lower limit and optionally enable one bounded recovery pass:

```powershell
py -3 -m examples.shared_catalog_procurement_example --live --concurrency 2 --retry-failed
```

The corresponding Agent keyword is `retry_failed_llm=True` (default False).
Only explicitly transient failed model jobs are retried once, serially, after
the phase's first pass has fully drained. Successful jobs and supplier enquiries
are not repeated. Authentication/configuration/unknown failures and invalid
model rankings are not retried by this recovery feature. The existing Campus
transport already retries once internally; enabling recovery permits at most
two client calls (up to four HTTP attempts) per transiently failing job.
This may improve completion reliability at the cost of extra waiting, not a
guaranteed latency improvement. A second failure still blocks complete selection.
Progress may add retrying and terminal events, but never dumps nested snapshots
unless --verbose is requested. Compare school-server results before choosing a
presentation setting; neither three-way nor two-way stability is assumed.
