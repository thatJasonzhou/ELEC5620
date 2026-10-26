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

## Shorter model requests and answers

The shared-data CLI now defaults to a compact model protocol (independent of
terminal --verbose). The model sees a small candidate table, shared event context
and the customer preferences. It returns only
`{"ranked":[[candidate_index,"short reason"],...]}`.
Reasons are requested in at most six words and validated to at most 120 characters.
Code maps indices back to the original immutable supplier/quotation snapshots,
then reuses identity/fact and phase-count validation. Invalid, repeated, missing,
boolean or out-of-range indices fail; extra output fields cannot override prices.
Compact mode emits no model-selected superlative basis codes (the existing
basis_codes field remains an empty list). Short prose remains AI-generated,
not fully fact-verified.

Catalogue names, price/rating/capacity and relevant preferences are retained.
Supplier notes/estimate references remain available at comparison. Internal batch,
event, proposal and quote IDs are not needed for the ranking task. Supplier/offer
references are additionally supplied when the preferences mention them.

On the same default photography fixture, shortlist input dropped from 3,337 to
977 characters; comparison input from 2,749 to 1,173 characters. The offline
three-item response fixture shrank from 444 to 135 characters. These are
character measurements, not tokens or measured Live speed gains.
Jason's separate "reply OK" Live baseline took 0.74s; this shows a fast response
was possible then, but does not prove other runs never queued.

CLI Live calls set max_tokens=256 by default. Use --max-output-tokens 512 to
increase the cap or 0 to omit it and use the server default. A server-reported
finish_reason=length is an explicit response_format failure, even if partial
text looks like JSON; it is never released as a successful partial ranking.
No unsupported thinking-mode switch is sent, and the underlying school model
behind the alias remains unknown.

Module integration opts in explicitly:

```python
procurement = VendorProcurementManagerAgent(
    llm=CampusQwenClient.from_env(max_output_tokens=256),
    vendor_service=vendor_service,
    quotation_service=quotation_service,
    llm_concurrency=2,
    compact_llm=True,
    retry_failed_llm=True,
)
```

Agent compact_llm defaults to False and Campus token cap defaults to None so
existing injected clients/prompts stay compatible. The shared-data example
opts in by default. No public Procurement reply shape or supplier reply seam changes.

## Bounded single-request diagnostics

Do not infer the failure cause from total elapsed time alone. A capped compact
photography run failed with response_format after 3.3s; a later uncapped run
failed with HTTP 502 after 60.69s, both before supplier enquiries. Neither run
establishes that the compact request is faster or identifies the school model.
The production client may retry internally, so total time can span two HTTP
attempts. HTTP 502 alone does not establish which upstream component failed.

Run this on the feature branch with the existing runtime environment:

```powershell
py -3 -m examples.diagnose_procurement_llm
```

It sends the exact compact photography shortlist prompt once through the existing
Campus client (at most two HTTP attempts under its normal retry policy). It prints
attempt durations/status and only allowlisted envelope metadata: finish reason,
content/reasoning character counts, and token counts when the server supplies
them. It never prints the response text, API key, endpoint or server error body.
The default cap is 256. A finish=length with detail=output_limit establishes
truncation; missing usage/reasoning fields mean unknown, not zero. This diagnostic
does not disable reasoning or assume the server supports such a parameter.

Optional isolated controls: --baseline sends only Reply with exactly OK;
--max-output-tokens 0 omits the cap. Each invocation probes one request, not a
complete event. response_received means transport/content parsing succeeded;
the ranking and procurement workflow are not validated by this probe. No Live
supplier quotation or booking is requested. Main/Mock integration is unchanged;
keep this investigation isolated until actual Live results are reviewed.

## Diagnosed reasoning budget and opt-in non-thinking probe

The single-request Live probe returned HTTP success in 2.98s, with 340 prompt
tokens, 256 completion tokens, all 256 reported as reasoning_tokens,
reasoning_chars=748, non-string content and finish=length. This establishes that
this capped request exhausted its output budget on reasoning before a final
answer. It does not prove every earlier slow request or HTTP 502 had that cause.

Qwen's official vLLM documentation describes the request extension
chat_template_kwargs={"enable_thinking": false}:
https://qwen.readthedocs.io/en/stable/deployment/vllm.html#thinking-non-thinking-modes
The extension is not standard OpenAI API and the school's backend/version/model
behind the alias is not established. Backend acceptance/effect needs a Live test.

```powershell
py -3 -m examples.diagnose_procurement_llm --disable-thinking
```

This requests non-thinking mode while keeping the same prompt and 256-token cap.
Check finish=stop, a final content string, and reasoning token/character statistics
when supplied. Missing statistics mean unknown. HTTP 400/422 or continuing reasoning
means support/effect needs further investigation. There is no silent retry with
the option removed, no automatic Mock fallback and no extraction of reasoning
text as the final ranking. Existing transport retry policy remains unchanged.

Once supported, validate actual ranking and the full five-service workflow with:

```powershell
py -3 -m examples.shared_catalog_procurement_example --live --concurrency 2 --disable-thinking
```

Module callers opt in with CampusQwenClient.from_env(enable_thinking=False).
The default is None (no extension sent); True explicitly requests thinking.
The CLI flag is also opt-in. Existing main/Mock integration remains isolated.
No non-thinking Live speed, output correctness or five-service success is yet
claimed. The previous statement about no thinking switch describes the earlier
increment; this increment adds an explicit, documented experimental option.
