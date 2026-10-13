# Contributing

## Branches

`main` must remain runnable. Create one branch per Jira Story:

```text
feature/PLAN-2-event-proposal
feature/VEN-7-vendor-booking
feature/FIN-4-budget-quotation
feature/OPS-12-operational-exception
fix/FIN-8-duplicate-payment
```

## Commits

Use a short Jira-prefixed message:

```text
FIN-4 Add quotation calculation
VEN-7 Handle rejected vendor booking
```

## Pull requests

Every pull request must include:

- Jira Story and Use Case ID
- Summary of the change
- Acceptance criteria completed
- Tests performed
- Screenshots for UI changes
- Any shared model or API changes

The author must not approve their own pull request. Suggested review cycle:

```text
Xiaowen -> Zhidong Zhou
Zhidong Zhou -> Hetong Wang
Hetong Wang -> Peng Dou
Peng Dou -> Clarissa Mo
Clarissa Mo -> Xiaowen
```

## Definition of Done

- Feature matches its Use Case and acceptance criteria.
- At least one normal path and one relevant exception path are tested.
- Shared models and status values are unchanged or intentionally documented.
- No secrets or machine-specific paths are committed.
- CI passes and another member reviews the pull request.
- The change is merged to `main` and the Jira Story is moved to Done.

