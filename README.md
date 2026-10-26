# EventPilot — AI Event Management Prototype

EventPilot is the ELEC5620 Stage 2 prototype. A customer describes an event in a React chat interface. The Event Planner Agent extracts structured requirements, asks focused follow-up questions, and sends a complete request to the Vendor Procurement Manager Agent. Matching vendor recommendations are then returned to the customer for confirmation.

## Implemented flow

1. Customer enters natural-language event requirements.
2. Event Planner Agent extracts event type, exact date/time, location, guests, budget and services.
3. Missing or ambiguous information is requested one item at a time.
4. Code validates the model output and applies booking gates.
5. Complete requirements are sent to the Vendor Procurement Manager Agent.
6. Vendor candidates are filtered from verified catalogue facts and up to three
   suppliers are shortlisted for each service.
7. The customer sends quote requests to shortlisted suppliers.
8. Suppliers use a separate portal to confirm availability and enter an actual price.
9. Procurement compares the received prices again and recommends one quotation
   per service; the customer still makes the final selection.
10. The customer page continues to the combined quotation, simulated deposit
    payment and booking.

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

The supplier page uses the fictional catalogue identities. Select a supplier,
review its pending requests, then send a simulated quotation or decline the
request. Interactive requests and replies are stored in
`backend/runtime/supplier_portal.sqlite3`, which is ignored by Git.

## Demo input

The merged fictional catalogue contains 51 suppliers across catering,
photography, venue, sound, decoration, videography, lighting, entertainment,
transport and event staff. The original 5 December demo remains available;
the complete expanded dataset uses Sydney or Melbourne, 16–17 December 2026,
and 50 or 80 guests. A complete original example is:

> I need a wedding in Sydney on 5 December 2026 from 3 pm to 9 pm for 80 guests. My budget is $30000 and I need catering and photography.

An expanded-services example is:

> I need a conference in Sydney on 16 December 2026 from 9 am to 5 pm for 50 guests. My budget is $100000 and I need a venue, lighting and event staff.

## API

- `GET /api/health`
- `POST /api/planner/message`
- `GET /api/events/{event_id}`
- `POST /api/events/{event_id}/quotations`
- `POST /api/events/{event_id}/quotation-selection`
- `POST /api/events/{event_id}/quotation-approval`
- `POST /api/events/{event_id}/deposit-payment`
- `POST /api/events/{event_id}/bookings`
- `GET /api/vendors`
- `GET /api/vendor/rfqs?vendor_id={vendor_id}`
- `POST /api/vendor/rfqs/{request_id}/response`
- `POST /api/vendor/reset` (clears simulated supplier cases after UI confirmation)

