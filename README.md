# EventPilot — AI Event Management Prototype

EventPilot is the ELEC5620 Stage 2 prototype. A customer describes an event in a React chat interface. The Event Planner Agent extracts structured requirements, asks focused follow-up questions, and sends a complete request to the Vendor Procurement Manager Agent. Matching vendor recommendations are then returned to the customer for confirmation.

## Implemented flow

1. Customer enters natural-language event requirements.
2. Event Planner Agent extracts event type, exact date/time, location, guests, budget and services.
3. Missing or ambiguous information is requested one item at a time.
4. Code validates the model output and applies booking gates.
5. Complete requirements are sent to the imported Vendor Procurement backend.
6. Vendor candidates are filtered from verified catalogue facts and ranked.
7. The React interface displays vendor options for customer confirmation.

There is no independent Orchestrator Agent. The planning workflow coordinates calls between the existing business agents.

## Repository structure

```text
frontend/             React customer chat interface
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

Open `http://localhost:5173`.

## Demo input

The imported fictional catalogue currently contains Sydney/Melbourne vendors for 5–7 December 2026 and supports catering and photography. A complete matching example is:

> I need a wedding in Sydney on 5 December 2026 from 3 pm to 9 pm for 80 guests. My budget is $30000 and I need catering and photography.

## API

- `GET /api/health`
- `POST /api/planner/message`
- `GET /api/events/{event_id}`
- `POST /api/events/{event_id}/vendor-selection`

