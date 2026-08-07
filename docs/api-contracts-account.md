# refraq API Contracts: Account Center

## 1. Purpose

Self-service endpoints for the current authenticated **User** (Account Center). No Role permission beyond authentication is required for these routes. Callers may use Session cookie or User PAT Bearer.

Business rules: `docs/business-account.md`.

Related: `docs/api-contracts-auth.md` (Current User Summary), `docs/api-contracts-tokens.md` (PAT section in the UI).

## 2. Transport

Same as other protected APIs: JSON, Session **or** PAT, `401` when unauthenticated.

## 3. `PATCH /account/profile`

Purpose: update the caller’s `display_name`, `email`, and/or `locale`.

### Request

```json
{
  "display_name": "Alice",
  "email": "alice@example.com",
  "locale": "zh-CN"
}
```

- At least one of `display_name`, `email`, `locale` must be present.
- `email` may be `null` or `""` to clear; empty string is stored as null.
- `locale` must be a supported code (`zh-CN`, `en-US`).

### Success Response: `200`

```json
{
  "user": {
    "id": "user_002",
    "account": "alice",
    "display_name": "Alice",
    "email": "alice@example.com",
    "locale": "zh-CN",
    "role_id": "role_operator",
    "role_key": "operator",
    "role_name": "Operator",
    "permissions": ["console:access", "dashboard:read"],
    "identity_source": "local"
  }
}
```

Shape matches Current User Summary (`docs/api-contracts-auth.md`) including `email` and `locale`.

### Failure Responses

| Status | Code | When |
| --- | --- | --- |
| `400` | `ACCOUNT_PROFILE_EMPTY` | No updatable fields provided |
| `400` | `ACCOUNT_INVALID_LOCALE` | `locale` not in the supported catalog |
| `400` | `ACCOUNT_INVALID_DISPLAY_NAME` | `display_name` empty or too long |
| `401` | auth codes | Missing/invalid Session or PAT |

## 4. `POST /account/password`

Purpose: change the caller’s local password.

### Request

```json
{
  "current_password": "old-secret",
  "new_password": "new-secret"
}
```

### Success Response: `200`

```json
{
  "success": true
}
```

Side effects: password hash updated; all other Sessions for this User are deleted; the **current** Session cookie remains valid.

### Failure Responses

| Status | Code | When |
| --- | --- | --- |
| `400` | `ACCOUNT_PASSWORD_NOT_LOCAL` | `identity_source` is not `local` |
| `400` | `ACCOUNT_PASSWORD_INVALID` | Current password wrong, or new password empty/invalid |
| `401` | auth codes | Unauthenticated |
| `400` | `ACCOUNT_PASSWORD_SESSION_REQUIRED` | Authenticated without a Session cookie (e.g. PAT-only); password change needs a Session for S1 |

Password change requires a valid **Session** cookie (not PAT-only) so the current session id can be retained under S1.

## 5. Non-Goals

- Forgot-password / reset links
- Email verification
- Admin changing another User’s password via this route (use future admin flows if needed)
