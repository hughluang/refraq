# refraq API Contracts: Console Navigation and Module Identity

## 1. Purpose

This document defines the Management Console navigation and module-identity APIs backed by the code-seeded **Console Module** catalog.

Transport rules match `docs/api-contracts-auth.md` §2.

Related business rules: `docs/business-management-console.md`.

## 2. Concepts

- **Console Module catalog**: fixed seed in backend code (ids, groups, routes, actions → permissions, i18n keys). Not writable at runtime.
- **Console Navigation**: catalog entries the current User may see, grouped, already filtered by `actions.list` Permission.
- **Console Module Identity**: unfiltered UX identity for every seeded module including Foundation and metadata-group modules (routes + action → permission). Used by the SPA for Refine wiring and page/feature ACL; not a second registration surface.
- Labels are **i18n keys**; the frontend translates them.
- Nav visibility permission is `actions.list` (no separate `nav_permission` field).

## 3. `GET /console/navigation`

Purpose: return grouped side-nav entries for the current session.

- Requires: authenticated User (Session or User PAT) and `console:access`
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
- Each module `route` is `routes.list` from the seed
- `/auth/me` does not include the navigation tree

### Errors

| Status | Condition |
| --- | --- |
| `401` | No valid authentication (Session or User PAT) |
| `403` | Authenticated but lacking `console:access` |

## 4. `GET /console/module-identities`

Purpose: return the full seeded Console Module Identity catalog (Foundation and metadata-group modules) for SPA routing and UX ACL.

- Requires: authenticated User (Session or User PAT) and `console:access`
- **Not** filtered by per-module permissions (contrast with navigation)
- Does **not** include group or sort fields (those remain navigation-only)

### Response: `200`

```json
{
  "modules": [
    {
      "id": "dashboard",
      "label_key": "layout.nav.home",
      "routes": { "list": "/console", "create": null, "edit": null },
      "actions": {
        "list": "dashboard:read",
        "create": null,
        "edit": null,
        "delete": null
      }
    },
    {
      "id": "users",
      "label_key": "users.title",
      "routes": {
        "list": "/console/users",
        "create": "/console/users/new",
        "edit": null
      },
      "actions": {
        "list": "users:read",
        "create": "users:write",
        "edit": "users:write",
        "delete": "users:write"
      }
    },
    {
      "id": "roles",
      "label_key": "roles.title",
      "routes": {
        "list": "/console/roles",
        "create": "/console/roles/new",
        "edit": "/console/roles/:id"
      },
      "actions": {
        "list": "roles:read",
        "create": "roles:write",
        "edit": "roles:write",
        "delete": "roles:write"
      }
    },
    {
      "id": "settings",
      "label_key": "settings.title",
      "routes": { "list": "/console/settings", "create": null, "edit": null },
      "actions": {
        "list": "settings:read",
        "create": null,
        "edit": "settings:write",
        "delete": null
      }
    }
  ]
}
```

### Errors

| Status | Condition |
| --- | --- |
| `401` | No valid authentication (Session or User PAT) |
| `403` | Authenticated but lacking `console:access` |

## 5. Seed Catalog (this slice)

| Module id | Group | `routes.list` | `actions.list` (nav) | Other actions |
| --- | --- | --- | --- | --- |
| `dashboard` | `workbench` | `/console` | `dashboard:read` | — |
| `users` | `admin` | `/console/users` | `users:read` | create/edit/delete → `users:write`; create route `/console/users/new` |
| `roles` | `admin` | `/console/roles` | `roles:read` | create/edit/delete → `roles:write`; create `/console/roles/new`; edit `/console/roles/:id` |
| `tokens` | `admin` | `/console/tokens` | `tokens:read` | create/edit/delete → `tokens:write` |
| `sources` | `metadata` | `/console/sources` | `sources:read` | create/edit/delete → `sources:write` |
| `catalog` | `metadata` | `/console/catalog` | `metadata:read` | — |
| `jobs` | `metadata` | `/console/jobs` | `jobs:run` | — |
| `settings` | `settings` | `/console/settings` | `settings:read` | edit → `settings:write` |
