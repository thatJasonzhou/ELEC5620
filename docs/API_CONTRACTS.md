# API contracts

Base URL: `/api/v1`

## Shared endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Service readiness |
| GET | `/use-cases` | All 15 prototype Use Case entries and implementation status |

## Financial reference endpoint

### `POST /quotations/calculate`

Request:

```json
{
  "eventId": "EVT-001",
  "customerBudget": "10000.00",
  "currency": "AUD",
  "vendorCosts": [
    {
      "description": "Catering",
      "quantity": 1,
      "unitPrice": "3500.00"
    }
  ],
  "contingencyRate": "0.05",
  "taxRate": "0.10",
  "serviceFeeRate": "0.10"
}
```

Response:

```json
{
  "eventId": "EVT-001",
  "currency": "AUD",
  "vendorSubtotal": "3500.00",
  "contingencyAmount": "175.00",
  "taxAmount": "367.50",
  "estimatedEventCost": "4042.50",
  "serviceFee": "404.25",
  "totalQuotation": "4446.75",
  "withinBudget": true,
  "budgetDifference": "5553.25",
  "activity": {}
}
```

All future endpoints must use the same casing, error envelope, and shared status values.

