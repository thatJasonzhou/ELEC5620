# Architecture

```text
React + TypeScript
        |
        | REST/JSON
        v
FastAPI application
  |-- EventPlannerAgent
  |-- VendorProcurementManagerAgent
  |-- FinancialManagerAgent
  |-- EventOperationsManagerAgent
  |-- WorkflowService (deterministic, not an agent)
  |-- MockVendorService
  |-- MockPaymentService
  |-- AIService
  |     |-- MockAIService
  |     `-- OpenAIService
  `-- SQLite / SQLAlchemy
```

## Responsibilities

- Routes validate transport data and map errors to HTTP responses.
- Agents coordinate one use-case-level action and create activity records.
- Services contain deterministic business rules.
- Repositories and SQLAlchemy models persist records.
- `AIService` is the only module allowed to call an AI provider.
- React displays workflow state and calls versioned REST endpoints.

## No independent orchestrator agent

`WorkflowService` validates allowed state transitions. It does not perceive, reason, generate text, or act as an AI agent. Cross-module work is performed by explicit service calls and shared records.

## Runtime AI boundary

AI can:

- interpret customer requirements;
- draft event proposals;
- compare vendor options;
- suggest recovery actions;
- summarize feedback.

Deterministic code must:

- calculate money;
- update payments and bookings;
- validate workflow transitions;
- write database records;
- prevent duplicate transactions.

