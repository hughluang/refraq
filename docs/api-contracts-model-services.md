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
  "has_secret": true,
  "in_use": true,
  "created_at": "2026-09-01T09:00:00Z",
  "updated_at": "2026-09-01T10:00:00Z"
}
```

`url` is the full embeddings path. `has_secret` is whether an API key is stored. `in_use` is true when this row is the purpose’s current in-use service.

## 4. Purpose State Shape

```json
{
  "purpose": "embedding",
  "closed": false,
  "ready": true,
  "in_use_id": "msvc_ab12cd34ef56",
  "generation": 3,
  "index_status": "ready"
}
```

`index_status` is `none` | `indexing` | `ready` | `failed`, derived from the ready bit and the latest `catalog_embed` Job. It is not computed by scanning embedding rows. `in_use_id` is null when the purpose has no in-use service.

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

Permission: `model_services:write`. Updates display name and, when the row is a draft, URL / model / protocol / secret. An in-use row rejects `model` or `protocol` changes with `MODEL_SERVICE_WIRE_IMMUTABLE`.

URL unchanged and `api_key` omitted: keep the stored secret. URL changed: the request must supply `api_key` or `clear_api_key: true`; the stored secret is not sent to the new URL. Secret or URL changes run the connectivity test before persist; failure does not save.

An in-use URL change that passes the test clears ready, increments generation, cancels an in-flight `catalog_embed` Job, and mints a new one. Secret-only or display-name-only changes do not.

### `POST /model-services/{id}/test`

Permission: `model_services:write`. Posts a fixed short probe (`input` as a string array; no `dimensions`) to the stored full URL. Success: `{ "ok": true, "dimension": N, "elapsed_ms": N, "model": "…" }`. Failure: Problem Details with a classified code; `detail` may include the **actual request URL** and a truncated remote body. Does not change in-use, closed, or ready.

### `POST /model-services/{id}/activate`

Permission: `model_services:write`. Tests, then sets this row in use for its purpose. Another in-use row of the same purpose becomes a draft. Always clears ready, increments generation, cancels an in-flight `catalog_embed` Job, and mints a new one — including when the purpose is closed. Test failure leaves in-use unchanged.

### `DELETE /model-services/{id}`

Permission: `model_services:write`. Deletes the row and secret. If it was in use, the purpose has no in-use service, search is lexical, and an in-flight `catalog_embed` Job is cancelled. The index is not cleaned.

### `POST /model-services/purpose/{purpose}/close`

Permission: `model_services:write`. Sets `closed=true`. Search becomes lexical. Does not cancel `catalog_embed`. Idempotent when already closed.

### `POST /model-services/purpose/{purpose}/open`

Permission: `model_services:write`. Body: `{ "rebuild": "none" | "full" }`. Tests the current in-use service, then sets `closed=false`. No in-use service → `MODEL_SERVICE_NOT_IN_USE`. Test failure leaves the purpose closed.

`rebuild=none` does not mint a Job. Hybrid resumes only if ready is still true.

`rebuild=full` clears ready, increments generation, cancels an in-flight same-kind Job, and mints `catalog_embed`.

### `POST /model-services/purpose/{purpose}/cleanup`

Permission: `model_services:write`. Allowed when `closed` or `in_use_id` is null. Otherwise `MODEL_SERVICE_CLEANUP_FORBIDDEN`. Cancels an in-flight `catalog_embed` Job, deletes that purpose’s catalog embedding rows, and clears ready. Does not mint a Job.

### `POST /model-services/purpose/{purpose}/reindex`

Permission: `model_services:write`. Rebuild-now for the current in-use service. No in-use → `MODEL_SERVICE_NOT_IN_USE`. Tests are not required. Clears ready, increments generation, cancels an in-flight same-kind Job, and mints `catalog_embed`. Allowed while closed.

## 6. `catalog_embed` Job

`kind` is `catalog_embed`. `trigger_kind` is `user`; `trigger_ref` and `created_by` are the acting User. `input` is `{ "model_service_id": "…", "generation": N }`. **Job result** on success:

```json
{
  "schema": "catalog_embed.v1",
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
  "failure_reasons": []
}
```

`objects` / `columns` are the written counts (same as `objects_written` / `columns_written`). `failure_reasons` is `{ "message", "count" }` per distinct embed error, ordered by count descending; empty when no row failed. Per-row embed failures increment the failed counters and do not fail the Job when at least one vector was written. A run that writes no vectors against a non-empty catalog ends `failed` with `JOB_EXECUTION_FAILED` and does not set ready; `error_summary` includes the dominant embed reason when one was recorded. Failed or cancelled Jobs write no result and do not set ready. Platform observe remains `GET /jobs`. There is no `POST /jobs` create.

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
| `409` | `MODEL_SERVICE_NOT_IN_USE` | Open or reindex without an in-use service |
| `409` | `MODEL_SERVICE_CLEANUP_FORBIDDEN` | Cleanup while open and an in-use service exists |
| `409` | `MODEL_SERVICE_SECRET_REQUIRED` | URL changed without a new key or `clear_api_key` |
| `503` | `MODEL_SERVICE_UNAVAILABLE` | Embeddings URL cannot be reached |

## 8. Non-Goals

- Runtime creation of protocols or free-form adapters
- Returning stored API keys or accepting client-echoed mask strings
- MCP mint or observe of `catalog_embed`
- Scanning catalog embedding rows to compute `index_status`

## 9. References

- `docs/business-model-services.md`
- `docs/api-contracts-jobs.md`
- `docs/conventions-errors.md`
