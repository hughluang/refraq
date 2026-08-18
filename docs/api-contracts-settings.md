# refraq API Contracts: Platform Settings

## 1. Purpose

This document defines the Platform Settings API that presents **System Parameter**s.

Transport rules match `docs/api-contracts-auth.md` §2.

Related: `docs/business-system-parameters.md`, `docs/adr/0028-system-parameters.md`, `docs/business-management-console.md` §5.

## 2. Concepts

- **System Parameter**: a named, site-wide key that an operator can decide from the business (`docs/business-system-parameters.md` §2.1). The stored row is what the catalog returns. Product seed occupy writes a missing row and never overwrites an operator value.
- **`source`**: `seed` until an operator writes the key, then `user`. Reset returns `source` to `seed`. Writing a value that equals the seed still makes `source` `user`.
- **Reset**: writes the seed back. It does not delete the row. The Console disables per-key reset when `source` is `seed`. `POST /settings/reset` of a seed key still records a change.
- Secrets and bootstrap credentials are never returned.

## 3. Shared Response Shape

```json
{
  "parameters": [
    {
      "key": "admin_session_ttl_hours",
      "value": 8,
      "seed": 8,
      "source": "seed",
      "constraint": { "type": "integer", "minimum": 1, "maximum": 168 },
      "group": "session",
      "operator_action_required": false,
      "label_key": "settings.parameter.admin_session_ttl_hours.label",
      "help_key": "settings.parameter.admin_session_ttl_hours.help",
      "apply_note_key": "settings.parameter.admin_session_ttl_hours.apply",
      "updated_at": "2026-08-17T09:00:00Z",
      "updated_by_user_id": null,
      "updated_by_account": null
    }
  ]
}
```

| Field | Notes |
| --- | --- |
| `key` | Stable identifier |
| `value` | Stored value. Not rewritten on read. May sit outside the current constraint; the Console flags that from `constraint` |
| `seed` | Product default restored by reset |
| `source` | `seed` or `user` |
| `constraint` | JSON Schema fragment under a closed profile: only `type`, `minimum`, `maximum`, `enum`, `pattern`, `maxLength`. `title` and `description` are unused. Type lives here; there is no top-level `value_type` |
| `group` | Console grouping (`session`, `jobs`) |
| `operator_action_required` | Whether apply needs an action outside this page |
| `label_key` / `help_key` / `apply_note_key` | i18n keys; the panel does not hard-code English |
| `updated_at` | Change Instant |
| `updated_by_user_id` / `updated_by_account` | Acting User; null for product occupy |

Items are ordered by group (`session`, `jobs`) then `key`.

### Registered keys

| Key | Seed | Constraint | Operator action | Applies |
| --- | --- | --- | --- | --- |
| `admin_session_ttl_hours` | 8 | integer 1–168 | No | New **Session**s only |
| `job_lost_detection_sec` | 60 | integer 15–3600 | No | Widen live; tighten waits `max(5, previous/3)` s before the reaper cutoff shrinks. The hidden system reaper **Scheduled Task** interval is derived from this value |

## 4. `GET /settings`

Purpose: read the catalog of System Parameters.

- Permission: `settings:read`

### Response: `200`

Shape in §3.

### Errors

| Status | Condition |
| --- | --- |
| `401` | No valid authentication (Session or User PAT) |
| `403` | Missing `settings:read` |
| `503` | Store read failed or a stored row is unreadable (`SYSTEM_PARAMETER_READ_FAILED`) |

## 5. `PATCH /settings`

Purpose: write one or more keys.

- Permission: `settings:write`

### Request

```json
{
  "values": {
    "admin_session_ttl_hours": 12
  }
}
```

Rules:

- `values` is a map of registered key → JSON scalar (integer, number, string, or bool)
- Unknown keys are rejected
- Each value must satisfy the key's declared constraint (type and bounds)
- Unknown fields on the request object are rejected (schema extra forbid)
- Empty `values` is rejected
- Validation is all-or-nothing: one invalid key writes nothing
- Changing `admin_session_ttl_hours` affects **only sessions created after** the patch
- A write that equals the seed still sets `source` to `user`

### Response: `200`

Updated catalog shape (§3).

### Errors

| Status | Problem Code | Condition |
| --- | --- | --- |
| `401` | `AUTH_UNAUTHENTICATED` | No valid authentication (Session or User PAT) |
| `403` | `AUTH_FORBIDDEN` | Missing `settings:write` |
| `422` | `REQUEST_INVALID` | Empty `values`, unknown fields, or a value that is not a JSON scalar (object, array) |
| `422` | `SYSTEM_PARAMETER_INVALID` | Unknown key, wrong JSON type for the declared constraint, or value outside the constraint |

## 6. `POST /settings/reset`

Purpose: restore seed default for one, several, or all keys.

- Permission: `settings:write`

### Request

```json
{
  "keys": ["admin_session_ttl_hours"]
}
```

Rules:

- Omit `keys`, or send an empty list, to reset every registered key
- Unknown keys are rejected
- Reset writes the seed, sets `source` to `seed`, and keeps the row (previous value and change Instant are updated)
- Reset of a key that already equals the seed still records a change and keeps `source` `seed`
- The Console disables per-key reset when `source` is `seed`; this endpoint still records that change if called

### Response: `200`

Updated catalog shape (§3).

### Errors

| Status | Problem Code | Condition |
| --- | --- | --- |
| `401` | `AUTH_UNAUTHENTICATED` | No valid authentication (Session or User PAT) |
| `403` | `AUTH_FORBIDDEN` | Missing `settings:write` |
| `422` | `REQUEST_INVALID` | Unknown fields on the request object |
| `422` | `SYSTEM_PARAMETER_INVALID` | Unknown key |

## 7. Retired surfaces

- A top-level PATCH body `{ "admin_session_ttl_hours": 12 }` (no `values` wrapper) is `REQUEST_INVALID`
- `DELETE /settings/override` is not a route (`HTTP_NOT_FOUND`)
- `job_worker_concurrency`, `beat_sync_every_sec`, `beat_max_interval_sec`, `reaper_interval_sec` — retired from the set (`docs/business-system-parameters.md` §5.2). A PATCH naming any of them is an unknown key

## 8. Non-Goals (this slice)

- An environment baseline or in-process overlay beside the store
- Exposing or mutating secrets / initial admin credentials
- Bulk session revoke when TTL shortens
- Runtime-defined keys or an admin UI to create a key
- `metadata` candidates (`catalog_fail_safe_threshold`, query timeout / max rows)
- Choice, text, bool, or secret parameter keys (intended shapes live in `docs/adr/0028-system-parameters.md`)
