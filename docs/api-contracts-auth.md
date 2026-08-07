# refraq API Contracts: Auth

## 1. Purpose

This document defines the backend API contracts for Management Console login and session.

These contracts serve the **Management Console** and its **Management Foundation** slice of refraq. They are enabling capabilities, not the product identity.

These contracts are intentionally small:

- `POST /auth/login`
- `GET /auth/me`
- `POST /auth/logout`

## 2. Transport Rules

- Content type: `application/json`
- Authentication transport for Management Console: session cookie
- Frontend must send requests with credentials included
- Metadata foundation and automation may alternatively authenticate with **User PAT** Bearer (`docs/api-contracts-tokens.md`); protected endpoints accept Session **or** PAT
- Protected endpoints return `401` for unauthenticated requests and `403` for insufficient permission

## 3. Shared Response Shapes

### Current User Summary

```json
{
  "id": "user_001",
  "account": "root",
  "display_name": "System Admin",
  "email": null,
  "locale": "en-US",
  "role_id": "role_super_admin",
  "role_key": "super_admin",
  "role_name": "Super Admin",
  "permissions": [
    "console:access",
    "dashboard:read",
    "users:read",
    "users:write",
    "roles:read",
    "roles:write"
  ],
  "identity_source": "local"
}
```

`role_id`, `role_key`, and `role_name` are `null` when the User has no Role. Console login never returns that state because login requires `console:access`.
`email` may be `null`. `locale` is a supported Console locale code (`zh-CN`, `en-US`).

### Error Response

```json
{
  "code": "AUTH_INVALID_CREDENTIALS",
  "message": "Invalid account or password"
}
```

Fields:

- `code`: stable machine-readable error code; clients SHOULD localize UI copy by `code`
- `message`: English default fallback string; not a locale-negotiated field in this slice

## 4. `POST /auth/login`

### Request

```json
{
  "account": "root",
  "password": "secret"
}
```

### Success Response: `200`

```json
{
  "user": {
    "id": "user_001",
    "account": "root",
    "display_name": "System Admin",
    "email": null,
    "locale": "en-US",
    "role_id": "role_super_admin",
    "role_key": "super_admin",
    "role_name": "Super Admin",
    "permissions": [
      "console:access",
      "dashboard:read",
      "users:read",
      "users:write",
      "roles:read",
      "roles:write"
    ],
    "identity_source": "local"
  }
}
```

Additional behavior:

- response sets the session cookie
- backend updates `last_login_at`

### Failure Responses

`401` invalid credentials:

```json
{
  "code": "AUTH_INVALID_CREDENTIALS",
  "message": "Invalid account or password"
}
```

`403` disabled account:

```json
{
  "code": "AUTH_ACCOUNT_DISABLED",
  "message": "This account is disabled"
}
```

`403` missing console access (no role, or role without `console:access`):

```json
{
  "code": "AUTH_CONSOLE_ACCESS_REQUIRED",
  "message": "This account cannot sign in to the console"
}
```

## 5. `GET /auth/me`

Purpose:

- restore login state on page refresh
- initialize frontend auth provider
- supply permission list for route and action control

### Request

No body.
Requires a valid **Session cookie or User PAT** Bearer (`docs/api-contracts-tokens.md`).

### Success Response: `200`

Same `user` shape as login success.

### Failure Response: `401`

```json
{
  "code": "AUTH_UNAUTHENTICATED",
  "message": "Not signed in or session expired"
}
```

(`message` is a default English fallback; PAT failures may use `AUTH_PAT_INVALID` where that code is more specific.)

## 6. `POST /auth/logout`

Purpose:

- invalidate current session
- clear browser session state

### Request

No body.
If session exists, invalidate it.
If session does not exist, the endpoint may still return success.

### Success Response: `200`

```json
{
  "success": true
}
```

Additional behavior:

- backend clears session cookie

## 7. Permission Error Shape

When a logged-in user lacks permission:

Status: `403`

```json
{
  "code": "AUTH_FORBIDDEN",
  "message": "You do not have permission for this action"
}
```

## 8. Cookie Expectations

The first version should aim for:

- `HttpOnly`
- `SameSite=Lax`
- `Path=/`

Use `Secure` in environments where HTTPS is enabled.

## 9. Backend Test Minimum

The first implementation should include tests for:

- login success
- login wrong password
- login disabled account
- login without `console:access`
- `GET /auth/me` with valid session
- `GET /auth/me` without session
- logout success
- protected endpoint returns `403` for insufficient permission
