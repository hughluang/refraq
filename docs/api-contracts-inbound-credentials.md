# refraq API Contracts: Inbound Credentials

## 1. Purpose

This document defines the HTTP API for a site-wide Inbound Credential: a secret a `trigger.inbound` node may name. It defines the resource shape, list and record verbs, and deletion while a **Data Channel** draft or published **Channel Version** still names the id. The credential has no URL of its own.

It does not check a presented token or signature, and it does not define Data Channel graphs or run records (`docs/api-contracts-data-channel.md`, `docs/business-data-channel.md`).

Related boundaries:

- Business rules: `docs/business-data-channel.md`.
- Errors and request IDs: `docs/conventions-errors.md`.
- Lists: `docs/conventions-pagination.md`.
- Instants: `docs/conventions-time.md`.

## 2. Transport And Authorization

Success bodies use JSON. Failures use RFC 9457 Problem Details. Mutations accept **Session** or **User PAT**.

| Permission | Grants |
| --- | --- |
| `inbound_credential:read` | List and read Inbound Credentials |
| `inbound_credential:write` | Create, update, and delete Inbound Credentials |

`inbound_credential:read` does not imply `inbound_credential:write`. Existing custom **Role**s do not receive either **Permission** automatically. `super_admin` has both by definition. The seeded `operator` Role does not include them. A **Data Channel** author names a credential from a trigger with `channel:write`; that permission does not manage the catalog. Listing names requires `inbound_credential:read`.

A response never includes the secret, a `secret` field, or a `value` field. The secret is not copied into any other field.

Create, update, and delete write one **Management Audit Event** with resource type `inbound_credential` and action `inbound_credential.create`, `inbound_credential.update`, or `inbound_credential.delete`. The detail holds `name`, `type`, and `config`. `config` holds only the non-secret fields for that type. The detail holds no secret. A validation failure, a 404, and a 409 write no event.

## 3. Resource Shape

```json
{
  "id": "icr_0123456789ab",
  "name": "Partner hook",
  "type": "token",
  "config": { "location": "header", "name": "X-Hook-Token" },
  "created_at": "2026-10-01T02:00:00Z",
  "updated_at": "2026-10-20T02:00:00Z"
}
```

| Field | Rule |
| --- | --- |
| `id` | Server-issued `icr_` plus 12 lowercase hex characters |
| `name` | Trimmed, 1 to 200 characters, not unique |
| `type` | `token` or `hmac_sha256` |
| `config` | Type-specific fields below. No secret |
| `created_at`, `updated_at` | Instants |

`type` `token` stores `config.location` `header` or `query`, and `config.name`, the header or query parameter that will carry the secret. A header name is an HTTP token of 1 to 128 characters. A query name is 1 to 2048 characters, is not blank, and contains no CR, LF, or NUL.

`type` `hmac_sha256` stores `config.signature_header` (an HTTP token of 1 to 128 characters) and `config.encoding` `hex` or `base64`. `config.prefix` and `config.timestamp_header` are optional and are configuration, not secrets. A prefix is 1 to 128 characters, is not blank, and contains no CR, LF, or NUL. A timestamp header is an HTTP token of 1 to 128 characters. An omitted optional field, or JSON `null`, is not stored and is absent from the response.

The secret is 1 to 4096 characters and is not blank. A whitespace-only secret is blank. The stored secret keeps its characters. It is encrypted before it is persisted. A response never returns it.

## 4. Endpoints

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `GET` | `/inbound-credentials` | `inbound_credential:read` | List Inbound Credentials (**Offset Page**) |
| `POST` | `/inbound-credentials` | `inbound_credential:write` | Create an Inbound Credential |
| `GET` | `/inbound-credentials/{id}` | `inbound_credential:read` | Read one Inbound Credential |
| `PATCH` | `/inbound-credentials/{id}` | `inbound_credential:write` | Replace credential fields |
| `DELETE` | `/inbound-credentials/{id}` | `inbound_credential:write` | Delete an Inbound Credential no graph names |

### 4.1 `GET /inbound-credentials`

Query: `q` (optional case-insensitive substring of `name`; a blank or whitespace-only value is the same as omitting it; `%` and `_` match themselves), `limit` (default 50, max 200), `offset` (default 0). Ordered by `created_at DESC`, `id DESC`. `total` counts the filtered set.

`200` `{ "items": [ … ], "total": 1, "limit": 50, "offset": 0 }`. Each item is the resource shape.

### 4.2 `POST /inbound-credentials`

```json
{
  "name": "Partner hook",
  "type": "token",
  "secret": "secret",
  "config": { "location": "header", "name": "X-Hook-Token" }
}
```

`name`, `type`, `secret`, and `config` are required. `config` must match `type`. `201` `{ "inbound_credential": { … } }`.

An HMAC credential sends the same envelope with `type` `hmac_sha256` and an HMAC `config`.

### 4.3 `PATCH /inbound-credentials/{id}`

Same fields as create. Every field is optional. An omitted `secret` leaves the stored secret unchanged. A present `secret` replaces it and must be 1 to 4096 characters and not blank. An omitted `config` leaves the stored config unchanged. A present `config` replaces the whole config and must match the type after this request. Changing `type` without a `config` is `REQUEST_INVALID`. JSON `null` for `secret`, `type`, or `config` is `REQUEST_INVALID`. A request that fails validation does not change the stored secret. `200` `{ "inbound_credential": { … } }`.

### 4.4 `DELETE /inbound-credentials/{id}`

`204` with no body when no Data Channel draft and no published Channel Version names this id from a `trigger.inbound` node `config.credential_id`. The node type does not have to be registered. Another node type, a `credential_id` outside `config`, or a different id does not block. Otherwise `409` `INBOUND_CREDENTIAL_IN_USE`. The credential remains.

## 5. Errors

| Code | HTTP | When |
| --- | --- | --- |
| `INBOUND_CREDENTIAL_NOT_FOUND` | 404 | No Inbound Credential for this id |
| `INBOUND_CREDENTIAL_IN_USE` | 409 | Delete while a draft or published version names the id |
| `REQUEST_INVALID` | 422 | Unknown fields, a name outside 1 to 200 characters, a type other than `token` or `hmac_sha256`, a secret outside the rules above, or a config outside the rules above |

Catalog request errors stay `REQUEST_INVALID`. There is no separate inbound problem code for a bad body.

## 6. Non-Goals

1. Verifying a presented token or HMAC signature.
2. A public request path.
3. Node execution and run records.
4. A signature algorithm other than the stored `hmac_sha256` fields.
5. A per-channel Inbound Credential catalog.
6. A scope column on the credential. The permissions are catalog keys.
