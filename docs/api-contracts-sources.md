# refraq API Contracts: Sources And Connections

## 1. Purpose

HTTP contracts for **Source System** and **Connection** management (metadata foundation slice A+).

Business rules: `docs/business-metadata.md`.
Transport: `application/json`. Authentication: Session cookie **or** User PAT Bearer (`docs/api-contracts-auth.md`, `docs/api-contracts-tokens.md`).
`401` unauthenticated; `403` missing permission.

## 2. Shared Shapes

### Source System

```json
{
  "id": "src_mes",
  "key": "mes",
  "name": "MES",
  "system_type": "manufacturing",
  "status": "active",
  "description": null
}
```

### Connection (secret never returned)

```json
{
  "id": "conn_mes_prod",
  "source_system_id": "src_mes",
  "name": "MES production",
  "engine": "oracle",
  "instance_key": "prod",
  "host": "db.example.internal",
  "port": 1521,
  "database_name": "MES",
  "schema_filter": null,
  "status": "active",
  "is_collection_active": true,
  "has_secret": true,
  "secret_updated_at": "2026-08-05T01:00:00Z"
}
```

### Error

```json
{
  "code": "CONNECTION_INSTANCE_KEY_DUPLICATE",
  "message": "Instance key already exists for this source system"
}
```

## 3. Source System Endpoints

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `GET` | `/sources` | `sources:read` | List Source Systems |
| `POST` | `/sources` | `sources:write` | Create |
| `GET` | `/sources/{id}` | `sources:read` | Get |
| `PATCH` | `/sources/{id}` | `sources:write` | Update fields / status |
| `GET` | `/sources/{id}/connections` | `sources:read` | List Connections for source |

### `POST /sources` body

```json
{
  "key": "mes",
  "name": "MES",
  "system_type": "manufacturing",
  "description": null
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
  "name": "MES production",
  "engine": "oracle",
  "instance_key": "prod",
  "host": "db.example.internal",
  "port": 1521,
  "database_name": "MES",
  "schema_filter": null,
  "is_collection_active": true,
  "secret": {
    "username": "meta_reader",
    "password": "not-a-real-password"
  }
}
```

Rules:

- Response never echoes `secret`.
- Enforcing one active full-ingest Connection per `(source_system_id, instance_key)` returns a stable conflict code when violated.
- Engines in slice A: `postgresql`, `mssql`, `oracle`.

## 5. Non-Goals

- Import from external `dbmeta`
- Connection test that returns row data (optional `POST /connections/{id}/test` may return reachability only in implementation; not required to expose query results)
