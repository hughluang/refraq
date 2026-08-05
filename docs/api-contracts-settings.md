# refraq API Contracts: Platform Settings

## 1. Purpose

This document defines the Platform Settings API for Management Console system parameters.

Transport rules match `docs/api-contracts-auth.md` §2.

Related: `docs/business-management-console.md`, `docs/adr/0002-console-navigation-catalog.md`.

## 2. Concepts

- **Env-backed Settings**: process configuration from environment (`backend/core/config.py`).
- **Settings Override**: in-process overlay for a narrow writable set; restart clears it; not a Store Backend.
- **Effective value**: override if present, otherwise env.
- Secrets (`ADMIN_SESSION_SECRET`, initial admin credentials) are never returned.

## 3. Shared Response Shape

### Platform Settings

```json
{
  "refraq_env": "dev",
  "admin_session_ttl_hours": 8,
  "admin_session_ttl_hours_source": "env",
  "admin_session_ttl_hours_default": 8
}
```

| Field | Notes |
| --- | --- |
| `refraq_env` | Read-only environment name |
| `admin_session_ttl_hours` | Effective TTL in hours |
| `admin_session_ttl_hours_source` | `env` or `override` |
| `admin_session_ttl_hours_default` | Current env/default value (ignores override) |

## 4. `GET /settings`

Purpose: read platform system parameters.

- Permission: `settings:read`

### Response: `200`

Shape in §3.

### Errors

| Status | Condition |
| --- | --- |
| `401` | No valid authentication (Session or User PAT) |
| `403` | Missing `settings:read` |

## 5. `PATCH /settings`

Purpose: set runtime overrides for writable keys.

- Permission: `settings:write`

### Request

```json
{
  "admin_session_ttl_hours": 12
}
```

Rules:

- Only `admin_session_ttl_hours` is accepted
- Value must be an integer in **1–168** inclusive
- Unknown fields are rejected (schema extra forbid)
- Changing TTL affects **only sessions created after** the patch; existing sessions keep their original `expires_at`

### Response: `200`

Updated platform settings shape (§3) with `admin_session_ttl_hours_source` = `override`.

### Errors

| Status | Condition |
| --- | --- |
| `401` | No valid authentication (Session or User PAT) |
| `403` | Missing `settings:write` |
| `422` | Validation failure (range / unknown fields) |

## 6. `DELETE /settings/override`

Purpose: clear the in-process override and fall back to env.

- Permission: `settings:write`

### Response: `200`

Platform settings shape (§3) with `admin_session_ttl_hours_source` = `env` and effective TTL equal to env/default.

### Errors

| Status | Condition |
| --- | --- |
| `401` | No valid authentication (Session or User PAT) |
| `403` | Missing `settings:write` |

## 7. Non-Goals (this slice)

- Persisting overrides to Postgres/Redis
- Syncing overrides across API replicas
- Exposing or mutating secrets / initial admin credentials via this API
- Bulk session revoke when TTL shortens
