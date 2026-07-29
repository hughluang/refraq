# refraq API Contracts: Auth

## 1. Purpose

This document defines the initial backend API contracts required for the first login/permission slice.

These contracts serve the **Management Console** and its **Management Foundation** slice of refraq. They are enabling capabilities, not the product identity.

These contracts are intentionally small:

- `POST /auth/login`
- `GET /auth/me`
- `POST /auth/logout`

## 2. Transport Rules

- Content type: `application/json`
- Authentication transport: session cookie
- Frontend must send requests with credentials included
- Protected endpoints return `401` for unauthenticated requests and `403` for insufficient permission

## 3. Shared Response Shapes

### Current User Summary

```json
{
  "id": "admin_001",
  "account": "root",
  "display_name": "System Admin",
  "role": "super_admin",
  "permissions": [
    "dashboard:read",
    "admins:read",
    "admins:write",
    "system:manage"
  ]
}
```

### Error Response

```json
{
  "code": "AUTH_INVALID_CREDENTIALS",
  "message": "账号或密码错误"
}
```

Fields:

- `code`: stable machine-readable error code
- `message`: user-facing message for the current locale or default language

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
    "id": "admin_001",
    "account": "root",
    "display_name": "System Admin",
    "role": "super_admin",
    "permissions": [
      "dashboard:read",
      "admins:read",
      "admins:write",
      "system:manage"
    ]
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
  "message": "账号或密码错误"
}
```

`403` disabled account:

```json
{
  "code": "AUTH_ACCOUNT_DISABLED",
  "message": "账号已被禁用"
}
```

## 5. `GET /auth/me`

Purpose:

- restore login state on page refresh
- initialize frontend auth provider
- supply permission list for route and action control

### Request

No body.
Requires a valid session cookie.

### Success Response: `200`

```json
{
  "user": {
    "id": "admin_001",
    "account": "root",
    "display_name": "System Admin",
    "role": "super_admin",
    "permissions": [
      "dashboard:read",
      "admins:read",
      "admins:write",
      "system:manage"
    ]
  }
}
```

### Failure Response: `401`

```json
{
  "code": "AUTH_UNAUTHENTICATED",
  "message": "未登录或登录已失效"
}
```

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
  "message": "无权限执行当前操作"
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
- `GET /auth/me` with valid session
- `GET /auth/me` without session
- logout success
- protected endpoint returns `403` for insufficient permission
