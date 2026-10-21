# refraq API Contracts: Webhooks

## 1. Purpose

This document defines the HTTP API for a site-wide **Webhook**: a saved HTTPS endpoint that an `action.webhook` node calls when that node executes. It defines the resource shape, list and record verbs, the test call, delivery recording, and deletion while a **Data Channel** graph still names the id.

It does not define Data Channel graphs, node execution, or run records (`docs/api-contracts-data-channel.md`). The platform does not call a Webhook on its own.

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
| `webhook:read` | List and read Webhooks. Controls Console Module visibility |
| `webhook:write` | Create, update, test, and delete Webhooks |

`webhook:read` does not imply `webhook:write`. Existing custom Roles do not receive either Permission automatically. `super_admin` has both by definition. The seeded `operator` Role does not include them. A Data Channel author references a Webhook with `channel:write`; that permission does not manage the catalog.

A response never includes the bearer secret. `secret_set` is true when a secret is stored.

## 3. Resource Shape

```json
{
  "id": "whk_01HZX",
  "name": "On-call",
  "url": "https://hooks.example.com/refraq",
  "secret_set": true,
  "last_delivery_at": "2026-10-20T02:00:00Z",
  "last_delivery_ok": false,
  "last_delivery_error": "connection timed out",
  "created_at": "2026-10-01T02:00:00Z",
  "updated_at": "2026-10-20T02:00:00Z"
}
```

| Field | Rule |
| --- | --- |
| `id` | Opaque server-issued id, 1 to 64 characters from `[A-Za-z0-9_-]` |
| `name` | Trimmed, 1 to 200 characters, not unique |
| `url` | Absolute `https` URL, at most 2048 characters. Userinfo is refused. The host must not be a loopback, link-local, private, or cloud-metadata address. The check runs on the literal host and again on each address resolved at call time |
| `secret_set` | Whether a bearer secret is stored. The secret is sent as `Authorization: Bearer` and is never returned |
| `last_delivery_at` | Instant of the latest test or node delivery, or `null` |
| `last_delivery_ok` | Whether that delivery returned an HTTP status below 400, or `null` before the first delivery |
| `last_delivery_error` | Short failure text, or `null` when the latest delivery succeeded or none has run |

## 4. Endpoints

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `GET` | `/webhooks` | `webhook:read` | List Webhooks (**Offset Page**) |
| `POST` | `/webhooks` | `webhook:write` | Create a Webhook |
| `GET` | `/webhooks/{id}` | `webhook:read` | Read one Webhook |
| `PATCH` | `/webhooks/{id}` | `webhook:write` | Replace name, URL, or secret |
| `DELETE` | `/webhooks/{id}` | `webhook:write` | Delete a Webhook no graph references |
| `POST` | `/webhooks/{id}/test` | `webhook:write` | POST a fixed test body |

### 4.1 `GET /webhooks`

Query: `q` (optional case-insensitive substring of `name`; a blank or whitespace-only value is the same as omitting it; `%` and `_` match themselves), `limit` (default 50, max 200), `offset` (default 0). Ordered by `created_at DESC`, `id DESC`. `total` counts the filtered set.

`200` `{ "items": [ … ], "total": 1 }`. Each item is the resource shape.

### 4.2 `POST /webhooks`

```json
{ "name": "On-call", "url": "https://hooks.example.com/refraq", "secret": "optional" }
```

`secret` is optional. Omit it or send `null` to store no secret. A present secret is 1 to 512 characters. `201` `{ "webhook": { … } }`.

### 4.3 `PATCH /webhooks/{id}`

Same fields as create. All three are optional. A omitted `secret` leaves the stored secret unchanged. `secret: null` clears it. `200` `{ "webhook": { … } }`.

### 4.4 `DELETE /webhooks/{id}`

`204` with no body when no Data Channel draft and no published version names this id from an `action.webhook` node. Otherwise `409` `WEBHOOK_IN_USE`.

### 4.5 `POST /webhooks/{id}/test`

Empty body. The platform POSTs JSON `{ "event": "webhook.test", "webhook_id": "<id>" }` with `Content-Type: application/json`. A stored secret is sent as `Authorization: Bearer`. The client waits at most 30 seconds.

`200`:

```json
{ "webhook": { … }, "status_code": 204, "ok": true, "error": null }
```

A refused address, a timeout, a connection failure, or an HTTP status of 400 or higher is still `200`. `ok` is false, `error` is a short message, and `status_code` is null when no HTTP response arrived. The call updates `last_delivery_at`, `last_delivery_ok`, and `last_delivery_error`. It does not change `name`, `url`, or the secret.

## 5. Node Delivery

An `action.webhook` node POSTs the JSON value of its body template to the selected Webhook with the same client, timeout, address rules, and bearer header as the test. The node execution fails when the call is refused, times out, cannot connect, or receives an HTTP status of 400 or higher. That failure follows the node's `on_error`. The same last-delivery fields are updated. The platform does not POST for any other reason.

## 6. Errors

| Code | HTTP | When |
| --- | --- | --- |
| `WEBHOOK_NOT_FOUND` | 404 | No Webhook for this id |
| `WEBHOOK_URL_REJECTED` | 422 | The URL is not `https`, has userinfo, or names a refused address |
| `WEBHOOK_IN_USE` | 409 | Delete while a draft or published version references the id |
| `REQUEST_INVALID` | 422 | Unknown fields, an empty name, or a secret outside 1 to 512 characters |

## 7. Non-Goals

1. Custom headers, HMAC, methods other than POST, or a body other than JSON.
2. A delivery history list. Only the latest attempt is stored.
3. A platform event that calls a Webhook without an `action.webhook` node.
4. Per-channel Webhook catalogs.
