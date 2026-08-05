# refraq API Contracts: Management Audit

## 1. Purpose

Read API for **Management Audit Events** produced by metadata foundation and User PAT flows.

Business rules: `docs/business-metadata.md` §13.
Permission: `audit:read`.
Auth: Session or User PAT.

## 2. Event Shape

```json
{
  "id": "aud_01",
  "created_at": "2026-08-05T02:10:00Z",
  "actor_user_id": "user_001",
  "actor_token_id": null,
  "resource_type": "connection",
  "resource_id": "conn_mes_prod",
  "action": "secret.rotate",
  "result": "success",
  "detail": {
    "summary": "Connection secret rotated"
  }
}
```

Rules:

- `detail` must not contain plaintext secrets or full PAT secrets.
- Controlled query events may store SQL summary/hash and row truncation flags, not Connection passwords.
- `actor_token_id` set when the action was authenticated via User PAT.

## 3. Endpoints

### `GET /audit/events`

- Permission: `audit:read`
- Query filters: `resource_type`, `actor_user_id`, `from`, `to`, `action`, pagination cursors/limit

Response `200`:

```json
{
  "items": [],
  "next_cursor": null
}
```

### `GET /audit/events/{id}`

- Permission: `audit:read`
- Response: single event shape

## 4. Non-Goals

- Streaming SIEM export
- Mutualized login/Settings audit completeness in this phase
- Client-side integrity proofs
