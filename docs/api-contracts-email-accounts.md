# refraq API Contracts: Email Accounts

## 1. Purpose

This document defines the HTTP API for a site-wide **Email Account**: a saved SMTP account that an `action.email` node uses when that node executes. It defines the resource shape, list and record verbs, the test message, delivery recording, and deletion while a **Data Channel** graph still names the id.

It does not define Data Channel graphs, node execution, or run records (`docs/api-contracts-data-channel.md`). The platform does not send mail on its own.

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
| `email_account:read` | List and read Email Accounts. Controls Console Module visibility |
| `email_account:write` | Create, update, test, and delete Email Accounts |

`email_account:read` does not imply `email_account:write`. Existing custom Roles do not receive either Permission automatically. `super_admin` has both by definition. The seeded `operator` Role does not include them. A Data Channel author references an Email Account with `channel:write`; that permission does not manage the catalog. The node picker lists accounts through this read API, so seeing names also requires `email_account:read`.

A response never includes the password. `password_set` is true when a password is stored.

## 3. Resource Shape

```json
{
  "id": "eml_01HZX",
  "name": "Office mail",
  "host": "smtp.example.com",
  "port": 587,
  "encryption": "starttls",
  "username": "refraq",
  "password_set": true,
  "from": "refraq@example.com",
  "tls_skip_verify": false,
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
| `host` | Trimmed, 1 to 255 characters, no whitespace. The platform does not classify the address |
| `port` | Integer from 1 to 65535 |
| `encryption` | `none`, `starttls`, or `implicit_tls` |
| `username` | Trimmed, 1 to 200 characters, or `null` when unset |
| `password_set` | Whether a password is stored. The password is never returned |
| `from` | One mailbox, `local@domain`, with no display name. `local` and each domain label are ASCII dot-atoms |
| `tls_skip_verify` | When true, a TLS handshake accepts any server certificate. Default false. Ignored when `encryption` is `none` |
| `last_delivery_at` | Instant of the latest test or node delivery, or `null` |
| `last_delivery_ok` | Whether that delivery was accepted, or `null` before the first delivery |
| `last_delivery_error` | Short failure text, or `null` when the latest delivery succeeded or none has run |

The platform does not require TLS or authentication. A chosen `starttls` or `implicit_tls` that the server does not complete fails the delivery. The client does not fall back to cleartext. Certificate verification runs unless `tls_skip_verify` is true.

## 4. Endpoints

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `GET` | `/email-accounts` | `email_account:read` | List Email Accounts (**Offset Page**) |
| `POST` | `/email-accounts` | `email_account:write` | Create an Email Account |
| `GET` | `/email-accounts/{id}` | `email_account:read` | Read one Email Account |
| `PATCH` | `/email-accounts/{id}` | `email_account:write` | Replace account fields |
| `DELETE` | `/email-accounts/{id}` | `email_account:write` | Delete an Email Account no graph references |
| `POST` | `/email-accounts/{id}/test` | `email_account:write` | Send one fixed test message |

### 4.1 `GET /email-accounts`

Query: `q` (optional case-insensitive substring of `name`; a blank or whitespace-only value is the same as omitting it; `%` and `_` match themselves), `limit` (default 50, max 200), `offset` (default 0). Ordered by `created_at DESC`, `id DESC`. `total` counts the filtered set.

`200` `{ "items": [ … ], "total": 1 }`. Each item is the resource shape.

### 4.2 `POST /email-accounts`

```json
{
  "name": "Office mail",
  "host": "smtp.example.com",
  "port": 587,
  "encryption": "starttls",
  "username": "refraq",
  "password": "optional",
  "from": "refraq@example.com",
  "tls_skip_verify": false
}
```

`username` and `password` are optional. Omit either, or send `null`, to store none. A present password is 1 to 512 characters. `tls_skip_verify` defaults to false when omitted. `201` `{ "email_account": { … } }`.

### 4.3 `PATCH /email-accounts/{id}`

Same fields as create. Every field is optional. An omitted `password` leaves the stored password unchanged. `password: null` clears it. `username: null` clears the username. `200` `{ "email_account": { … } }`.

### 4.4 `DELETE /email-accounts/{id}`

`204` with no body when no Data Channel draft and no published version names this id from an `action.email` node. Otherwise `409` `EMAIL_ACCOUNT_IN_USE`.

### 4.5 `POST /email-accounts/{id}/test`

```json
{ "to": "ops@example.com" }
```

`to` is one mailbox, the same form as `from`. The platform sends one plain-text message with subject `refraq email test` and body `This is a test message from refraq.` The client waits at most 30 seconds.

`200`:

```json
{ "email_account": { … }, "ok": true, "error": null }
```

A timeout, a connection failure, a TLS failure, or a refused recipient is still `200`. `ok` is false and `error` is a short message. The call updates `last_delivery_at`, `last_delivery_ok`, and `last_delivery_error`. It does not change the account configuration.

## 5. Node Delivery

An `action.email` node sends one plain-text message through the selected Email Account. `to`, `subject`, and `body` are templates rendered once for that execution. `to` splits on comma and semicolon into mailboxes. The node sends nothing and fails when any address is not a mailbox, there are more than 50 recipients, `subject` is longer than 998 characters, `body` is larger than 256 KiB, the connection fails or times out, TLS does not complete as configured, or the server refuses any recipient. A refused recipient aborts before the message data is sent. That failure follows the node's `on_error`. A success output is `{ "ok": true }`. The same last-delivery fields are updated. Retrying the node sends another message. The platform does not send mail for any other reason.

## 6. Errors

| Code | HTTP | When |
| --- | --- | --- |
| `EMAIL_ACCOUNT_NOT_FOUND` | 404 | No Email Account for this id |
| `EMAIL_ACCOUNT_IN_USE` | 409 | Delete while a draft or published version references the id |
| `REQUEST_INVALID` | 422 | Unknown fields, an empty name, a host or port outside the rules, an unknown `encryption`, a mailbox that is not one address, or a password outside 1 to 512 characters |

## 7. Non-Goals

1. Cc, Bcc, HTML, attachments, and a display name on `from`.
2. One message per input item. One node execution sends one message.
3. A delivery history list. Only the latest attempt is stored.
4. Address classification, required TLS, or required authentication.
5. A platform event that sends mail without an `action.email` node.
6. Per-channel Email Account catalogs.
7. Deduplicating a retry of the node.
