# refraq API Contracts: HTTP Accounts

## 1. Purpose

This document defines the HTTP API for a site-wide **HTTP Account**: a credential an `action.http` node may reference. It defines the resource shape, list and record verbs, and deletion while a **Data Channel** graph still names the id. The account has no URL of its own.

It does not define Data Channel graphs, node execution, or run records (`docs/api-contracts-data-channel.md`, `docs/business-data-channel.md`). The platform does not send a request from an HTTP Account except from an `action.http` node.

Related boundaries:

- Business rules: `docs/business-data-channel.md`.
- Console module: `docs/api-contracts-console.md`.
- Errors and request IDs: `docs/conventions-errors.md`.
- Lists: `docs/conventions-pagination.md`.
- Instants: `docs/conventions-time.md`.

## 2. Transport And Authorization

Success bodies use JSON. Failures use RFC 9457 Problem Details. Mutations accept Session or User PAT.

| Permission | Grants |
| --- | --- |
| `http_account:read` | List and read HTTP Accounts. Controls Console Module visibility |
| `http_account:write` | Create, update, and delete HTTP Accounts |

`http_account:read` does not imply `http_account:write`. Existing custom Roles do not receive either Permission automatically. `super_admin` has both by definition. The seeded `operator` Role does not include them. A Data Channel author references an HTTP Account with `channel:write`; that permission does not manage the catalog. The node picker lists accounts through this read API, so seeing names also requires `http_account:read`.

A response never includes the bearer token, the basic password, a static header value, or a secret query value. `auth.username` is present only when `auth.type` is `basic`. Header and query entries in a response carry `name` only.

Create, update, and delete write a **Management Audit Event** with resource type `http_account` and action `http_account.create`, `http_account.update`, or `http_account.delete`. The detail holds the name, the auth type, the basic username when set, the header names, the query names, and the allowed origins. It holds no secret value. An `action.http` execution does not write one.

## 3. Resource Shape

```json
{
  "id": "hac_01HZX",
  "name": "Office API",
  "auth": { "type": "bearer" },
  "headers": [{ "name": "X-Api-Key" }],
  "query": [{ "name": "api_key" }],
  "allowed_origins": ["https://api.example.com:443"],
  "created_at": "2026-10-01T02:00:00Z",
  "updated_at": "2026-10-20T02:00:00Z"
}
```

| Field | Rule |
| --- | --- |
| `id` | Opaque server-issued id with prefix `hac_`, 1 to 64 characters from `[A-Za-z0-9_-]` |
| `name` | Trimmed, 1 to 200 characters, not unique |
| `auth` | `{ "type": "none" }`, `{ "type": "bearer" }`, or `{ "type": "basic", "username" }`. Default `none`. The token and the password are never returned |
| `headers` | Names of the static headers, in stored order. Values are never returned |
| `query` | Names of the secret query parameters, in stored order. Repeated names are kept. Values are never returned |
| `allowed_origins` | Normalized origins. Empty means any origin |

`auth` on create and update is one of three objects. `none` carries no `token`, `username`, or `password`. `bearer` carries `token` (1 to 4096 characters) and no `username` or `password`. `basic` carries `username` and `password` and no `token`. The username is 1 to 256 characters with no `:` and no control character. The password is 1 to 1024 characters.

`headers` holds at most 32 objects `{ "name", "value" }`. A name is an HTTP token of 1 to 128 characters. Compared case-insensitively, these names are refused: `authorization`, `host`, `content-length`, `transfer-encoding`, `connection`, `keep-alive`, `upgrade`, `te`, `trailer`, `proxy-authorization`, and `proxy-connection`. A value is 1 to 4096 characters and contains no CR, LF, or NUL.

`query` holds at most 32 objects `{ "name", "value" }`. Each name and each value is 1 to 2048 characters. Repeated names are kept.

`allowed_origins` holds at most 32 absolute `http` or `https` URLs with no userinfo, no query, no fragment, and no path other than empty or `/`. Each entry is stored as an origin: the scheme, the lowercase host, and the port. An omitted port is stored as 80 for `http` and 443 for `https`. A stated port from 1 to 65535 is kept. Any other port is refused. An IPv6 host is written in brackets. Empty or absent means any origin.

The account does not store a URL. It does not classify hosts.

## 4. Endpoints

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `GET` | `/http-accounts` | `http_account:read` | List HTTP Accounts (**Offset Page**) |
| `POST` | `/http-accounts` | `http_account:write` | Create an HTTP Account |
| `GET` | `/http-accounts/{id}` | `http_account:read` | Read one HTTP Account |
| `PATCH` | `/http-accounts/{id}` | `http_account:write` | Replace account fields |
| `DELETE` | `/http-accounts/{id}` | `http_account:write` | Delete an HTTP Account no graph references |

### 4.1 `GET /http-accounts`

Query: `q` (optional case-insensitive substring of `name`; a blank or whitespace-only value is the same as omitting it; `%` and `_` match themselves), `limit` (default 50, max 200), `offset` (default 0). Ordered by `created_at DESC`, `id DESC`. `total` counts the filtered set.

`200` `{ "items": [ … ], "total": 1 }`. Each item is the resource shape.

### 4.2 `POST /http-accounts`

```json
{
  "name": "Office API",
  "auth": { "type": "bearer", "token": "secret" },
  "headers": [{ "name": "X-Api-Key", "value": "secret" }],
  "query": [{ "name": "api_key", "value": "secret" }],
  "allowed_origins": ["https://api.example.com/"]
}
```

Every field except `name` is optional. An omitted `auth` stores `{ "type": "none" }`. An omitted `headers`, `query`, or `allowed_origins` stores an empty list. `201` `{ "http_account": { … } }`.

### 4.3 `PATCH /http-accounts/{id}`

Same fields as create. Every field is optional. An omitted `auth` leaves the stored auth unchanged. A present `auth` replaces the whole auth and must carry its secret when the type is `bearer` or `basic`. An omitted `headers`, `query`, or `allowed_origins` leaves that list unchanged. A present list, including an empty list, replaces the stored list. JSON `null` for `auth`, `headers`, `query`, or `allowed_origins` is `REQUEST_INVALID`. `200` `{ "http_account": { … } }`.

### 4.4 `DELETE /http-accounts/{id}`

`204` with no body when no Data Channel draft and no published version names this id from an `action.http` node. Otherwise `409` `HTTP_ACCOUNT_IN_USE`.

## 5. Errors

| Code | HTTP | When |
| --- | --- | --- |
| `HTTP_ACCOUNT_NOT_FOUND` | 404 | No HTTP Account for this id |
| `HTTP_ACCOUNT_IN_USE` | 409 | Delete while a draft or published version references the id |
| `REQUEST_INVALID` | 422 | Unknown fields, a name outside 1 to 200 characters, an auth object outside the rules above, a header or query entry outside the rules above, or an origin outside the rules above |

## 6. Non-Goals

1. A catalog test action, and last-delivery fields.
2. A URL, or a saved base URL, on the account.
3. OAuth, token refresh, client certificates, and any auth other than `none`, `bearer`, and `basic`.
4. Wildcard or suffix patterns in allowed origins.
5. Per-channel HTTP Account catalogs.
6. Refusing a private, loopback, link-local, or cloud-metadata host. That refusal stays on **Webhook**.
