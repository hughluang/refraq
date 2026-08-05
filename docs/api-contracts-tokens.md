# refraq API Contracts: User PAT

## 1. Purpose

Contracts for **User PAT** create/list/revoke.

Business rules: `docs/business-user-tokens.md`.
Auth for these endpoints: Session cookie **or** User PAT (a PAT may revoke itself).
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

## 3. Endpoints

### `GET /tokens`

- Permission: `tokens:read`
- Returns `{ "items": [ /* metadata shapes */ ] }`

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

### `POST /tokens/{id}/revoke`

- Permission: `tokens:write`
- Response `200` with updated metadata (`revoked_at` set)

## 4. Using A PAT

```http
Authorization: Bearer rfq_pat_ab12...full-secret
```

- Invalid/expired/revoked → `401` with `AUTH_PAT_INVALID` (or equivalent stable code)
- Valid PAT with insufficient permission → `403` as usual

## 5. Auth Contract Interaction

`docs/api-contracts-auth.md` Session cookie flows remain unchanged for Console login/logout/`/auth/me`.
When a PAT is presented, `/auth/me` (if allowed) returns the same Current User Summary shape resolved from that User.
