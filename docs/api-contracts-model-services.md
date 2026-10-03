# refraq API Contracts: Model Services

## 1. Purpose

This document defines the authenticated management API for **Model Service** records, purpose-level vector state, connectivity tests, and rebuild minting. It does not define Catalog Search HTTP or Job observe.

Related boundaries:

- Business rules: `docs/business-model-services.md`.
- Catalog Search: `docs/api-contracts-metadata.md`.
- Jobs: `docs/api-contracts-jobs.md`.
- Errors: `docs/conventions-errors.md`.

## 2. Transport And Authorization

All endpoints use JSON success and RFC 9457 Problem Details failures. They accept Session or User PAT and require `console:access` plus `model_services:read` for reads or `model_services:write` for writes. Secrets are write-only and never returned. Existing custom Roles do not receive either Permission automatically; `super_admin` has both by definition.

## 3. Record Shape

```json
{
  "id": "msvc_ab12cd34ef56",
  "purpose": "embedding",
  "protocol": "openai_compat",
  "display_name": "Office TEI",
  "url": "http://embed.internal:8080/v1/embeddings",
  "model": "Qwen3-Embedding-8B",
  "timeout_sec": 30,
  "has_secret": true,
  "in_use": true,
  "created_at": "2026-09-01T09:00:00Z",
  "updated_at": "2026-09-01T10:00:00Z"
}
```

`url` is the full embeddings path. `timeout_sec` is the shared client read timeout in integer seconds (15–300). Create requires it. Patch omits it to keep the stored value; null does not clear it. `has_secret` is whether an API key is stored. `in_use` is true when this row is the purpose’s current in-use service.

## 4. Purpose State Shape

```json
{
  "purpose": "embedding",
  "closed": false,
  "ready": true,
  "in_use_id": "msvc_ab12cd34ef56",
  "generation": 3,
  "index_status": "ready",
  "embed_schedule": {
    "id": "sched_catalog_embed_site",
    "enabled": true,
    "cron": "0 3 * * *",
    "interval_seconds": null,
    "schedule_timezone": "UTC",
    "next_run_at": "2026-08-14T03:00:00Z"
  }
}
```

`index_status` is `none` | `indexing` | `ready` | `failed`. It is `ready` when the ready bit is set. Otherwise a non-terminal `catalog_embed` Job makes it `indexing`. Otherwise it is `failed` when the latest sweep is `failed`, and `none` when there is no sweep or that sweep has another status. A sweep is a `catalog_embed` Job whose result `outcome` is not `skipped`. Failed and cancelled Jobs leave `result` null and count as sweeps. It is not computed by scanning embedding rows. `in_use_id` is null when the purpose has no in-use service. `embed_schedule` describes the site cadence that mints `catalog_embed`: id, enabled, cadence, and the next due Instant. Minted Jobs are observed on that schedule’s `last_job` and related Jobs, not on purpose state.

## 5. Endpoints

### `GET /model-services/spec`

Permission: `model_services:read`. Returns the purpose/protocol specification used to drive create and edit forms. Query `purpose` defaults to `embedding`; `protocol` defaults to `openai_compat`. Unimplemented values are `MODEL_SERVICE_PURPOSE_UNSUPPORTED` or `MODEL_SERVICE_PROTOCOL_UNSUPPORTED`.

### `GET /model-services`

Permission: `model_services:read`. **Offset Page** of record shapes (newest `updated_at` first, then `id`). Query params: `purpose` (optional), `limit` (default **50**, max **200**), `offset` (default **0**).

### `GET /model-services/purpose/{purpose}`

Permission: `model_services:read`. Returns the purpose state shape. Unknown purpose → `MODEL_SERVICE_PURPOSE_UNSUPPORTED`.

### `POST /model-services`

Permission: `model_services:write`. Creates a draft. Body: `purpose`, `protocol`, `display_name`, `url`, `model`, optional `api_key`. First-slice `purpose` must be `embedding` and `protocol` must be `openai_compat`.

### `GET /model-services/{id}`

Permission: `model_services:read`. Returns the record shape.

### `PATCH /model-services/{id}`

Permission: `model_services:write`. Updates display name, `timeout_sec`, and, when the row is a draft, URL / model / protocol / secret. An in-use row rejects `model` or `protocol` changes with `MODEL_SERVICE_WIRE_IMMUTABLE`. `timeout_sec` outside 15–300 is `MODEL_SERVICE_INVALID_CONFIG`. An in-use `timeout_sec` change does not clear ready and does not mint `catalog_embed`.

URL unchanged and `api_key` omitted: keep the stored secret. URL changed: the request must supply `api_key` or `clear_api_key: true`; the stored secret is not sent to the new URL. Secret or URL changes run the connectivity test before persist; failure does not save.

An in-use URL change that passes the test clears ready, increments generation, and runs the site embed schedule now. Secret-only, display-name-only, or timeout-only changes do not. The call does not cancel an in-flight Job.

### `POST /model-services/{id}/test`

Permission: `model_services:write`. Posts a fixed short probe (`input` as a string array; no `dimensions`) to the stored full URL. Success: `{ "ok": true, "dimension": N, "elapsed_ms": N, "model": "…", "output_dim": 1024, "timeout_sec": N }`. `dimension` is the native probe width. `output_dim` is `EMBEDDING_OUTPUT_DIM`, the stored and query width after prefix truncation and L2-normalize. `elapsed_ms` is how long this probe took; it is not a threshold. `timeout_sec` is the client read timeout this probe used. Probe, index batch, and query embed share the in-use record’s `timeout_sec`. Failure: Problem Details with a classified code; `detail` may include the **actual request URL** and a truncated remote body. Does not change in-use, closed, or ready.

### `POST /model-services/{id}/activate`

Permission: `model_services:write`. Tests, then sets this row in use for its purpose. Another in-use row of the same purpose becomes a draft. Always clears ready, increments generation, and runs the site embed schedule now — including when the purpose is closed. Test failure leaves in-use unchanged. The Job may skip while closed.

### `DELETE /model-services/{id}`

Permission: `model_services:write`. Deletes the row and secret. If it was in use, the purpose has no in-use service and search is lexical. An in-flight `catalog_embed` Job is not cancelled. The index is not cleaned.

### `POST /model-services/purpose/{purpose}/close`

Permission: `model_services:write`. Sets `closed=true`. Search becomes lexical. Does not cancel `catalog_embed`. Idempotent when already closed.

### `POST /model-services/purpose/{purpose}/open`

Permission: `model_services:write`. Empty body. Tests the current in-use service, then sets `closed=false`. No in-use service → `MODEL_SERVICE_NOT_IN_USE`. Test failure leaves the purpose closed. Does not mint a Job and does not change generation. Vector Search resumes only if ready is still true.

### `POST /model-services/purpose/{purpose}/cleanup`

Permission: `model_services:write`. Allowed when `closed` or `in_use_id` is null. Otherwise `MODEL_SERVICE_CLEANUP_FORBIDDEN`. If a `catalog_embed` Job is non-terminal, `MODEL_SERVICE_CLEANUP_BUSY`. Deletes that purpose’s catalog embedding rows and clears ready. Does not mint a Job and does not cancel one.

## 6. `catalog_embed` Job

`kind` is `catalog_embed`. `trigger_kind` is `schedule`; `trigger_ref` is the site schedule id. Run-now sets `created_by` to the acting User; a due tick leaves it null. `input` is `{}`. **Job result** on success:

```json
{
  "schema": "catalog_embed.v1",
  "outcome": "completed",
  "reason": null,
  "objects": 12,
  "columns": 80,
  "objects_written": 12,
  "columns_written": 80,
  "objects_failed": 0,
  "columns_failed": 0,
  "objects_skipped": 0,
  "columns_skipped": 0,
  "objects_attempted": 12,
  "columns_attempted": 80,
  "generation": 3,
  "failure_reasons": [],
  "orphans_deleted": 0
}
```

`objects` / `columns` are the written counts (same as `objects_written` / `columns_written`). `failure_reasons` is `{ "message", "count" }` per distinct embed error, ordered by count descending; empty when no row failed. Per-row embed failures increment the failed counters and do not fail the Job when at least one vector was written, except when client-deadline rows (connect or read) outnumber written rows: the Job then stops, ends `failed` with `JOB_EXECUTION_FAILED`, and does not set ready. A run that writes no vectors against a non-empty catalog ends `failed` with `JOB_EXECUTION_FAILED` and does not set ready; `error_summary` includes the dominant embed reason when one was recorded. Failed or cancelled Jobs write no result and do not set ready. Platform observe remains `GET /jobs`. There is no `POST /jobs` create.

## 7. Errors

| Status | Problem Code | Condition |
| --- | --- | --- |
| `400` | `MODEL_SERVICE_INVALID_CONFIG` | Invalid URL, model, display name, or secret declaration |
| `400` | `MODEL_SERVICE_PURPOSE_UNSUPPORTED` | Purpose is not implemented |
| `400` | `MODEL_SERVICE_PROTOCOL_UNSUPPORTED` | Protocol is not implemented |
| `400` | `MODEL_SERVICE_TEST_FAILED` | Endpoint reachable but the embeddings response is unusable |
| `403` | `AUTH_FORBIDDEN` | Missing Model Service permission |
| `404` | `MODEL_SERVICE_NOT_FOUND` | Record does not exist |
| `409` | `MODEL_SERVICE_WIRE_IMMUTABLE` | PATCH changed model or protocol on an in-use row |
| `409` | `MODEL_SERVICE_NOT_IN_USE` | Open without an in-use service |
| `409` | `MODEL_SERVICE_CLEANUP_FORBIDDEN` | Cleanup while open and an in-use service exists |
| `409` | `MODEL_SERVICE_CLEANUP_BUSY` | Cleanup while a `catalog_embed` Job is non-terminal |
| `409` | `MODEL_SERVICE_SECRET_REQUIRED` | URL changed without a new key or `clear_api_key` |
| `503` | `MODEL_SERVICE_UNAVAILABLE` | Embeddings URL cannot be reached, or the client deadline elapsed (connect or read) |

## 8. Non-Goals

- Runtime creation of protocols or free-form adapters
- Returning stored API keys or accepting client-echoed mask strings
- MCP mint or observe of `catalog_embed`
- Scanning catalog embedding rows to compute `index_status`

## 9. References

- `docs/business-model-services.md`
- `docs/api-contracts-jobs.md`
- `docs/conventions-errors.md`
