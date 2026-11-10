# refraq API Contracts: Model Services

## 1. Purpose

This document defines the authenticated management API for **Model Service** records, purpose-level vector state, connectivity tests, and rebuild minting. It does not define Catalog Search HTTP, Entity MCP, or Job observe.

Related boundaries:

- Business rules: `docs/business-model-services.md`.
- Catalog Search: `docs/api-contracts-metadata.md`.
- Entity semantic search: `docs/api-contracts-entity-mcp.md`.
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
  "batch_limit": 32,
  "has_secret": true,
  "in_use": true,
  "created_at": "2026-09-01T09:00:00Z",
  "updated_at": "2026-09-01T10:00:00Z"
}
```

`url` is the full embeddings path. `timeout_sec` is the shared client read timeout in integer seconds (15–300). Create requires it. Patch omits it to keep the stored value; null does not clear it. `batch_limit` is the maximum input strings in one embeddings request, an integer from 1 through 32. Create omits it to store 32. Patch omits it to keep the stored value. `has_secret` is whether an API key is stored. `in_use` is true when this row is the purpose’s current in-use service.

## 4. Purpose State Shape

```json
{
  "purpose": "embedding",
  "closed": false,
  "ready": true,
  "in_use_id": "msvc_ab12cd34ef56",
  "generation": 3,
  "control_revision": 4,
  "index_status": "ready",
  "catalog_index": {
    "ready": true,
    "generation_last_swept": 3,
    "index_status": "ready",
    "coverage": {
      "objects_written": 12,
      "columns_written": 80,
      "objects_failed": 0,
      "columns_failed": 0,
      "objects_attempted": 12,
      "columns_attempted": 80
    },
    "progress": null,
    "failure_summary": null,
    "rebuild_owed": false
  },
  "entity_index": {
    "ready": false,
    "generation": null,
    "index_status": "none",
    "coverage": { "written": 0, "failed": 0, "attempted": 0 },
    "progress": null,
    "failure_summary": null,
    "schedule": {
      "id": "sched_entity_embed_site",
      "enabled": true,
      "cron": "0 3 * * *",
      "interval_seconds": null,
      "next_run_at": "2026-08-14T03:00:00Z"
    },
    "rebuild_owed": true
  },
  "embed_schedule": {
    "id": "sched_catalog_embed_site",
    "enabled": true,
    "cron": "0 3 * * *",
    "interval_seconds": null,
    "next_run_at": "2026-08-14T03:00:00Z"
  }
}
```

`ready` and `index_status` on this object are the Catalog index. `ready` equals `catalog_index.ready`. Catalog Search reads `catalog_index_state.ready`, not the stored `model_service_purposes.ready` column. `entity_index` is absent from that decision. `generation` is the shared embedding space. `control_revision` fences calls and ready publication and is not part of that space.

`index_status` is `none` | `indexing` | `ready` | `failed`. On the purpose object and on `catalog_index`, it is `ready` when the Catalog ready bit is set. Otherwise a non-terminal `catalog_embed` Job makes it `indexing`. Otherwise it is `failed` when the latest Catalog sweep is `failed`, and `none` when there is no sweep or that sweep has another status. `entity_index.index_status` uses the same ladder over `entity_embed` sweeps and `entity_index.ready`. A sweep is a Job of that kind whose result `outcome` is not `skipped`. Failed and cancelled Jobs leave `result` null and count as sweeps. Status is not computed by scanning embedding rows.

`catalog_index.generation_last_swept` is the generation of the last Catalog publish, or null when none has published. `entity_index.generation` is the generation of the last Entity publish, or null. `entity_index.ready` does not mean every incremental target is present. `rebuild_owed` is true after a shared space change until that domain's sweep publishes. `in_use_id` is null when the purpose has no in-use service. `embed_schedule` describes the site cadence that mints `catalog_embed`. `entity_index.schedule` describes the site cadence that mints `entity_embed` (`key` `entity_embed:site`). Each object is id, enabled, cadence, and the next due Instant. Minted Jobs are observed on that schedule’s `recent_jobs` and related Jobs, not on purpose state.

## 5. Endpoints

### `GET /model-services/spec`

Permission: `model_services:read`. Returns the purpose/protocol specification used to drive create and edit forms. Query `purpose` defaults to `embedding`; `protocol` defaults to `openai_compat`. Unimplemented values are `MODEL_SERVICE_PURPOSE_UNSUPPORTED` or `MODEL_SERVICE_PROTOCOL_UNSUPPORTED`.

### `GET /model-services`

Permission: `model_services:read`. **Offset Page** of record shapes (newest `updated_at` first, then `id`). Query params: `purpose` (optional), `limit` (default **50**, max **200**), `offset` (default **0**).

### `GET /model-services/purpose/{purpose}`

Permission: `model_services:read`. Returns the purpose state shape. Unknown purpose → `MODEL_SERVICE_PURPOSE_UNSUPPORTED`.

### `POST /model-services`

Permission: `model_services:write`. Creates a draft. Body: `purpose`, `protocol`, `display_name`, `url`, `model`, `timeout_sec`, optional `batch_limit`, optional `api_key`. `purpose` must be `embedding` and `protocol` must be `openai_compat`.

### `GET /model-services/{id}`

Permission: `model_services:read`. Returns the record shape.

### `PATCH /model-services/{id}`

Permission: `model_services:write`. Updates display name, `timeout_sec`, `batch_limit`, URL, model, and secret. An in-use row rejects a `protocol` change with `MODEL_SERVICE_WIRE_IMMUTABLE`. `timeout_sec` outside 15–300, or `batch_limit` outside 1–32, is `MODEL_SERVICE_INVALID_CONFIG`. An in-use `timeout_sec` or `batch_limit` change does not advance generation, does not clear either index, and does not mint a rebuild.

URL unchanged and `api_key` omitted: keep the stored secret. URL changed: the request must supply `api_key` or `clear_api_key: true`; the stored secret is not sent to the new URL. Secret, URL, or model changes run the connectivity test before persist; failure does not save.

An in-use URL or model change that passes the test clears both index ready bits, increments generation and the control revision, and runs both site embed schedules now. Secret-only, display-name-only, timeout-only, and batch-limit-only changes do not. The call does not cancel an in-flight Job.

### `POST /model-services/{id}/test`

Permission: `model_services:write`. Posts a fixed short probe (`input` as a string array; no `dimensions`) to the stored full URL. Success: `{ "ok": true, "dimension": N, "elapsed_ms": N, "model": "…", "output_dim": 1024, "timeout_sec": N }`. `dimension` is the native probe width. `output_dim` is `EMBEDDING_OUTPUT_DIM` (1024). A longer vector is prefix-truncated to that width and then L2-normalized. A prefix whose norm is zero is returned unscaled. A vector of that width or shorter passes through. The processing contract is `prefix-1024-l2-v1`. `elapsed_ms` is how long this probe took; it is not a threshold. `timeout_sec` is the client read timeout this probe used. Probe, index batch, and query embed share the in-use record’s `timeout_sec`. Failure: Problem Details with a classified code; `detail` may include the **actual request URL** and a truncated remote body. Does not change in-use, closed, or ready.

### `POST /model-services/{id}/activate`

Permission: `model_services:write`. Tests, then sets this row in use for its purpose. Another in-use row of the same purpose becomes a draft. Always clears both index ready bits, increments generation and the control revision, and runs both site embed schedules now — including when the purpose is closed. Test failure leaves in-use unchanged. Each Job may skip while closed.

### `DELETE /model-services/{id}`

Permission: `model_services:write`. Deletes the row and secret. If it was in use, the purpose has no in-use service and Catalog Search is lexical. An in-flight embed Job is not cancelled. Neither index is cleaned.

### `POST /model-services/purpose/{purpose}/close`

Permission: `model_services:write`. Sets `closed=true` and bumps `control_revision`. Generation is unchanged. Catalog Search becomes lexical. Entity semantic search is refused. Both indexes keep their vectors and ready bits. Does not cancel an in-flight embed Job. Idempotent when already closed, and still bumps `control_revision`.

### `POST /model-services/purpose/{purpose}/open`

Permission: `model_services:write`. Empty body. Tests the current in-use service, then sets `closed=false` and bumps `control_revision`. No in-use service → `MODEL_SERVICE_NOT_IN_USE`. Test failure leaves the purpose closed. Does not mint a Job and does not change generation. Catalog vector search resumes only if `catalog_index.ready` is still true. Entity semantic search resumes only if `entity_index` is ready on the current generation.

### `POST /model-services/purpose/{purpose}/force-generation`

Permission: `model_services:write`. Empty body. No in-use service → `MODEL_SERVICE_NOT_IN_USE`. Increments `generation` and `control_revision`, clears both index ready bits, records `rebuild_owed` on both indexes, and runs both site embed schedules now. URL, model, and stored vectors stay. Does not cancel an in-flight Job.

### `POST /model-services/purpose/{purpose}/cleanup`

Permission: `model_services:write`. Allowed when `closed` or `in_use_id` is null. Otherwise `MODEL_SERVICE_CLEANUP_FORBIDDEN`. If a `catalog_embed` or `entity_embed` Job is non-terminal, `MODEL_SERVICE_CLEANUP_BUSY`. Deletes Catalog embedding rows and Entity projection rows, clears both ready bits, leaves `rebuild_owed` false on both, and bumps `control_revision`. Generation is unchanged. Does not mint a Job, does not cancel one, and does not refill either index.

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
| `409` | `MODEL_SERVICE_WIRE_IMMUTABLE` | PATCH changed protocol on an in-use row |
| `409` | `MODEL_SERVICE_NOT_IN_USE` | Open or force generation without an in-use service |
| `409` | `MODEL_SERVICE_CLEANUP_FORBIDDEN` | Cleanup while open and an in-use service exists |
| `409` | `MODEL_SERVICE_CLEANUP_BUSY` | Cleanup while a `catalog_embed` or `entity_embed` Job is non-terminal |
| `409` | `MODEL_SERVICE_SECRET_REQUIRED` | URL changed without a new key or `clear_api_key` |
| `503` | `MODEL_SERVICE_UNAVAILABLE` | Embeddings URL cannot be reached, or the client deadline elapsed (connect or read) |

## 8. Non-Goals

- Runtime creation of protocols or free-form adapters
- Returning stored API keys or accepting client-echoed mask strings
- MCP mint or observe of `catalog_embed` or `entity_embed`
- Scanning embedding rows to compute `index_status`
- Treating `model_service_purposes.ready` as the Catalog Search switch

## 9. References

- `docs/business-model-services.md`
- `docs/api-contracts-jobs.md`
- `docs/conventions-errors.md`
