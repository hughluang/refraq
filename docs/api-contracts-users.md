# refraq API Contracts: Users

## 1. Purpose

This document defines the User management endpoints for the **Management Console** slice. They belong to the **Management Foundation** and are gated by the `users:read` and `users:write` permissions.

These contracts complement `docs/api-contracts-auth.md` and `docs/api-contracts-roles.md`. They follow the same transport rules:

- Content type: `application/json`
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

`role_id`, `role_key`, and `role_name` may be `null` when the User has no Role.
`last_login_at` may be `null` if the User has never signed in.
`email` may be `null` (optional contact; not unique, not verified).
`locale` is a supported Console locale code; new Users default to the platform default locale unless provided.
`display_timezone` is optional IANA for Console Instant formatting (`null` = follow browser); Instant fields remain UTC `Z`.

### Error Response

```json
{
  "code": "USER_ACCOUNT_DUPLICATE",
  "message": "Account already exists"
}
```

`code` is the stable machine-readable code; clients SHOULD localize UI copy by `code`. `message` is an English default fallback string; it is not locale-negotiated in this slice.

## 3. `GET /users`

Purpose: list User records.

- Permission: `users:read`

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
  ]
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

## 6. Non-Goals for this slice

- Hard delete of User records is intentionally not exposed.
- Password reset / forgot-password flows remain out of scope (self-service password change for the current User is `docs/api-contracts-account.md`).
- LDAP sync and **Client** (machine principal) credential management are out of scope.
- **User PAT** is specified separately in `docs/api-contracts-tokens.md` / `docs/business-user-tokens.md` (not a Client API).
- Self-service profile, locale, and password for the current User are specified in `docs/api-contracts-account.md` / `docs/business-account.md`.
