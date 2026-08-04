# refraq API Contracts: Console Navigation

## 1. Purpose

This document defines the Management Console navigation API backed by the code-seeded **Console Module** catalog.

Transport rules match `docs/api-contracts-auth.md` §2.

Related business rules: `docs/business-management-console.md`.

## 2. Concepts

- **Console Module catalog**: fixed seed in backend code (ids, groups, routes, nav permissions, i18n keys). Not writable at runtime.
- **Navigation response**: catalog entries the current User may see, grouped, already filtered by Permission.
- Labels are **i18n keys**; the frontend translates them.

## 3. `GET /console/navigation`

Purpose: return grouped side-nav entries for the current session.

- Requires: authenticated session and `console:access`
- Does **not** require per-module permissions to call the endpoint; missing module permissions simply omit those modules (and empty groups)

### Response: `200`

```json
{
  "groups": [
    {
      "id": "workbench",
      "label_key": "layout.navGroup.workbench",
      "modules": [
        {
          "id": "dashboard",
          "label_key": "layout.nav.home",
          "route": "/console"
        }
      ]
    },
    {
      "id": "admin",
      "label_key": "layout.navGroup.admin",
      "modules": [
        {
          "id": "users",
          "label_key": "users.title",
          "route": "/console/users"
        },
        {
          "id": "roles",
          "label_key": "roles.title",
          "route": "/console/roles"
        }
      ]
    },
    {
      "id": "settings",
      "label_key": "layout.navGroup.settings",
      "modules": [
        {
          "id": "settings",
          "label_key": "settings.title",
          "route": "/console/settings"
        }
      ]
    }
  ]
}
```

Rules:

- Groups with zero visible modules are omitted
- Module order and group order follow the seed catalog
- `/auth/me` does not include the navigation tree

### Errors

| Status | Condition |
| --- | --- |
| `401` | No valid session |
| `403` | Authenticated but lacking `console:access` |

## 4. Seed Catalog (this slice)

| Module id | Group | Route | Nav permission |
| --- | --- | --- | --- |
| `dashboard` | `workbench` | `/console` | `dashboard:read` |
| `users` | `admin` | `/console/users` | `users:read` |
| `roles` | `admin` | `/console/roles` | `roles:read` |
| `settings` | `settings` | `/console/settings` | `settings:read` |
