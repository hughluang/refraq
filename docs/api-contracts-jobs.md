# refraq API Contracts: Jobs

## 1. Purpose

Contracts for enqueueing and observing platform **Jobs** via domain facades (metadata / Source surfaces in this phase) and platform list/get/logs/cancel.

Business rules: `docs/business-jobs.md` (platform Job) and `docs/business-metadata.md` §4.2 (structure Source facade), root `CONTEXT.md`.
Auth: Session or User PAT. Permissions: `jobs:run` unless noted.
Instants: [`docs/conventions-time.md`](conventions-time.md) (UTC `Z` on the wire).
HTTP protocol failures: [`docs/conventions-errors.md`](conventions-errors.md). Job `error_code` / `error_message` remain resource fields on a successful GET, not Problem Details.

## 2. Job Shape

```json
{
  "id": "job_01HZX",
  "kind": "structure",
  "status": "queued",
  "input": {
    "source_id": "src_mes_prod"
  },
  "summary": "structure · mes-prod",
  "result": null,
  "trigger_kind": "user",
  "trigger_ref": "user_001",
  "trigger_actor_name": "Ada",
  "created_by_user_id": "user_001",
  "created_at": "2026-08-05T02:00:00Z",
  "started_at": null,
  "finished_at": null,
  "error_code": null,
  "error_message": null,
  "log_updated_at": "2026-08-05T02:00:00Z"
}
```

Status: `queued` | `running` | `succeeded` | `failed` | `cancelled`.

Rules:

- **Job** is a durable asynchronous execution record. It is not owned by Source.
- Public Job fields are lifecycle + `kind` + generic **`input`** + observation fields **`summary`**, **`trigger_kind`**, **`trigger_ref`**, and nullable generic **`result`**.
- **`summary`** is a human-readable snapshot written at enqueue (structure: `structure · {source_key}`). It is not a Source foreign key and must not be confused with the **Source** entity. Do not overwrite it with outcome.
- **`result`** is kind-interpreted structured outcome, written only when the Job reaches **succeeded**. Failed, cancelled, and fail-safe Jobs leave `result` `null` (never `{}`). Platform list/get do not interpret the document. Structure envelope:

```json
{
  "schema": "structure.diff.v1",
  "class": "breaking",
  "counts": {
    "objects_added": 0,
    "objects_removed": 1,
    "columns_added": 0,
    "columns_removed": 1,
    "type_changed": 0,
    "pk_changed": 0,
    "nullable_tightened": 0,
    "nullable_widened": 0,
    "comments_or_defaults": 0
  },
  "structure_diff_id": "sdiff_01"
}
```

`class` is `breaking` | `non_breaking` | `unchanged`. Full locators live on the **Structure Diff** (`docs/api-contracts-metadata.md`), not in `result`. Other kinds keep `result` null.
- **`trigger_kind`** / **`trigger_ref`** describe how the Job was started (`user` | `schedule` | `mcp` | `system`, plus optional id). Coexist with **`created_by_user_id`** (user triggers set both).
- **`trigger_actor_name`** is a presentation-only field: when `trigger_kind` is `user` and `trigger_ref` resolves to a known User, it is that User's `display_name`; otherwise `null`. It is not an identity field — **`trigger_ref`** remains authoritative.
- Operator-visible run log lives on the Job row as **`log_body`** (newline-separated lines). List/get Job shapes do **not** include full `log_body`; use `GET /jobs/{id}/logs`. Optional **`log_updated_at`** may appear on JobOut.
- No universal `source_id` columns on Job; domain ids appear inside `input` when the kind requires them.
- Slice A `kind=structure` for `kind=database` Sources: `input` includes `source_id` only. Workers load reachability from the Source.

## 3. Endpoints

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `POST` | `/sources/{id}/jobs` | `jobs:run` | Enqueue a Job for this Source (domain facade) |
| `GET` | `/sources/{id}/jobs` | `jobs:run` | List Jobs related to this Source (domain facade) |
| `GET` | `/jobs` | `jobs:run` | Platform list all Jobs (`status`, `kind` query filters) |
| `GET` | `/jobs/{id}` | `jobs:run` | Get Job by id |
| `GET` | `/jobs/{id}/logs` | `jobs:run` | Get Job `log_body` (`{ job_id, body, updated_at }`) |
| `POST` | `/jobs/{id}/cancel` | `jobs:run` | Cancel if not terminal |

### `POST /sources/{id}/jobs` body (Slice A structure)

```json
{
  "kind": "structure"
}
```

Rules:

- Path `{id}` is the Source; the facade validates the Source, builds Job `input` (`source_id` from the path), sets `summary` / trigger fields, persists the Job, and enqueues the worker after commit.
- For database structure Jobs, the Source must be usable and have a secret; otherwise return a stable error.
- Response `202` returns the Job shape. Work runs asynchronously on a worker.

### `GET /sources/{id}/jobs`

Domain list semantics for “Jobs related to this Source” (for example Jobs whose `input.source_id` matches). Query params may include `status`, `kind`. This is a Source/metadata concern — not a reason to add Source columns on the Job record.

### `GET /jobs`

Platform-wide list (newest first). Query params may include `status`, `kind`. Create remains domain-facade-only.

### `GET /jobs/{id}/logs`

Returns `{ "job_id", "body", "updated_at" }` where `body` is the full multiline log text (empty string if none).

## 4. Errors

| code | When |
| --- | --- |
| `JOB_SOURCE_DISABLED` | Source not usable |
| `JOB_SECRET_MISSING` | No usable Source secret when required |
| `JOB_INPUT_INVALID` | Kind/input failed domain validation (including missing Source `engine`/`access`) |
| `JOB_NOT_CANCELLABLE` | Job already terminal |
| `JOB_ALREADY_ACTIVE` | Non-terminal structure Job already exists for this Source |
| `JOB_FAIL_SAFE` | Absent ratio exceeded fail-safe threshold; catalog unchanged |
| `JOB_COLLECT_FAILED` | Connector collect aborted; catalog unchanged |
| `JOB_ENDPOINT_FAILED` | Connector could not open the live endpoint |

Stable aliases of older draft codes (`INGESTION_*`) must not be reintroduced in new clients.

### Structure single-flight

Enqueue of `kind=structure` rejects with `JOB_ALREADY_ACTIVE` when the Source–Job facade finds a
non-terminal structure Job whose `input.source_id` matches the path Source. Authority is the
Postgres/memory Job table (queried via the facade), not Celery.

## 5. Slice Notes

- Slice A: `kind=structure` only on the Source facade for database Sources.
- Later slices/domains may add kinds and additional facade routes; unknown kind → `400` with stable code.
- Console: module id `jobs` is the global observe surface under the **Operations** nav group; structure enqueue lives on Sources. Permission `jobs:run`. Job lists (platform-wide and Source-scoped) omit a `result` column. Job detail may show **Job result** as uninterpreted JSON and does not unpack `class` or link to **Structure Diff**.

## 6. Non-Goals

- Global `POST /jobs` as the only create path in this phase (platform store may still be shared; HTTP create goes through domain facades)
- Promoting `source_id` to universal Job fields
- Promoting structure `class` onto Job list or detail chrome
- Streaming log push (SSE/WebSocket); Console polls `GET /jobs/{id}/logs`
