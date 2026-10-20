# ELEC5620 Stage 2 Development Rules

## Current architecture decisions

- Product: One-Person AI Event Management Company prototype.
- Frontend: React + TypeScript + Vite.
- Backend: FastAPI + Python.
- LLM: OpenAI API through `backend/src/llm/`; never call an LLM directly from React.
- Storage: SQLite where persistence is implemented; vendor catalogue and mock supplier responses use JSON.
- Business agents: Event Planner, Vendor Procurement Manager, Financial Manager and Event Operations.
- There is no independent Orchestrator/Supervisor Agent. Cross-agent coordination is implemented by application workflow/services and must not be presented as a fifth agent.
- Payment and external supplier systems are simulated for Stage 2.

These decisions supersede older Stage 1 notes that mention Campus Qwen, Streamlit or an independent Supervisor Agent.

## Implementation rules

1. Business agents inherit `AIAgent` and return structured envelopes.
2. Agents use service classes for deterministic business rules and persistence.
3. LLM transport, model configuration, retries and errors stay inside `backend/src/llm/`.
4. API and agent data uses snake_case JSON, ISO dates (`YYYY-MM-DD`), 24-hour times (`HH:MM`) and integer AUD cents.
5. Model output must be validated before it updates event state or reaches another agent.
6. Never invent vendor availability, price, capacity or ratings; vendor facts come from the catalogue.
7. API keys are loaded only from environment variables and must never be logged or committed.

## Required checks

- Backend: `python -m pytest backend/tests -q`
- Frontend: `npm run build` from `frontend/`
- Run both checks before merging a feature branch.

