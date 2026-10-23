# Operations minimal handoff — KAN-28

Owner: Peng Dou. This increment implements execution scheduling and progress,
not the full Operations scope. Reference: root shared-data-and-interfaces.md
sections 2, 4 and 5.3. Existing Procurement and Financial code is unchanged.

## Run

From the repository root, install requirements-dev.txt, then:

```sh
python -m examples.operations_example
python -m streamlit run ui/event_operations_ui.py
python -m pytest tests/unit/ tests/integration/ tests/e2e/ -q
```

The demo uses actual existing Procurement quotation/booking and Financial budget
code. Planner proposal, customer approval, deposit and supplier replies are MOCK.
The checked-in supplier presets currently confirm catering only; photography
works with the same input contract once Procurement supplies its confirmed result.
Do not turn the existing rejected photography scenario into a success silently.

## Connect the team UI / Supervisor

```python
from src.agents.event_operations import EventOperationsAgent
from src.services.event_operations_service import InMemoryEventOperationsService
from src.llm import MockLLMClient

# Create once per user session, not once per button click.
operations = EventOperationsAgent(MockLLMClient(), InMemoryEventOperationsService())
result = operations.generate_execution_plan({
    "event_id": event["event_id"],
    "event_date": event["event_date"],
    "proposal": approved_proposal,
    "procurement_result": successful_booking_result,
})
```

`proposal` keeps the root contract: event_id, proposal_id, status=Approved,
required_services and nonempty timeline entries (title/start_at/end_at).
Use the complete successful `confirm_bookings` envelope, including bookings,
customer_payment and requires_attention=false. A bare `get_bookings()` list is
insufficient: it cannot prove the overall booking workflow passed its gates.
The caller must supply authoritative current snapshots; this prototype has no
independent identity/approval store and is not a public authenticated API.

Response uses the existing envelope; `data.execution_plan` contains the shared
plan fields and task fields. `planned_end_time` and `delay_reason` are Operations
detail fields. `data.bookings`, `data.summary` and `data.storage` support the UI.
No existing upstream fields or interfaces are changed. `scheduled_at` maps to
OperationalTask.planned_start_time and `title` to task_name.

Tasks initially follow the approved timeline, with booking_id=null. An operator
explicitly assigns a confirmed booking to a task; the code does not infer the
supplier from a title. Add arrival, setup, service or departure tasks with explicit
times through `add_task`. Catering and photography use the same implementation.
Times must be timezone-aware and within the supplied event date for this MVP.

Other `handle` requests require event_id/proposal_id plus:

| action | additional fields |
|---|---|
| monitor_execution | none |
| assign_task | task_id, booking_id (null for an internal task) |
| add_task | title, start_at, end_at, optional booking_id |
| update_task_status | task_id, status, reason when DELAYED |

Task transitions follow the Stage 1 state diagram: NOT_STARTED → IN_PROGRESS
or DELAYED; IN_PROGRESS → DELAYED or COMPLETED; DELAYED → IN_PROGRESS or
COMPLETED. Repeating a status is allowed, but COMPLETED cannot be reopened.
Assignment changes are allowed only before a task starts; overlapping tasks for
one booking are conservatively blocked. Unrelated/internal tasks can overlap.

`summary.execution_complete` requires all tasks completed and every confirmed
booking assigned to a task. It does **not** close the Event or claim settlement,
complaint resolution, supplier departure or financial reconciliation.
If departure matters, explicitly create a departure task and record its completion.

Repeated generation preserves IDs and progress. Changed inputs for an active
event are blocked for reviewed revision, not silently overwritten.
All records are memory-only and session-local. Restart loses state. JSON download
is a review artifact, not a supported restore/checkpoint mechanism.

## Later increments

SQLite storage, reviewed revisions, automatic overdue checks, AI recovery advice,
feedback, closure, multi-day events and Supervisor/FastAPI wiring are deferred.
The inherited LLM dependency is intentionally unused in this minimal increment;
do not claim that this deterministic flow demonstrates LLM intelligence.
For frontend reuse, import `render_operations` from ui.event_operations_ui; it
does not configure the page or render at import time. The final frontend can call
the Agent directly using its own controls instead of the standalone JSON form.
