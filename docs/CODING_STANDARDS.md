# Coding standards

## General

- English names in code and APIs.
- One clear responsibility per module.
- No hard-coded keys, local absolute paths, or credentials.
- Prefer small explicit functions over duplicated logic.
- Add type annotations to public Python functions and TypeScript interfaces to API data.

## Error response

```json
{
  "detail": {
    "code": "MISSING_COST_DATA",
    "message": "At least one vendor cost is required."
  }
}
```

## Backend

- Use Decimal for money; never binary float.
- Validate rates from 0 to 1.
- Round displayed and stored money to two decimal places.
- Keep provider calls behind an interface.
- Use UTC timestamps.

## Frontend

- Components do not construct backend URLs directly.
- Loading, empty, and error states must be visible.
- Do not display raw internal exceptions to users.
- Use the same labels as the shared status enums.

## Tests

- Test normal and exception behavior.
- Business-rule tests should not require network access.
- Mock AI and external services in automated tests.

