# refraq API Contracts: Global Variables

## 1. Purpose

This document defines the HTTP contract for the site-wide **Global Variable** list and manual delete. Node reads and writes are not HTTP; they run inside a **Channel Run**. A **Channel Variable** is a separate resource (`docs/api-contracts-data-channel.md`).

Related boundaries:

- Business rules: `docs/business-data-channel.md`
- Data Channel definitions and runs: `docs/api-contracts-data-channel.md`
- Problem Details and Problem Codes: `docs/conventions-errors.md`
- **Offset Page** lists: `docs/conventions-pagination.md`
- **Instant** wire form: `docs/conventions-time.md`
- Terminology: `docs/glossary.md`

## 2. Cross-Cutting Rules

Success responses use `application/json`. Every HTTP failure uses RFC 9457 Problem Details (`application/problem+json`) with `type` derived as `urn:refraq:problem:{CODE}`. Authentication is a Session cookie or a **User PAT** Bearer token. Unauthenticated requests return `401 AUTH_UNAUTHENTICATED`. Authenticated callers lacking the required **Permission** return `403`. Every permission in this document is `platform`-scoped.

Collection lists use the **Offset Page** envelope `{ "items", "total", "limit", "offset" }`. Instants on the wire are UTC with a `Z` suffix. Unknown fields on a request object are rejected with `422 REQUEST_INVALID`.

## 3. Resource Shape

```json
{
  "name": "lease",
  "value": { "owner": "job_01HZX" },
  "expires_at": "2026-10-12T01:00:00Z",
  "updated_at": "2026-10-12T00:00:00Z"
}
```

- `name` matches `^[A-Za-z0-9_.:-]{1,128}$`.
- `value` is JSON, at most 64 KiB encoded.
- `expires_at` is `null` when the value does not expire. An expired value is absent from this API.
- `updated_at` is the Instant of the last write.

## 4. Endpoints

### 4.1 List

`GET /channel-variables`

Permission: `channel:read`. Default `limit` 50, max 200.

```json
{ "items": [], "total": 0, "limit": 50, "offset": 0 }
```

Items are ordered by `name`. Expired values are omitted.

### 4.2 Delete

`DELETE /channel-variables/{name}`

Permission: `channel:write`. Success is `204` with no body. The delete is a **Management Audit Event** `channel.variable_delete`.

| Status | Code | When |
| --- | --- | --- |
| 404 | `CHANNEL_VARIABLE_NOT_FOUND` | No live value has this name |
| 422 | `CHANNEL_VARIABLE_NAME_INVALID` | The name does not match the name rule |

The 422 and 404 rows apply to a `{name}` bound as one path segment. A URL whose decoded path contains `/` in the name position is not this operation; an unmatched route is `HTTP_NOT_FOUND`. A trailing slash resolves to the collection, which does not allow `DELETE`, and that is `HTTP_METHOD_NOT_ALLOWED`.

## 5. Non-Goals

1. Creating or editing a value over HTTP. Nodes write values.
2. A per-channel namespace on this site-wide resource. A **Channel Variable** is a separate resource.
3. Background deletion of expired rows.
