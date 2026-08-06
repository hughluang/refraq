# refraq API Contracts: Sources And Connections

## 1. Purpose

HTTP contracts for **Source** and **Connection** management (metadata foundation slice A+).

Business rules: `docs/business-metadata.md`, `docs/adr/0007-source-owns-catalog-identity.md`.
Transport: `application/json`. Authentication: Session cookie **or** User PAT Bearer (`docs/api-contracts-auth.md`, `docs/api-contracts-tokens.md`).
`401` unauthenticated; `403` missing permission.

## 2. Shared Shapes

### Source

```json
{
  "id": "src_mes_prod",
  "key": "mes-prod",
  "name": "MES production",
  "kind": "database",
  "status": "active",
  "description": null,
  "database_name": "MES",
  "schema_filter": null
}
```

Slice A accepts `kind` = `database` only. Other kind values are reserved for later phases.
For `kind=database`, `database_name` is required; `schema_filter` is optional catalog scope.

### Connection (secret never returned)

```json
{
  "id": "conn_mes_prod",
  "source_id": "src_mes_prod",
  "name": "MES production primary",
  "engine": "oracle",
  "host": "db.example.internal",
  "port": 1521,
  "status": "active",
  "is_collection_active": true,
  "has_secret": true,
  "secret_updated_at": "2026-08-05T01:00:00Z"
}
```

Connection is reachability + credentials only. Catalog scope (`database_name`, `schema_filter`) lives on the parent Source.
Multi-environment catalogs are separate Sources.

### Error

```json
{
  "code": "CONNECTION_COLLECTION_ACTIVE_CONFLICT",
  "message": "Another connection is already collection-active for this source"
}
```

## 3. Source Endpoints

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `GET` | `/sources` | `sources:read` | List Sources |
| `POST` | `/sources` | `sources:write` | Create |
| `GET` | `/sources/{id}` | `sources:read` | Get |
| `PATCH` | `/sources/{id}` | `sources:write` | Update fields / status |
| `GET` | `/sources/{id}/connections` | `sources:read` | List Connections for source |

### `POST /sources` body

```json
{
  "key": "mes-prod",
  "name": "MES production",
  "kind": "database",
  "description": null,
  "database_name": "MES",
  "schema_filter": null
}
```

## 4. Connection Endpoints

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `POST` | `/sources/{id}/connections` | `sources:write` | Create Connection (includes secret once) |
| `GET` | `/connections/{id}` | `sources:read` | Get Connection (no secret) |
| `PATCH` | `/connections/{id}` | `sources:write` | Update non-secret fields / flags |
| `PUT` | `/connections/{id}/secret` | `sources:write` | Rotate secret |

### `POST .../connections` body (example)

```json
{
  "name": "MES production primary",
  "engine": "oracle",
  "host": "db.example.internal",
  "port": 1521,
  "is_collection_active": true,
  "secret": {
    "username": "meta_reader",
    "password": "not-a-real-password"
  }
}
```

Rules:

- Response never echoes `secret`.
- Parent Source must be `kind=database` (slice A); creating a Connection on an unsupported kind returns a stable error.
- Enforcing one active full-ingest Connection per Source returns `CONNECTION_COLLECTION_ACTIVE_CONFLICT` when violated.
- Engines in slice A: `postgresql`, `mssql`, `oracle`.
- Collectors open the live session using Connection host/port/engine/secret composed with the parent Source's `database_name` / `schema_filter`.

## 5. Non-Goals

- Import from external `dbmeta`
- Non-database Source kinds (CSV/file) and their attachment APIs
- Connection test that returns row data (optional `POST /connections/{id}/test` may return reachability only in implementation; not required to expose query results)
- Putting catalog scope (`database_name`, schema) on Connection
