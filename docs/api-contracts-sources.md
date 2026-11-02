# refraq API Contracts: Sources

## 1. Purpose

HTTP contracts for **Source** management (metadata foundation slice A+), including embedded reachability and credentials for `kind=database`.

Business rules: `docs/business-metadata.md` §6.
Transport: success `application/json`; HTTP failures `application/problem+json` ([`docs/conventions-errors.md`](conventions-errors.md)). Authentication: Session cookie **or** User PAT Bearer (`docs/api-contracts-auth.md`, `docs/api-contracts-tokens.md`).
`401` unauthenticated; `403` missing permission.

## 2. Shared Shapes

### Source (read projection)

```json
{
  "id": "src_mes_prod",
  "key": "mes-prod",
  "name": "MES production",
  "kind": "database",
  "status": "active",
  "description": null,
  "engine": "oracle",
  "access": {
    "host": "db.example.internal",
    "port": 1521,
    "username": "meta_reader",
    "ssl_mode": "disable",
    "service_name": "MES",
    "owner": "MES_APP",
    "extra": {}
  },
  "has_access": true,
  "access_updated_at": "2026-08-05T01:00:00Z"
}
```

Slice A accepts `kind` = `database` only. Other kind values are reserved for later phases.
For `kind=database`: `engine` and `access` are required on create. Catalog scope lives **inside** `access` as engine-dialect keys (ADR 0021). Every engine must pin scope to the schema/owner dimension so object names are unique within the Source:
- PostgreSQL: required `database` and `schema`
- MSSQL: required `database` and `schema`
- Oracle: required `service_name` and `owner`
`access` is a per-engine JSON document validated against the **Connector Spec** (`additionalProperties` forbidden at the root; `extra` may allow string KV). Secrets (fields marked `x-secret` in the Spec, e.g. `password`) live **inside** `access`. At rest the whole document is application-encrypted; there is no separate secret column.
Slice A engines: `postgresql`, `mssql`, `oracle`. PostgreSQL Spec allows full TLS modes; mssql/oracle Specs accept `ssl_mode=disable` only until those connectors wire TLS.

**Read projection:** list/get/`SourceOut` decrypt then **strip** every `x-secret` property before returning `access`. Decrypt failure surfaces as `SOURCE_SECRET_REQUIRED` (does not silently null `access` while `has_access` stays true). Non-secret fields (host, port, username, ssl_mode, dialect scope keys, extra, …) remain.
**Write/edit full tree:** `GET /sources/{id}/access` (`sources:write`) returns the decrypted document including secrets.
For non-database kinds (future), `engine` / `access` may be absent.

### Error

HTTP protocol failures use Problem Details ([`docs/conventions-errors.md`](conventions-errors.md)):

```json
{
  "type": "urn:refraq:problem:SOURCE_ACCESS_REQUIRED",
  "status": 400,
  "detail": "A database source requires engine and access",
  "code": "SOURCE_ACCESS_REQUIRED",
  "request_id": "…"
}
```

Source probe completed-failure remains HTTP 200 `{ "ok": false, "code", "message" }` (result document; not Problem Details).

## 3. Source Endpoints

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `GET` | `/sources` | `sources:read` or `sources:access_manage` | List Sources the caller can open, plus identity rows for `sources:access_manage` (**Offset Page**; optional `q`, `engine`) |
| `GET` | `/sources/access-schema/{engine}` | `sources:read` | Connector Spec (JSON Schema) for SpecTree + validation |
| `POST` | `/sources` | `sources:write` | Create (database kind requires engine + full `access` including secrets and dialect scope) |
| `GET` | `/sources/{id}` | `sources:read` | Get (projected `access`) |
| `GET` | `/sources/{id}/access` | `sources:write` | Decrypted full `access` tree for edit |
| `PATCH` | `/sources/{id}` | `sources:write` | Update fields / status / replace full `access`; may seed missing product-default schedules |
| `DELETE` | `/sources/{id}` | `sources:write` | Hard-delete a **disabled** Source (and its catalog) |
| `POST` | `/sources/test` | `sources:write` | Reachability probe for a draft Source (not persisted) |
| `POST` | `/sources/{id}/test` | `sources:write` | Reachability probe for a stored Source |

There is **no** `PUT /sources/{id}/secret`. Credential changes are a full `access` replace via create/patch (or probe override).

Instance checks follow the Role check (`docs/business-metadata.md` §6.1). A missing Role key is `403` `AUTH_FORBIDDEN` before the id is resolved. No **Source Access Level** on that Source is `404` `SOURCE_NOT_FOUND`, the same code as an unknown id. A level that does not include the route's key is `403` `AUTH_FORBIDDEN`. `sources:access_manage` does not pass an instance check. `POST /sources`, draft `POST /sources/test`, and `GET /sources/access-schema/{engine}` use only the Role key in the table.

A successful `POST /sources` writes a `user` **Source Membership** for the creator at `maintainer` in the same transaction as the Source and its seed schedules, and writes `source_membership.create`. Hard-delete removes memberships whose target is that Source id. Every-Source memberships remain. `SOURCE_NOT_DISABLED` is returned only after the level check passes.

### `GET /sources`

**Offset Page** (`key ASC`, `id ASC`). Query params: `limit` (default **100**, max **500**), `offset` (default **0**), optional `q`, optional `engine`.

`q` is a case-insensitive substring of `key`, `name`, or `locator_key`. A blank or whitespace-only `q` is the same as omitting it. `%` and `_` match themselves. `engine`, when present, is an exact match of a supported engine code (`postgresql`, `mssql`, `oracle`). Any other value is `422 REQUEST_INVALID`. It combines with `q`. `total` counts the filtered set. Ordering and the envelope are unchanged.

Response: `{ "items": […], "total": N, "limit": L, "offset": O }`. The page is filtered before pagination. An empty visible set is an empty page.

A row the caller has a level on uses the projected Source shape. A row included only because the caller holds `sources:access_manage`, and on which the caller has no level, is an identity object: `id`, `key`, `name`, `kind`, `engine`, `status`. It omits `locator_key`, `description`, `access`, `has_access`, and `access_updated_at`.

### `GET /sources/access-schema/{engine}`

Returns `{ "engine": "postgresql", "schema": { … JSON Schema … } }` with `x-secret` markers on sensitive properties. Spec is the single source of truth for API validation and Console SpecTree. Unsupported engine → `SOURCE_ENGINE_UNSUPPORTED`.

### `POST /sources` body

```json
{
  "key": "mes-prod",
  "name": "MES production",
  "kind": "database",
  "description": null,
  "engine": "oracle",
  "access": {
    "host": "db.example.internal",
    "port": 1521,
    "username": "meta_reader",
    "password": "not-a-real-password",
    "ssl_mode": "disable",
    "service_name": "MES",
    "owner": "MES_APP",
    "extra": {}
  }
}
```

Rules: for `kind=database`, `engine` and `access` are required (`SOURCE_ACCESS_REQUIRED` / `SOURCE_ACCESS_INVALID` / `SOURCE_ENGINE_UNSUPPORTED` as applicable). Spec validation enforces required dialect scope keys. Creating a database Source also inserts two ordinary **Scheduled Task**s: one structure (product default daily `0 2 * * *`, enabled, default name `structure · {source_key}`) and one join-detection (product default daily `0 4 * * *`, enabled, default name `join_detection · {source_key}`). Cron uses the **Schedule Timezone** System Parameter. Create and both seeds succeed or fail together. The response remains `{ "source": { … } }` — it does not include the seeds. Updating `access` does not delete catalog; the next structure Job re-collects against the new endpoint.
**Cutover:** rows that used plaintext `access` JSONB plus a separate secret column are **not** auto-migrated; operators must re-enter connectivity after upgrade. Pre-0021 top-level `database_name` / `schema_filter` are one-shot backfilled into `access` then dropped (ADR 0021).

### `PATCH /sources/{id}`

Partial update of name, description, status, engine, and/or `access`. When business fields actually change on a database Source, the product inserts a default **Scheduled Task** for each missing work kind (`structure`, `join_detection`; disabled schedules of that kind count as present). The success body is `{ "source": { … }, "schedules": [ … ] }` only when at least one insert happened; otherwise `{ "source": { … } }` with the `schedules` key omitted. GET and `POST /sources` never include `schedules`.

### `GET /sources/{id}/access`

```json
{
  "access": {
    "host": "db.example.internal",
    "port": 1521,
    "username": "meta_reader",
    "password": "not-a-real-password",
    "ssl_mode": "disable",
    "service_name": "MES",
    "owner": "MES_APP",
    "extra": {}
  }
}
```

Missing / undecryptable blob → `SOURCE_ACCESS_REQUIRED` or `SOURCE_SECRET_REQUIRED` as applicable.

### `DELETE /sources/{id}`

Hard-delete. Allowed only when `status` is `disabled`.

- Success: `204` with empty body. Catalog Objects (and columns) under the Source are removed. Historical Jobs that referenced the Source in `input` are retained (no FK).
- `status=active` (or any non-disabled) → `409` `SOURCE_NOT_DISABLED`.
- Unknown id, or a Source the caller has no level on → `404` `SOURCE_NOT_FOUND`. A level without `sources:write` is `403` `AUTH_FORBIDDEN` and is not `SOURCE_NOT_DISABLED`.

### Source reachability test

Probe only: sync HTTP, no Job, no catalog mutation, no write to Source. Scope comes from the same `access` document used for connectivity (no probe-only database field).

#### `POST /sources/test` (draft)

```json
{
  "engine": "postgresql",
  "access": {
    "host": "db.example.internal",
    "port": 5432,
    "username": "meta_reader",
    "password": "not-a-real-password",
    "ssl_mode": "require",
    "database": "postgres",
    "extra": {}
  }
}
```

#### `POST /sources/{id}/test` (stored)

```json
{
  "engine": null,
  "access": null
}
```

Rules:

- Draft requires a full valid `access` including secrets and required dialect scope keys.
- Stored test uses body `access` when present; otherwise decrypts the stored access blob (`SOURCE_SECRET_REQUIRED` / access errors if none or decrypt fails).
- Optional `engine` on the stored endpoint overrides the row for this probe only. Missing engine (body and row) is `SOURCE_ACCESS_REQUIRED`; invalid `access` uses the same codes as create/patch.
- Success response: `{ "ok": true }`. Success proves the live endpoint **and** that the dialect catalog scope object (`schema` / `owner` from the same `access` document) exists. A reachable host with a missing scope is not success.
- Completed probe failure (unreachable, auth rejected, declared scope missing, timeout ~10s): HTTP 200 with `{ "ok": false, "code": "SOURCE_TEST_FAILED" | "SOURCE_TEST_TIMEOUT", "message": "..." }` — never row data beyond the result envelope; audit detail must not include passwords. Draft uses `resource_id` `"draft"`.
- Validation / missing Source: 400 / 404 with stable codes as elsewhere.
- Admission pool full or this actor's share full: `ADMISSION_CAPACITY_EXCEEDED` (`503`) / `ADMISSION_ACTOR_LIMIT_EXCEEDED` (`429`), same as Controlled Query (ADR 0045).
- Probe does not block save; results are not persisted on the Source.

### 3.1 Source Membership

Business rule: `docs/business-metadata.md` §6.1. Levels are `viewer`, `steward`, `maintainer`. The every-Source target stored on a row is `*`.

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `GET` | `/sources/{source_id}/memberships` | `sources:access_manage`, or `maintainer` on that Source | List memberships whose target is this Source |
| `POST` | `/sources/{source_id}/memberships` | `sources:access_manage` | Create one membership on this Source (`201`) |
| `PATCH` | `/sources/{source_id}/memberships/{membership_id}` | `sources:access_manage` | Change `level` |
| `DELETE` | `/sources/{source_id}/memberships/{membership_id}` | `sources:access_manage` | Delete (`204`) |
| `GET` | `/source-memberships` | `sources:access_manage` | List every-Source memberships |
| `POST` | `/source-memberships` | `sources:access_manage` | Create an every-Source membership (`201`) |
| `PATCH` | `/source-memberships/{membership_id}` | `sources:access_manage` | Change `level` |
| `DELETE` | `/source-memberships/{membership_id}` | `sources:access_manage` | Delete (`204`) |
| `GET` | `/users/{user_id}/source-access` | `users:read` | Effective Source access for that User |

Create body:

```json
{
  "subject": { "type": "user", "id": "user_01" },
  "level": "viewer"
}
```

`subject.type` is `user`, `role`, or `group`. Change body is `{ "level": "steward" }` only. There is no Role field on the level.

List and write responses use `{ "items": [ Membership ] }` or `{ "membership": Membership }`. A membership is `{ "id", "subject", "target", "level", "created_at", "updated_at" }`. `subject` is `{ "type", "id", "display_name", "missing" }`. A subject that no longer exists has `missing: true` and `display_name: null`, and grants nothing. `target` is the Source id or `*`.

A `steward` or `viewer` who lacks `sources:access_manage` and lists a Source's memberships receives `403` `AUTH_FORBIDDEN`. No level, when the caller lacks `sources:access_manage`, and an unknown Source, are `404` `SOURCE_NOT_FOUND`. `sources:access_manage` can list and write a Source that exists and on which the caller has no level. A membership id that is missing, or that belongs to the other collection, is `404` `SOURCE_MEMBERSHIP_NOT_FOUND`.

| Code | Status | When |
| --- | --- | --- |
| `SOURCE_MEMBERSHIP_DUPLICATE` | 409 | That subject already has a membership for this target |
| `SOURCE_MEMBERSHIP_SUBJECT_UNKNOWN` | 422 | Unknown subject id or subject type |
| `SOURCE_MEMBERSHIP_LEVEL_UNKNOWN` | 422 | `level` is not `viewer`, `steward`, or `maintainer` |
| `SOURCE_MEMBERSHIP_NOT_FOUND` | 404 | No row for this id on this collection |
| `SOURCE_NOT_FOUND` | 404 | Source id is unknown, or the caller has no level and lacks `sources:access_manage` |
| `USER_NOT_FOUND` | 404 | `GET /users/{user_id}/source-access` names an unknown User |
| `AUTH_FORBIDDEN` | 403 | Role key missing on a write, or a list by a caller who lacks `sources:access_manage` and whose level is not `maintainer` |

Duplicate, unknown subject, and unknown level write no audit event. A successful create, change, or delete commits the row and then writes a **Management Audit Event**: resource type `source_membership`, resource id the membership id, action `source_membership.create`, `source_membership.update`, or `source_membership.delete`. Detail is `{ "subject": { "type", "id" }, "target", "old_level", "new_level" }`. `old_level` is null on create. `new_level` is null on delete.

`GET /users/{user_id}/source-access` returns `{ "items": [ { "source_id", "key", "name", "level", "contributions" } ] }`. Each contribution is `{ "kind", "subject_name" }`. `kind` is `direct`, `group`, `role`, `every`, or `identity`. The read lists registered Sources the User reaches. `super_admin` is `maintainer` on each of those Sources with contribution `identity` and has no stored membership. A Source that is gone between the explanation and the name lookup is omitted.

## 4. Non-Goals

- Import from external `dbmeta`
- Non-database Source kinds (CSV/file) and their attachment APIs
- A separate Connection resource or credential reuse across Sources
- Soft delete / versioned credential history / audit-per-rotation (hard-delete of disabled Sources is in scope; see `DELETE /sources/{id}`)
- Source test that returns query row data (reachability-only responses only)
- Persisting probe results (last-tested timestamp, auto status flip, or blocking save until tested)
- Free-form YAML authoring; hand-written per-engine forms (use SpecTree)
- SSH tunnel / Private Link in this slice
- Auto-migration of pre-0011 `secret_ciphertext` into the access blob
