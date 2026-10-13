# Coding task template

Give this prompt to Codex together with one Jira Story:

```text
Read AGENTS.md and the relevant files in docs/ before changing code.

Implement Jira Story [KEY]: [TITLE]
Related Use Case: [UC ID]

User Story:
As a [user], I want [goal], so that [reason].

Acceptance Criteria:
1. [criterion]
2. [criterion]
3. [exception criterion]

Rules:
1. Implement only the assigned feature.
2. Do not rename shared models, fields, statuses, or public endpoints.
3. Follow the UC4 reference structure: schema -> service -> agent -> route -> UI -> tests.
4. Keep AI calls behind AIService.
5. Use deterministic code for calculations, payments, bookings, and state changes.
6. Add tests for the normal and exception paths.
7. Run relevant checks before finishing.
8. Summarise changed files and any integration impact.
```

