# Frontend/backend API contract

## `POST /api/planner/message`

Request:

```json
{
  "event_id": "optional-existing-id",
  "message": "natural-language customer message"
}
```

The response contains the event ID, current stage, assistant reply, the six
normalised requirement groups, missing fields, progress, agent activity and any
verified vendor recommendations. The frontend must reuse `event_id` on later
messages.

## `GET /api/events/{event_id}`

Returns the current server-side event session for restoring or inspecting the
prototype state.

## `POST /api/events/{event_id}/vendor-selection`

Request:

```json
{
  "offering_ids": ["CAT-001", "PHOTO-001"]
}
```

Only offering IDs returned for that event are accepted. A successful response
moves the workflow to proposal preparation.

## Error format

FastAPI validation errors use the standard `detail` field. The React client
shows the error without silently changing local progress.
