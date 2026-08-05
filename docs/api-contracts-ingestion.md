# refraq API Contracts: Ingestion Jobs

## 1. Purpose

Contracts for enqueueing and observing **Ingestion Jobs**.

Business rules: `docs/business-metadata.md`.
Auth: Session or User PAT. Permissions: `ingestion:run` unless noted.

## 2. Job Shape

```json
{
  "id": "job_01HZX",
  "connection_id": "conn_mes_prod",
  "source_system_id": "src_mes",
  "kind": "structure",
  "status": "queued",
  "created_by_user_id": "user_001",
  "created_at": "2026-08-05T02:00:00Z",
  "started_at": null,
  "finished_at": null,
  "error_code": null,
  "error_message": null
}
```

Status: `queued` | `running` | `succeeded` | `failed` | `cancelled`.

## 3. Endpoints

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `POST` | `/connections/{id}/ingestion-jobs` | `ingestion:run` | Enqueue job |
| `GET` | `/ingestion-jobs` | `ingestion:run` | List (filter by connection/source/status) |
| `GET` | `/ingestion-jobs/{id}` | `ingestion:run` | Get |
| `POST` | `/ingestion-jobs/{id}/cancel` | `ingestion:run` | Cancel if not terminal |

### `POST /connections/{id}/ingestion-jobs` body

```json
{
  "kind": "structure"
}
```

### Response: `202`

Returns the Job shape. Collection runs asynchronously on a worker.

## 4. Errors

| code | When |
| --- | --- |
| `INGESTION_CONNECTION_DISABLED` | Connection or Source not usable |
| `INGESTION_SECRET_MISSING` | No usable secret |
| `INGESTION_NOT_CANCELLABLE` | Job already terminal |

## 5. Slice Notes

- Slice A: `kind=structure` only.
- Later slices may add kinds; unknown kind → `400` with stable code.
