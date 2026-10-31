# EventPilot — AI Event Management Prototype

EventPilot is the ELEC5620 Stage 2 prototype. A customer describes an event in a React chat interface. The Event Planner Agent extracts structured requirements, asks focused follow-up questions, and prepares a timed service plan. The customer confirms that plan before Procurement contacts suppliers.

## Implemented flow

1. Customer enters natural-language event requirements.
2. Event Planner Agent extracts event type, exact date/time, location, guests, budget and services.
3. Missing or ambiguous information is requested one item at a time.
4. Code validates the model output and applies booking gates.
5. Planner creates arrival, start and end times for every service. Before confirmation, the customer can add, remove or replace services and request schedule revisions without losing unaffected details.
6. Procurement filters verified catalogue facts and shortlists suppliers.
7. For the classroom demonstration, only three shortlisted venue suppliers receive interactive portal requests. Other service categories return clearly marked Mock replies.
8. Procurement recommends one quotation per service. Finance adds the 10% service fee and 10% contingency and checks the complete combination against the customer's total budget.
9. If the combination is over budget, Finance returns the exact overage and supplier subtotal ceiling. Procurement performs one bounded reselection before returning the case to Planner.
10. The customer approves the combined quotation. The selected venue confirms the exact schedule and price in the supplier portal; other services are Mock-confirmed.
11. The prototype then creates a simulated deposit, confirms bookings and generates an Operations execution plan from the approved service schedule. The focused Operations demonstration is: the venue supplier reports a delay, Operations proposes a revised schedule, the customer accepts it, and only then can the supplier confirm arrival and complete the service. The customer view uses the current Sydney clock rather than demo time controls.
12. After every service is complete, the customer explicitly confirms that the event has finished. Operations records this acceptance and closes before Finance prepares the remaining balance. The customer then completes a simulated final payment and the event is closed as paid in full.
13. The customer may then submit one optional rating and comment. Feedback is stored with the Operations record and is not sent to suppliers.

For classroom recovery, the existing customer UI includes a hidden **Demo controls** drawer. It stores complete checkpoints across the customer session, supplier portal and Operations state, allowing the presenter to undo the previous action, restart the current stage, load an earlier stage or reset the demo without manually rebuilding every downstream record.

There is no independent Orchestrator Agent. The planning workflow coordinates calls between the existing business agents.

## Repository structure

```text
frontend/             React customer chat and supplier quotation portal
backend/src/agents/   Event Planner and Vendor Procurement agents
backend/src/services/ workflow, session and procurement services
backend/src/llm/      OpenAI and clearly marked local demo clients
backend/src/api/      FastAPI application
backend/data/         fictional vendor catalogue and mock supplier data
backend/tests/        unit and integration tests
docs/                 shared contracts and architecture notes
```

## Run locally

### Backend

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
python -m uvicorn src.api.app:app --app-dir backend --reload --port 8000
```

The backend starts in `mock` mode so the complete UI can be demonstrated without credentials. To use the real Event Planner model:

```powershell
$env:PLANNER_LLM_MODE = "live"
$env:OPENAI_API_KEY = "your-key"
$env:OPENAI_MODEL = "a-model-available-to-your-project"
```

Never put the key in React or commit it to GitHub.

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open:

- Customer page: `http://localhost:5173/`
- Supplier page: `http://localhost:5173/?view=vendor`

The supplier page uses a supplier dropdown so only one supplier's work is shown
at a time. Pending quotations and final confirmations stay in Action Required;
completed and unselected quotations are collapsed under Quotation History. Once
a supplier is booked, that supplier receives Operations controls for arrival,
delay reporting, service start and service completion.
Interactive requests and replies are stored in
`backend/runtime/supplier_portal.sqlite3`, which is ignored by Git.
Operations state is stored in the same SQLite database as Procurement.

## Demo input

The merged fictional catalogue contains 51 suppliers across catering,
photography, venue, sound, decoration, videography, lighting, entertainment,
transport and event staff. The complete expanded dataset uses Sydney or
Melbourne, 16–17 December 2026, and 50 or 80 guests. A reliable demo example is:

> I need a conference in Sydney on 16 December 2026 from 9 am to 5 pm for 50 guests. My budget is $100000 and I need a venue, lighting and event staff.

## API

- `GET /api/health`
- `POST /api/planner/message`
- `GET /api/events/{event_id}`
- `POST /api/events/{event_id}/plan-confirmation`
- `POST /api/events/{event_id}/quotations`
- `POST /api/events/{event_id}/quotation-selection`
- `POST /api/events/{event_id}/quotation-approval`
- `POST /api/events/{event_id}/deposit-payment`
- `POST /api/events/{event_id}/final-payment`
- `POST /api/events/{event_id}/feedback`
- `POST /api/events/{event_id}/bookings`
- `GET /api/operations`
- `POST /api/events/{event_id}/operations/{action}`
- `GET /api/vendors`
- `GET /api/vendor/rfqs?vendor_id={vendor_id}`
- `POST /api/vendor/rfqs/{request_id}/response`
- `GET /api/vendor/confirmations`
- `POST /api/vendor/confirmations/{confirmation_id}/response`
- `POST /api/vendor/reset` (clears simulated supplier cases after UI confirmation)

