# Instructions for coding agents and contributors

Read this file and all directly relevant files in `docs/` before changing code.

## Product boundaries

- The product is the One-Person AI Event Management Company Stage 2 prototype.
- There are exactly four domain agents:
  - `EventPlannerAgent`
  - `VendorProcurementManagerAgent`
  - `FinancialManagerAgent`
  - `EventOperationsManagerAgent`
- Do not add an Orchestrator Agent, Supervisor Agent, or Event Closure Agent.
- `WorkflowService` is deterministic application code, not an AI agent.
- Vendor booking and all payments are simulated.
- AI may interpret, propose, compare, or explain. AI must not perform arithmetic, payment updates, database writes, or state transitions directly.

## Change rules

- Preserve the shared names and fields in `docs/DATA_MODELS.md`.
- Preserve public API contracts unless the task explicitly changes them.
- Use `eventId`/`event_id` as the identifier connecting modules.
- Do not place secrets in code, tests, screenshots, or commits.
- Keep changes inside the assigned module. Shared changes require an explanation in the pull request.
- Add or update tests for every behavior change.
- Update the relevant documentation when changing a contract.

## Backend conventions

- Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.
- Classes: `PascalCase`; functions and variables: `snake_case`.
- API schemas belong in `app/schemas`; deterministic logic belongs in `app/services`.
- Agents coordinate services and produce an `AgentActivity`; they do not duplicate service logic.
- Raise domain exceptions in services and translate them to HTTP errors in routes.
- Format and lint with Ruff; test with pytest.

## Frontend conventions

- React with TypeScript and functional components.
- Components and types: `PascalCase`; functions and variables: `camelCase`.
- HTTP calls belong in `src/services`, not directly inside presentation components.
- Reuse shared types and status labels.
- Format with Prettier and lint with ESLint.

## Required completion checks

- Acceptance criteria are implemented.
- Normal and exception paths are tested.
- Backend tests pass.
- Frontend builds successfully.
- No shared contract was silently renamed.
- The Jira key appears in the branch or commit message.

