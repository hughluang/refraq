# refraq API Contracts: Sources

## 1. Purpose

HTTP contracts for **Source** management (metadata foundation slice A+), including embedded reachability and credentials for `kind=database`.

Business rules: `docs/business-metadata.md`, `docs/adr/0007-source-owns-catalog-identity.md`, `docs/adr/0010-source-owns-access.md`, `docs/adr/0011-encrypted-access-blob-and-connector-spec.md`, `docs/adr/0021-catalog-scope-in-access.md`.
Transport: `application/json`. Authentication: Session cookie **or** User PAT Bearer (`docs/api-contracts-auth.md`, `docs/api-contracts-tokens.md`).
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

```json
{
  "code": "SOURCE_ACCESS_REQUIRED",
  "message": "A database source requires engine and access"
}
```

## 3. Source Endpoints

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `GET` | `/sources` | `sources:read` | List Sources (projected `access`) |
| `GET` | `/sources/access-schema/{engine}` | `sources:read` | Connector Spec (JSON Schema) for SpecTree + validation |
| `POST` | `/sources` | `sources:write` | Create (database kind requires engine + full `access` including secrets and dialect scope) |
| `GET` | `/sources/{id}` | `sources:read` | Get (projected `access`) |
| `GET` | `/sources/{id}/access` | `sources:write` | Decrypted full `access` tree for edit |
| `PATCH` | `/sources/{id}` | `sources:write` | Update fields / status / replace full `access` |
| `DELETE` | `/sources/{id}` | `sources:write` | Hard-delete a **disabled** Source (and its catalog) |
| `POST` | `/sources/test` | `sources:write` | Reachability probe for a draft Source (not persisted) |
| `POST` | `/sources/{id}/test` | `sources:write` | Reachability probe for a stored Source |

There is **no** `PUT /sources/{id}/secret`. Credential changes are a full `access` replace via create/patch (or probe override).

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

Rules: for `kind=database`, `engine` and `access` are required (`SOURCE_ACCESS_REQUIRED` / `SOURCE_ACCESS_INVALID` / `SOURCE_ENGINE_UNSUPPORTED` as applicable). Spec validation enforces required dialect scope keys. Updating `access` does not delete catalog; the next structure Job re-collects against the new endpoint.
**Cutover:** rows that used plaintext `access` JSONB plus a separate secret column are **not** auto-migrated; operators must re-enter connectivity after upgrade. Pre-0021 top-level `database_name` / `schema_filter` are one-shot backfilled into `access` then dropped (ADR 0021).

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
- Unknown id → `404` `SOURCE_NOT_FOUND`.

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
- Success response: `{ "ok": true }`.
- Completed probe failure (unreachable, auth rejected, timeout ~10s): HTTP 200 with `{ "ok": false, "code": "SOURCE_TEST_FAILED" | "SOURCE_TEST_TIMEOUT", "message": "..." }` — never row data beyond the result envelope; audit detail must not include passwords. Draft uses `resource_id` `"draft"`.
- Validation / missing Source: 400 / 404 with stable codes as elsewhere.
- Probe does not block save; results are not persisted on the Source.

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
