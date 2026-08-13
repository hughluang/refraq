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
- Modules with `routes.list` null (for example `tokens`, identity-only / embedded in Account Center) are omitted from navigation even when the caller has `actions.list`; they remain in module-identities for ACL
- `/auth/me` does not include the navigation tree
- Account Center (`/console/account`) is not a Console Module; see `docs/business-account.md`

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
      "routes": { "list": "/console", "create": null, "edit": null, "show": null },
      "actions": {
        "list": "dashboard:read",
        "create": null,
        "edit": null,
        "delete": null,
        "show": null
      }
    },
    {
      "id": "users",
      "label_key": "users.title",
      "routes": {
        "list": "/console/users",
        "create": "/console/users/new",
        "edit": null,
        "show": null
      },
      "actions": {
        "list": "users:read",
        "create": "users:write",
        "edit": "users:write",
        "delete": "users:write",
        "show": null
      }
    },
    {
      "id": "roles",
      "label_key": "roles.title",
      "routes": {
        "list": "/console/roles",
        "create": "/console/roles/new",
        "edit": "/console/roles/:id",
        "show": null
      },
      "actions": {
        "list": "roles:read",
        "create": "roles:write",
        "edit": "roles:write",
        "delete": "roles:write",
        "show": null
      }
    },
    {
      "id": "catalog",
      "label_key": "catalog.title",
      "routes": {
        "list": "/console/catalog",
        "create": null,
        "edit": null,
        "show": "/console/catalog/:id"
      },
      "actions": {
        "list": "metadata:read",
        "create": null,
        "edit": "metadata:write",
        "delete": null,
        "show": "metadata:read"
      }
    },
    {
      "id": "business-domains",
      "label_key": "businessDomains.title",
      "routes": {
        "list": "/console/business-domains",
        "create": "/console/business-domains",
        "edit": "/console/business-domains",
        "show": null
      },
      "actions": {
        "list": "metadata:read",
        "create": "metadata:write",
        "edit": "metadata:write",
        "delete": "metadata:write",
        "show": null
      }
    },
    {
      "id": "settings",
      "label_key": "settings.title",
      "routes": { "list": "/console/settings", "create": null, "edit": null, "show": null },
      "actions": {
        "list": "settings:read",
        "create": null,
        "edit": "settings:write",
        "delete": null,
        "show": null
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
| `tokens` | `admin` (identity only; **not** in navigation) | `null` (no Console page; UI in Account Center) | `tokens:read` | create/edit/delete → `tokens:write`; see `docs/business-account.md` |
| `sources` | `metadata` | `/console/sources` | `sources:read` | create/edit/delete → `sources:write` |
| `catalog` | `metadata` | `/console/catalog` | `metadata:read` | edit → `metadata:write`; show → `metadata:read`; show route `/console/catalog/:id` |
| `business-domains` | `metadata` | `/console/business-domains` | `metadata:read` | create/edit/delete → `metadata:write` |
| `type-mappings` | `metadata` | `/console/type-mappings` | `metadata:read` | edit → `metadata:write` (no create/delete) |
| `jobs` | `metadata` | `/console/jobs` | `jobs:run` | — |
| `settings` | `settings` | `/console/settings` | `settings:read` | edit → `settings:write` |
