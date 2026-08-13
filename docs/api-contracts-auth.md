# refraq API Contracts: Auth

## 1. Purpose

This document defines the backend API contracts for Management Console login and session.

These contracts serve the **Management Console** and its **Management Foundation** slice of refraq. They are enabling capabilities, not the product identity.

These contracts are intentionally small:

- `POST /auth/login`
- `GET /auth/me`
- `POST /auth/logout`

## 2. Transport Rules

- Success content type: `application/json`
- HTTP **failures**: `application/problem+json` (RFC 9457). Global rules: [`docs/conventions-errors.md`](conventions-errors.md), ADR [`0023`](adr/0023-api-problem-details.md)
- Every HTTP response (success and failure) echoes `X-Request-ID`
- Authentication transport for Management Console: session cookie
- Frontend must send requests with credentials included
- Metadata foundation and automation may alternatively authenticate with **User PAT** Bearer (`docs/api-contracts-tokens.md`); protected endpoints accept Session **or** PAT
- Protected endpoints return `401` for unauthenticated requests and `403` for insufficient permission
- **Instants** on all HTTP APIs: RFC 3339 with required offset inbound; outbound UTC `Z`. Global rules: [`docs/conventions-time.md`](conventions-time.md).

## 3. Shared Response Shapes

### Current User Summary

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
`display_timezone` is an optional IANA zone for **Management Console** Instant formatting (`null` = follow browser); it does not change Instant JSON on HTTP or MCP (outbound remains UTC `Z`).

### Error Response

HTTP failures use Problem Details. First-party clients branch on **Problem Code** (`code`), not on `type`. `detail` is the English fallback; localize UI by `code`. `request_id` matches `X-Request-ID`.

```json
{
  "type": "urn:refraq:problem:AUTH_INVALID_CREDENTIALS",
  "status": 401,
  "detail": "Invalid account or password",
  "code": "AUTH_INVALID_CREDENTIALS",
  "request_id": "…"
}
```

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
  "type": "urn:refraq:problem:AUTH_INVALID_CREDENTIALS",
  "status": 401,
  "detail": "Invalid account or password",
  "code": "AUTH_INVALID_CREDENTIALS",
  "request_id": "…"
}
```

`403` disabled account:

```json
{
  "type": "urn:refraq:problem:AUTH_ACCOUNT_DISABLED",
  "status": 403,
  "detail": "This account is disabled",
  "code": "AUTH_ACCOUNT_DISABLED",
  "request_id": "…"
}
```

`403` missing console access (no role, or role without `console:access`):

```json
{
  "type": "urn:refraq:problem:AUTH_CONSOLE_ACCESS_REQUIRED",
  "status": 403,
  "detail": "This account cannot sign in to the console",
  "code": "AUTH_CONSOLE_ACCESS_REQUIRED",
  "request_id": "…"
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
  "type": "urn:refraq:problem:AUTH_UNAUTHENTICATED",
  "status": 401,
  "detail": "Not signed in or session expired",
  "code": "AUTH_UNAUTHENTICATED",
  "request_id": "…"
}
```

(`detail` is a default English fallback; PAT failures may use `AUTH_PAT_INVALID` where that code is more specific.)

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
  "type": "urn:refraq:problem:AUTH_FORBIDDEN",
  "status": 403,
  "detail": "You do not have permission for this action",
  "code": "AUTH_FORBIDDEN",
  "request_id": "…"
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
