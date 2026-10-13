# One-Person AI Event Management Company

Stage 2 prototype for ELEC5620. The system supports one business owner with four AI-assisted domain agents across the event lifecycle.

## Agreed scope

- Four domain agents only: Planner, Vendor Procurement, Financial, and Operations.
- No independent Orchestrator Agent. A deterministic `WorkflowService` validates state changes.
- All 15 use cases have a visible entry or status.
- The main event flow is runnable end to end.
- Every major module includes at least one exception path.
- Vendor and payment integrations are simulated.
- Agent observations, decisions, and actions are visible in the UI.

## Technology

- Frontend: React, TypeScript, Vite
- Backend: Python, FastAPI, Pydantic, SQLAlchemy
- Database: SQLite
- AI integration: shared `AIService`; mock mode by default and OpenAI Responses API when configured
- Testing: pytest plus frontend type and production-build checks
- Collaboration: Jira, GitHub branches, pull requests, and GitHub Actions

## Project structure

```text
frontend/               React prototype
backend/app/agents/     Four domain agents
backend/app/api/        REST endpoints
backend/app/models/     Shared enums and database entities
backend/app/schemas/    Shared request and response contracts
backend/app/services/   Deterministic business and integration services
backend/tests/          Backend tests
docs/                   Team standards and architecture contracts
```

## Run locally

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Backend API: `http://localhost:8000`  
Interactive API documentation: `http://localhost:8000/docs`

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Frontend: `http://localhost:5173`

## AI configuration

The project runs in mock mode without an API key. To use OpenAI, copy `.env.example` to `.env` and set:

```env
AI_PROVIDER=openai
OPENAI_API_KEY=your_key
OPENAI_MODEL=a_model_available_to_your_account
```

Never put API keys in frontend code or commit them to GitHub.

## Team workflow

1. Select a Jira Story.
2. Create a branch such as `feature/FIN-4-budget-quotation`.
3. Implement only that Story using the shared contracts.
4. Add tests and run them locally.
5. Open a pull request and ask the assigned reviewer.
6. Merge only after review and passing checks.

Read [AGENTS.md](AGENTS.md) and the files in [docs](docs/) before changing shared code.

