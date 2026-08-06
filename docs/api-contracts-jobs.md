# refraq API Contracts: Jobs

## 1. Purpose

Contracts for enqueueing and observing platform **Jobs** via domain facades (metadata / Source surfaces in this phase).

Business rules: `docs/business-metadata.md`, root `CONTEXT.md`.
Auth: Session or User PAT. Permissions: `jobs:run` unless noted.

## 2. Job Shape

```json
{
  "id": "job_01HZX",
  "kind": "structure",
  "status": "queued",
  "input": {
    "source_id": "src_mes_prod",
    "connection_id": "conn_mes_prod"
  },
  "created_by_user_id": "user_001",
  "created_at": "2026-08-05T02:00:00Z",
  "started_at": null,
  "finished_at": null,
  "error_code": null,
  "error_message": null
}
```

Status: `queued` | `running` | `succeeded` | `failed` | `cancelled`.

Rules:

- **Job** is a durable asynchronous execution record. It is not owned by Connection or Source.
- Public Job fields are lifecycle + `kind` + generic **`input`** (object). Domains interpret `input` per `kind`.
- No universal `source_id` / `connection_id` columns on Job; those appear inside `input` when the kind requires them.
- Slice A `kind=structure` for `kind=database` Sources: `input` includes `source_id` and `connection_id`.

## 3. Endpoints

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `POST` | `/sources/{id}/jobs` | `jobs:run` | Enqueue a Job for this Source (domain facade) |
| `GET` | `/sources/{id}/jobs` | `jobs:run` | List Jobs related to this Source (domain facade) |
| `GET` | `/jobs/{id}` | `jobs:run` | Get Job by id |
| `POST` | `/jobs/{id}/cancel` | `jobs:run` | Cancel if not terminal |

### `POST /sources/{id}/jobs` body (Slice A structure)

```json
{
  "kind": "structure",
  "connection_id": "conn_mes_prod"
}
```

Rules:

- Path `{id}` is the Source; the facade validates the Source, builds Job `input` (at least `source_id` from the path + body fields such as `connection_id`), persists the Job, and enqueues the worker after commit.
- For database structure Jobs, resolve `connection_id` from the body or, if omitted, from the Source's single collection-active Connection. The Connection must belong to that Source, be usable, and have a secret; otherwise return a stable error.
- Response `202` returns the Job shape. Work runs asynchronously on a worker.

### `GET /sources/{id}/jobs`

Domain list semantics for “Jobs related to this Source” (for example Jobs whose `input.source_id` matches). Query params may include `status`, `kind`. This is a Source/metadata concern — not a reason to add Source columns on the Job record.

## 4. Errors

| code | When |
| --- | --- |
| `JOB_SOURCE_DISABLED` | Source not usable |
| `JOB_CONNECTION_DISABLED` | Connection not usable for this kind |
| `JOB_SECRET_MISSING` | No usable Connection secret when required |
| `JOB_INPUT_INVALID` | Kind/input failed domain validation |
| `JOB_NOT_CANCELLABLE` | Job already terminal |

Stable aliases of older draft codes (`INGESTION_*`) must not be reintroduced in new clients.

## 5. Slice Notes

- Slice A: `kind=structure` only on the Source facade for database Sources.
- Later slices/domains may add kinds and additional facade routes; unknown kind → `400` with stable code.
- Console module id `jobs`; permission `jobs:run`.

## 6. Non-Goals

- Global `POST /jobs` as the only create path in this phase (platform store may still be shared; HTTP create goes through domain facades)
- Promoting `source_id` / `connection_id` to universal Job fields
