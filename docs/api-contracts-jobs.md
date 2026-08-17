# refraq API Contracts: Jobs

## 1. Purpose

Contracts for observing platform **Jobs** (list/get/logs/cancel) and presenting trigger fields. Structure Jobs are minted only via **Scheduled Task** (`docs/api-contracts-schedules.md`).

Business rules: `docs/business-jobs.md` (platform Job) and `docs/business-metadata.md` §4.2 (structure via schedules), root `CONTEXT.md`.
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
  "trigger_kind": "schedule",
  "trigger_ref": "sched_01HZX",
  "trigger_actor_name": null,
  "trigger_schedule_name": "structure · mes-prod",
  "scheduled_for": "2026-08-05T02:00:00Z",
  "running_timeout_sec": null,
  "created_by_user_id": null,
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
- **`trigger_kind`** / **`trigger_ref`** describe how the Job was started (`user` | `schedule` | `mcp` | `system`, plus optional id). Structure minting in this phase is `schedule` with `trigger_ref` = Scheduled Task id. Historical `user` / `mcp` rows may remain. Coexist with **`created_by_user_id`** (operator run-now sets created_by; Beat leaves it null).
- **`scheduled_for`** is the due-slot Instant consumed for an automatic fire; null for operator run-now. Due mint is idempotent on `(trigger_ref, scheduled_for)` when `scheduled_for` is not null.
- **`running_timeout_sec`** is the minted **Running Time Limit** snapshot (nullable positive seconds). Null = the reaper does not mark `JOB_RUNNING_TIMEOUT`. Copied from the **Scheduled Task** at mint; not a live read. Job lists do not add a column; Job detail may show it when non-null.
- **`trigger_actor_name`** is presentation-only: when `trigger_kind` is `user` and `trigger_ref` resolves to a known User, it is that User's `display_name`; otherwise `null`.
- **`trigger_schedule_name`** is presentation-only: when `trigger_kind` is `schedule` and `trigger_ref` resolves to a known Scheduled Task, it is that schedule's `name`. Otherwise `null` (deleted schedule). Not an identity field — **`trigger_ref`** remains authoritative. Console Triggered-by uses this in the same column as `trigger_actor_name` (missing name falls back to `trigger_ref`).
- Operator-visible run log lives on the Job row as **`log_body`** (newline-separated lines). List/get Job shapes do **not** include full `log_body`; use `GET /jobs/{id}/logs`. Optional **`log_updated_at`** may appear on JobOut.
- No universal `source_id` columns on Job; domain ids appear inside `input` when the kind requires them.
- Slice A `kind=structure` for `kind=database` Sources: `input` includes `source_id` only. Workers load reachability from the Source.
- Entering execution requires a `queued → running` claim. Broker redelivery of a non-queued Job must not re-run domain work.
- **`JOB_WORKER_LOST`**: occupancy stale (worker gone). **`JOB_RUNNING_TIMEOUT`**: still occupied, the Job snapshot `running_timeout_sec` is set, and elapsed `started_at` exceeds that snapshot. Distinct codes; both leave status `failed`. Cooperative: the worker process is not killed; the structure runner does not apply a catalog snapshot after the stamp. Lost-detection SLA assumes Beat is alive; if Beat is down, occupancy reaping stops — API alone does not clear a false `RUNNING`.

## 3. Endpoints

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `GET` | `/jobs` | `jobs:run` | Platform list all Jobs (`status`, `kind` query filters) |
| `GET` | `/jobs/{id}` | `jobs:run` | Get Job by id |
| `GET` | `/jobs/{id}/logs` | `jobs:run` | Get Job `log_body` (`{ job_id, body, updated_at }`) |
| `POST` | `/jobs/{id}/cancel` | `jobs:run` | Cancel if not terminal |
| `GET` | `/schedules/{id}/jobs` | `jobs:run` | Jobs this schedule minted (`trigger_kind=schedule` and `trigger_ref=id`) |

Structure minting is `POST /schedules/{id}/run` (`docs/api-contracts-schedules.md`). There is no `POST /sources/{id}/jobs` and no `GET /sources/{id}/jobs`.

### `GET /jobs`

Platform-wide list (newest first). Query params may include `status`, `kind`.

### `GET /schedules/{id}/jobs`

Jobs whose trigger points at this Scheduled Task. Missing schedule → `SCHEDULE_NOT_FOUND`. Query params may include `status`, `kind`. Historical user/mcp Jobs are not included.

### `GET /jobs/{id}/logs`

Returns `{ "job_id", "body", "updated_at" }` where `body` is the full multiline log text (empty string if none).

## 4. Errors

| code | When |
| --- | --- |
| `JOB_SOURCE_DISABLED` | Structure Job found the Source not usable when executing |
| `JOB_SECRET_MISSING` | No usable Source secret when required |
| `JOB_INPUT_INVALID` | Kind/input failed domain validation (including missing Source `engine`/`access`) |
| `JOB_NOT_CANCELLABLE` | Job already terminal |
| `JOB_ALREADY_ACTIVE` | Structure Job execution found another non-terminal structure Job for the same Source (catalog-write serialization). Not a schedule mint / HTTP conflict |
| `JOB_WORKER_LOST` | Occupancy stale; worker gone |
| `JOB_RUNNING_TIMEOUT` | Job snapshot `running_timeout_sec` is set and elapsed while still occupied |
| `JOB_FAIL_SAFE` | Absent ratio exceeded fail-safe threshold; catalog unchanged |
| `JOB_COLLECT_FAILED` | Connector collect aborted; catalog unchanged |
| `JOB_ENDPOINT_FAILED` | Connector could not open the live endpoint |
| `SCHEDULE_NOT_FOUND` | `GET /schedules/{id}/jobs` or run-now on a missing schedule |
| `SCHEDULE_SYSTEM_IMMUTABLE` | run-now on a system schedule |

Stable aliases of older draft codes (`INGESTION_*`) must not be reintroduced in new clients.

### Structure single-flight

At most one non-terminal `kind=structure` Job may **run** catalog writes per Source. Enforced when the structure Job **executes**: if another running structure Job for the same `input.source_id` already wins, this Job ends `failed` with `JOB_ALREADY_ACTIVE`. Authority is the Job table, not Celery and not the schedule. The **Scheduled Task** always mints; Source busy is never a schedule mint skip or HTTP 409.

## 5. Slice Notes

- Slice A: `kind=structure` only, minted by structure schedules for database Sources.
- Later slices/domains may add kinds; unknown kind → `400` with stable code.
- Console: module id `jobs` is the global observe surface under the **Operations** nav group. Permission `jobs:run`. Job lists omit a `result` column. Job detail may show **Job result** as uninterpreted JSON and does not unpack `class` or link to **Structure Diff**. Triggered-by is one column.

## 6. Non-Goals

- Global `POST /jobs` create
- Promoting `source_id` to universal Job fields
- Promoting structure `class` onto Job list or detail chrome
- Streaming log push (SSE/WebSocket); Console polls `GET /jobs/{id}/logs`
- Source-scoped Job HTTP
