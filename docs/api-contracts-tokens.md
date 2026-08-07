# refraq API Contracts: User PAT

## 1. Purpose

Contracts for **User PAT** create/list/deactivate/restore/soft-delete.

Business rules: `docs/business-user-tokens.md`.
Auth for these endpoints: Session cookie **or** User PAT (a PAT may deactivate or delete itself).
Permissions: `tokens:read` / `tokens:write`. Users act only on their own tokens.

## 2. Token Metadata Shape

```json
{
  "id": "pat_01",
  "name": "mcp-local",
  "prefix": "rfq_pat_ab12",
  "expires_at": "2026-11-05T00:00:00Z",
  "revoked_at": null,
  "created_at": "2026-08-05T01:00:00Z",
  "last_used_at": null
}
```

`revoked_at` is the deactivate timestamp. Soft-deleted tokens are omitted from responses; `deleted_at` is not exposed.

## 3. Endpoints

### `GET /tokens`

- Permission: `tokens:read`
- Returns `{ "items": [ /* metadata shapes */ ] }` (excludes soft-deleted)

### `POST /tokens`

- Permission: `tokens:write`

Request:

```json
{
  "name": "mcp-local",
  "expires_at": "2026-11-05T00:00:00Z"
}
```

Response `201`:

```json
{
  "token": {
    "id": "pat_01",
    "name": "mcp-local",
    "prefix": "rfq_pat_ab12",
    "expires_at": "2026-11-05T00:00:00Z",
    "revoked_at": null,
    "created_at": "2026-08-05T01:00:00Z",
    "last_used_at": null
  },
  "secret": "rfq_pat_ab12...full-secret-once-only"
}
```

`secret` appears only here.

### `POST /tokens/{id}/deactivate`

- Permission: `tokens:write`
- Sets `revoked_at` (idempotent if already deactivated)
- Soft-deleted id → `404` `TOKEN_NOT_FOUND`
- Response `200` with updated metadata

### `POST /tokens/{id}/restore`

- Permission: `tokens:write`
- Clears `revoked_at` (idempotent if already active)
- Soft-deleted id → `404` `TOKEN_NOT_FOUND`
- Response `200` with updated metadata
- Auth still fails if `expires_at` is in the past

### `DELETE /tokens/{id}`

- Permission: `tokens:write`
- Soft-delete: sets `deleted_at`; row remains in DB
- Requires the token to be deactivated (`revoked_at` set); otherwise `409` `TOKEN_NOT_DEACTIVATED`
- Already soft-deleted or unknown id → `404` `TOKEN_NOT_FOUND`
- Response `204`

## 4. Using A PAT

```http
Authorization: Bearer rfq_pat_ab12...full-secret
```

- Invalid / expired / deactivated / soft-deleted → `401` with `AUTH_PAT_INVALID` (or equivalent stable code)
- Valid PAT with insufficient permission → `403` as usual

## 5. Auth Contract Interaction

`docs/api-contracts-auth.md` Session cookie flows remain unchanged for Console login/logout/`/auth/me`.
When a PAT is presented, `/auth/me` (if allowed) returns the same Current User Summary shape resolved from that User.
