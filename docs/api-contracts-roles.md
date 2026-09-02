# refraq API Contracts: Roles And Permissions

## 1. Purpose

This document defines Role management and the Permission catalog for the **Management Foundation**.

Endpoints are gated by `roles:read` and `roles:write` (catalog listing requires `roles:read`).

Transport rules match `docs/api-contracts-auth.md` §2.

## 2. Shared Response Shapes

### Role Summary

```json
{
  "id": "role_operator",
  "key": "operator",
  "name": "Operator",
  "permissions": ["console:access", "dashboard:read"],
  "locked": false,
  "user_count": 1
}
```

`locked` is `true` only for the system role `super_admin`.
For `super_admin`, `permissions` in API responses is the **effective** full Permission catalog (by identity), not the stored list.
`user_count` is the number of Users currently referencing the Role.

### Permission Catalog Entry

```json
{
  "key": "users:read",
  "description": "List and view users"
}
```

### Error Response

Same HTTP Problem Details shape as other Management Foundation APIs ([`docs/conventions-errors.md`](conventions-errors.md)).

## 3. `GET /permissions`

Purpose: return the fixed Permission catalog for Role editing UIs.

- Permission: `roles:read`

### Response: `200`

```json
{
  "items": [
    { "key": "console:access", "description": "Sign in to the Management Console" },
    { "key": "dashboard:read", "description": "View the console home" },
    { "key": "users:read", "description": "List and view users" },
    { "key": "users:write", "description": "Create users and change user status" },
    { "key": "roles:read", "description": "List roles and the permission catalog" },
    { "key": "roles:write", "description": "Create, update, and delete roles" },
    { "key": "settings:read", "description": "View platform system parameters" },
    { "key": "settings:write", "description": "Change platform system parameters" },
    { "key": "model_services:read", "description": "View Model Services and embedding purpose state" },
    { "key": "model_services:write", "description": "Create, update, test, activate, close, open, clean, rebuild, and delete Model Services" },
    { "key": "sources:read", "description": "List and view Sources (non-secret fields)" },
    { "key": "sources:write", "description": "Create, update, and hard-delete (disabled only) Sources; set secrets; run reachability tests; creating a database Source, or a mutating update of one with a missing product-default schedule kind, also inserts the product-default Scheduled Task for each missing kind (`structure`, `join_detection`)" },
    { "key": "metadata:read", "description": "Browse catalog objects, semantics, and joins" },
    { "key": "metadata:write", "description": "Write semantics and join edges" },
    { "key": "jobs:run", "description": "Enqueue and manage Jobs; manage domain Scheduled Tasks" },
    { "key": "query:run", "description": "Run controlled read-only SQL against a Source" },
    { "key": "catalog:sample", "description": "Run Catalog Sample (structured live peek) on a Catalog Object" },
    { "key": "tokens:read", "description": "List own User PAT metadata" },
    { "key": "tokens:write", "description": "Create, deactivate, restore, and soft-delete (deactivated only) own User PATs" },
    { "key": "audit:read", "description": "Read management-plane audit events" }
  ]
}
```

Catalog meanings for metadata-phase keys: `docs/business-metadata.md` §6 and `docs/business-user-tokens.md`. Platform **Job** / **Scheduled Task** permission `jobs:run`: `docs/business-jobs.md`.

## 4. `GET /roles`

Purpose: list Role records.

- Permission: `roles:read`

**Offset Page** (locked first, then `key ASC`, `id ASC`). Query params: `limit` (default **50**, max **200**), `offset` (default **0**).

### Response: `200`

```json
{
  "items": [
    {
      "id": "role_super_admin",
      "key": "super_admin",
      "name": "Super Admin",
      "permissions": [
        "console:access",
        "dashboard:read",
        "users:read",
        "users:write",
        "roles:read",
        "roles:write",
        "settings:read",
        "settings:write"
      ],
      "locked": true,
      "user_count": 1
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

## 5. `POST /roles`

Purpose: create a Role.

- Permission: `roles:write`

### Request

```json
{
  "key": "analyst",
  "name": "Analyst",
  "permissions": ["console:access", "dashboard:read"]
}
```

`key` must be a stable slug (`[a-z][a-z0-9_]*`, max 64).
`permissions` must be a subset of the catalog; duplicates are ignored; unknown keys are rejected.

### Success Response: `201`

```json
{
  "role": {
    "id": "role_analyst",
    "key": "analyst",
    "name": "Analyst",
    "permissions": ["console:access", "dashboard:read"],
    "locked": false,
    "user_count": 0
  }
}
```

### Failure Responses

`400 ROLE_INVALID_KEY` if the key format is invalid.

`400 ROLE_INVALID_PERMISSION` if any permission is outside the catalog.

`409 ROLE_KEY_DUPLICATE` if the key already exists.

## 6. `GET /roles/{id}`

Purpose: fetch one Role.

- Permission: `roles:read`

### Success Response: `200`

```json
{
  "role": {
    "id": "role_operator",
    "key": "operator",
    "name": "Operator",
    "permissions": ["console:access", "dashboard:read"],
    "locked": false,
    "user_count": 1
  }
}
```

### Failure Responses

`404 ROLE_NOT_FOUND`

## 7. `PATCH /roles/{id}`

Purpose: update display name and/or permissions.

- Permission: `roles:write`

### Request

```json
{
  "name": "Operations",
  "permissions": ["console:access", "dashboard:read", "users:read"]
}
```

Both fields are optional; omitted fields stay unchanged.
`key` cannot be changed via this endpoint.
Locked roles (`super_admin`) reject permission changes with `403 ROLE_LOCKED`.

### Success Response: `200`

```json
{
  "role": {
    "id": "role_operator",
    "key": "operator",
    "name": "Operations",
    "permissions": ["console:access", "dashboard:read", "users:read"],
    "locked": false,
    "user_count": 1
  }
}
```

### Failure Responses

`400 ROLE_INVALID_PERMISSION` if any permission is outside the catalog.

`403 ROLE_LOCKED` if the role is locked and permissions would change (name-only updates on locked roles may still be rejected for simplicity; this slice rejects any PATCH on locked roles).

`404 ROLE_NOT_FOUND`

## 8. `DELETE /roles/{id}`

Purpose: delete a Role.

- Permission: `roles:write`

### Success Response: `204`

Empty body.

### Failure Responses

`403 ROLE_LOCKED` if the role is the locked system role.

`409 ROLE_IN_USE` if any User still references the role.

`404 ROLE_NOT_FOUND`

## 9. Non-Goals for this slice

- Free-form permission strings outside the catalog
- Multi-role assignment to a User
- Hierarchical / inherited roles
