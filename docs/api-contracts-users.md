# refraq API Contracts: Users

## 1. Purpose

This document defines the User management endpoints for the **Management Console** slice, including **User Group**s and **Subject Attribute**s. They belong to the **Management Foundation** and are gated by the `users:read` and `users:write` permissions. How grants and row rules consume groups and attributes is `docs/business-entity-access.md`.

These contracts complement `docs/api-contracts-auth.md` and `docs/api-contracts-roles.md`. They follow the same transport rules (`docs/api-contracts-auth.md` §2, [`docs/conventions-errors.md`](conventions-errors.md)):

- Success: `application/json`; HTTP failures: `application/problem+json`
- Authentication: Session cookie or User PAT Bearer (see `docs/api-contracts-auth.md` §2, `docs/api-contracts-tokens.md`)
- All endpoints require a valid authenticated User
- `401` is returned when authentication is missing or invalid
- `403` is returned when the caller is authenticated but lacks the required permission

The former `/admins` resource is retired; clients must use `/users`.

## 2. Shared Response Shapes

### User Summary

```json
{
  "id": "user_001",
  "account": "root",
  "display_name": "System Admin",
  "email": null,
  "locale": "en-US",
  "display_timezone": null,
  "role_id": "role_super_admin",
  "role_key": "super_admin",
  "role_name": "Super Admin",
  "status": "active",
  "identity_source": "local",
  "last_login_at": "2026-07-30T08:00:00Z"
}
```

`role_id`, `role_key`, and `role_name` may be `null` when the User has no Role. `identity_source=oidc` means the local password is unavailable.
`last_login_at` may be `null` if the User has never signed in.
`email` may be `null` (optional contact; not unique, not verified).
`locale` is a supported Console locale code; new Users default to the platform default locale unless provided.
`display_timezone` is optional IANA for Console Instant formatting (`null` = follow browser); Instant fields remain UTC `Z`.

### Error Response

HTTP failures use Problem Details ([`docs/conventions-errors.md`](conventions-errors.md)). First-party clients localize by **Problem Code** (`code`); `detail` is the English fallback.

```json
{
  "type": "urn:refraq:problem:USER_ACCOUNT_DUPLICATE",
  "status": 409,
  "detail": "Account already exists",
  "code": "USER_ACCOUNT_DUPLICATE",
  "request_id": "…"
}
```

## 3. `GET /users`

Purpose: list User records.

- Permission: `users:read`

**Offset Page** (oldest first: `created_at ASC`, `id ASC`). Query params: `limit` (default **50**, max **200**), `offset` (default **0**).

### Response: `200`

```json
{
  "items": [
    {
      "id": "user_001",
      "account": "root",
      "display_name": "System Admin",
      "email": null,
      "locale": "en-US",
      "role_id": "role_super_admin",
      "role_key": "super_admin",
      "role_name": "Super Admin",
      "status": "active",
      "identity_source": "local",
      "last_login_at": "2026-07-30T08:00:00Z"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

## 4. `POST /users`

Purpose: create a new User.

- Permission: `users:write`

### Request

```json
{
  "account": "alice",
  "display_name": "Alice",
  "email": "alice@example.com",
  "password": "initial-secret",
  "role_id": "role_operator"
}
```

`role_id` may be `null` or omitted to create a User without a Role.
`email` is optional; omit or `null` for no contact email.
`locale` may be omitted; the server applies the default supported locale.

### Success Response: `201`

```json
{
  "user": {
    "id": "user_002",
    "account": "alice",
    "display_name": "Alice",
    "email": "alice@example.com",
    "locale": "en-US",
    "role_id": "role_operator",
    "role_key": "operator",
    "role_name": "Operator",
    "status": "active",
    "identity_source": "local",
    "last_login_at": null
  }
}
```

### Failure Responses

`400 USER_INVALID_ROLE` if `role_id` is not null and does not exist.

`409 USER_ACCOUNT_DUPLICATE` if the account already exists.

## 5. `PATCH /users/{id}/status`

Purpose: enable or disable an existing User.

- Permission: `users:write`

### Request

```json
{
  "status": "disabled"
}
```

`status` must be `active` or `disabled`.

When `status` is set to `disabled`, the backend invalidates all sessions belonging to that User. Subsequent requests with a former session cookie return `401 AUTH_UNAUTHENTICATED`. Re-enabling the account does not restore those sessions; a new login is required.

### Success Response: `200`

```json
{
  "user": {
    "id": "user_002",
    "account": "alice",
    "display_name": "Alice",
    "email": "alice@example.com",
    "locale": "en-US",
    "role_id": "role_operator",
    "role_key": "operator",
    "role_name": "Operator",
    "status": "disabled",
    "identity_source": "local",
    "last_login_at": null
  }
}
```

### Failure Responses

`400 USER_INVALID_STATUS` if `status` is not `active` or `disabled`.

`403 USER_SELF_DISABLE_FORBIDDEN` if the caller tries to disable their own account.

`404 USER_NOT_FOUND` if the target User does not exist.

## 6. Pending Federated Identities

Pending identities are administrative handoff records, not Users or Identity Providers. Both endpoints require `users:write`; `users:read` does not expose external claims.

### `GET /users/pending-federated-identities`

Returns an offset page of unexpired pending records: `id`, `issuer`, `subject`, `provider_id`, `account_hint` (the derived account, used to prefill a new-User claim), `email`, `display_name`, `groups` (exact strings), `admission_reason`, `attempt_count`, `first_seen_at`, `last_attempt_at`, and the fixed `expires_at`.

### `POST /users/pending-federated-identities/{id}/claim`

Claim either an existing User or create one with a selected Role:

```json
{ "user_id": "user_002" }
```

```json
{ "create_user": { "account": "alice", "display_name": "Alice", "email": "alice@example.com", "role_id": "role_operator" } }
```

Existing-user claim changes no Role. New-user claim sets `identity_source=oidc` and no usable local password. A User with another binding cannot be claimed. The last active local `super_admin` cannot be converted. Codes include `PENDING_IDENTITY_NOT_FOUND`, `PENDING_IDENTITY_EXPIRED`, `FEDERATION_ALREADY_BOUND`, `FEDERATION_LAST_LOCAL_SUPER_ADMIN`, and `USER_ACCOUNT_DUPLICATE`.

## 7. `POST /users/{id}/unfederate`

Requires `users:write`; clears the binding, changes `identity_source` to `local`, and sets a new initial password atomically. Account Center and the User cannot call it. A missing or empty `password` fails schema validation with `422 REQUEST_INVALID` before the domain rule runs; `FEDERATION_PASSWORD_REQUIRED` is the domain-boundary guard behind it and is not reachable over HTTP. The reachable code is `FEDERATION_NOT_BOUND`.

## 8. User Groups

A **User Group** is a named set of Users that **Access Grant**s and **Access Restriction**s may name (`docs/business-entity-access.md` §2). It carries no Permission. Reads require `users:read`; writes require `users:write`. Every successful write writes a **Management Audit Event**.

```json
{
  "id": "grp_01HZX",
  "key": "east_sales",
  "name": "East sales",
  "description": null,
  "member_count": 12,
  "created_at": "2026-10-07T00:00:00Z",
  "updated_at": "2026-10-07T00:00:00Z"
}
```

`key` is `[a-z][a-z0-9_]*`, at most 63 characters, unique, and immutable. `name` is required, at most 256 characters.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/user-groups` | **Offset Page** (`key ASC`, `id ASC`); `q` matches `key` or `name` substring; `limit` default 50, max 200 |
| `POST` | `/user-groups` | Create `{ "key", "name", "description"? }` → `201 { "group" }` |
| `GET` | `/user-groups/{id}` | `{ "group" }` |
| `PATCH` | `/user-groups/{id}` | Update `name`, `description` → `{ "group" }` |
| `DELETE` | `/user-groups/{id}` | Delete the group, its memberships, and its Subject Attribute values → `204` |
| `GET` | `/user-groups/{id}/members` | **Offset Page** of User Summaries (`account ASC`, `id ASC`) |
| `PUT` | `/user-groups/{id}/members/{user_id}` | Add a member (idempotent) → `204` |
| `DELETE` | `/user-groups/{id}/members/{user_id}` | Remove a member (idempotent) → `204` |
| `GET` | `/users/{id}/groups` | The User's groups (array, `key ASC`) |
| `PUT` | `/users/{id}/groups` | Replace the User's memberships `{ "group_ids": [] }` → `{ "groups" }` |

Grants that name a deleted group grant nothing (`docs/business-entity-access.md` §2.1). Codes: `USER_GROUP_NOT_FOUND` (404), `USER_GROUP_KEY_DUPLICATE` (409), `USER_GROUP_INVALID` (422), `USER_NOT_FOUND` (404).

## 9. Subject Attributes

A **Subject Attribute** definition is a typed key whose values are set on Users and User Groups and compared by row rules (`docs/business-entity-access.md` §2.2). Reads require `users:read`; writes require `users:write`. Every successful write writes a **Management Audit Event**.

### 9.1 Definitions

```json
{
  "id": "sad_01HZX",
  "key": "regions",
  "name": "Covered regions",
  "description": null,
  "value_type": "dictionary",
  "dictionary_id": "dct_01HZX",
  "multi_value": true,
  "created_at": "2026-10-07T00:00:00Z",
  "updated_at": "2026-10-07T00:00:00Z"
}
```

`key` follows the User Group key rule and is immutable. `value_type` is `string`, `integer`, `date`, `dictionary`, or `user`, and is immutable. `dictionary_id` is required for `dictionary`, must name an existing Dictionary, is immutable, and is absent for other types. `multi_value` may change from `false` to `true` only.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/subject-attributes` | **Offset Page** (`key ASC`, `id ASC`) |
| `POST` | `/subject-attributes` | Create → `201 { "subject_attribute" }` |
| `GET` | `/subject-attributes/{id}` | `{ "subject_attribute" }` |
| `PATCH` | `/subject-attributes/{id}` | Update `name`, `description`, `multi_value` |
| `DELETE` | `/subject-attributes/{id}` | Delete the definition and all its values → `204` |

### 9.2 Values

Values are addressed per subject as a map from key to a value list.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/users/{id}/subject-attributes` | `{ "values": { "regions": ["EAST"] }, "effective": { "regions": ["EAST", "SOUTH"] } }` |
| `PUT` | `/users/{id}/subject-attributes` | Replace the User's own values `{ "values": { … } }` |
| `GET` | `/user-groups/{id}/subject-attributes` | `{ "values": { … } }` |
| `PUT` | `/user-groups/{id}/subject-attributes` | Replace the group's values `{ "values": { … } }` |

`effective` is the User's own values united with the values of every group the User belongs to. A key with no values is omitted. Each value list is non-empty and has at most 256 distinct values; a single-valued key accepts one value. A value must encode under `value_type`: a `dictionary` value must be an active code of the bound Dictionary when written, and a `user` value must name an existing User.

Codes: `SUBJECT_ATTRIBUTE_NOT_FOUND` (404), `SUBJECT_ATTRIBUTE_KEY_DUPLICATE` (409), `SUBJECT_ATTRIBUTE_INVALID` (422; unknown key in a values map, wrong value type, too many values, inactive code, unknown User, or a change to an immutable field).

## 10. Non-Goals

- Hard delete of User records is intentionally not exposed.
- Password reset / forgot-password flows remain out of scope (self-service password change for the current User is `docs/api-contracts-account.md`).
- LDAP sync, non-OIDC federation, and **Client** (machine principal) credential management are out of scope.
- **User PAT** is specified separately in `docs/api-contracts-tokens.md` / `docs/business-user-tokens.md` (not a Client API).
- Self-service profile, locale, and password for the current User are specified in `docs/api-contracts-account.md` / `docs/business-account.md`.
- Synchronizing User Groups or Subject Attributes from an Identity Provider, nested groups, and Permissions on User Groups.
