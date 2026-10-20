# EventPilot integration architecture

## Runtime flow

```text
React chat
    -> FastAPI /api/planner/message
    -> EventPlannerAgent
       -> DemoLLMClient or OpenAIResponsesClient
    -> PlannerWorkflowService
    -> VendorProcurementManagerAgent
       -> verified vendor catalogue and procurement services
    -> React vendor confirmation cards
```

The workflow service coordinates the two business agents. It is application
logic, not a fifth Agent. The backend owns the conversation state, validation,
vendor filtering and AI credentials. The browser only renders API responses and
sends customer messages or vendor selections.

## Booking gates

Vendor matching begins only after these six requirement groups are complete:

1. event type;
2. exact date, start time and end time;
3. location;
4. guest count;
5. budget;
6. requested services.

AI output is treated as a suggestion. Python validates and normalises the
structured fields before any workflow transition. Vendor facts are taken from
the imported catalogue rather than invented by the model.

## LLM modes

- `mock` is the default, clearly labelled UI demo mode. It is deterministic and
  supports offline marking and tests.
- `live` uses the OpenAI Responses API with a JSON schema. It is enabled only
  in the backend with `PLANNER_LLM_MODE=live` and `OPENAI_API_KEY`.

Conversation storage is currently in memory for a simple prototype. The
`EventSessionService` boundary allows a database implementation to replace it
without changing the React API.
