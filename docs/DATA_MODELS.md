# Shared data models

Use these names consistently in code, diagrams, Jira, and documentation.

## Core entities

- `Event`
- `EventRequirement`
- `EventProposal`
- `Vendor`
- `VendorQuotation`
- `VendorBooking`
- `EventBudget`
- `CustomerQuotation`
- `Payment`
- `OperationPlan`
- `EventChangeRequest`
- `OperationalIssue`
- `Feedback`
- `AgentActivity`

Do not introduce `EventChange`, `OperationalException`, `CustomerFeedback`, or `EventClosureAgent` as substitutes.

## Common identifiers

- API/JSON: `eventId`, `requestId`, `vendorId`, `paymentId`
- Python: `event_id`, `request_id`, `vendor_id`, `payment_id`
- Dates and times: ISO 8601
- Money: decimal values with an explicit currency; default prototype currency is AUD

## Event status

```text
DRAFT
REQUIREMENTS_DEFINED
PROPOSAL_GENERATED
PROPOSAL_APPROVED
BOOKING_CONFIRMED
PREPARING
IN_PROGRESS
COMPLETED
CLOSED
CANCELLED
```

## Payment status

```text
PENDING
PARTIALLY_PAID
PAID
FAILED
```

## Vendor booking status

```text
REQUESTED
CONFIRMED
COMPLETED
CANCELLED
```

## Agent activity envelope

```json
{
  "eventId": "EVT-001",
  "requestId": "REQ-004",
  "agent": "FinancialManagerAgent",
  "perception": "Received three accepted vendor quotations",
  "decision": "The calculated quotation is within the customer budget",
  "action": "Generated an itemised customer quotation",
  "result": "Total AUD 9,350.00",
  "createdAt": "2026-10-14T10:00:00Z"
}
```

