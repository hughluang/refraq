# refraq API Contracts: Scheduled Tasks

## 1. Purpose

Contracts for operator management of domain **Scheduled Task** definitions (the schedule layer) and firing them.

Business rules: `docs/business-scheduled-tasks.md` (platform Scheduled Task) and `docs/business-metadata.md` §4.2 (Metadata structure **facade** onto schedules — not schedule ownership by Source), root `CONTEXT.md`, `docs/adr/0026-seed-structure-schedule-on-source-create.md`, `docs/adr/0027-running-time-limit-on-schedule.md`.
Auth: Session or User PAT. Permission: `jobs:run`.
Instants: [`docs/conventions-time.md`](conventions-time.md) (UTC `Z` on the wire).
HTTP protocol failures: [`docs/conventions-errors.md`](conventions-errors.md).

Create is domain-facade (`POST /sources/{id}/schedules`) plus the database Source create-time seed and a mutating Source update (zero structure schedules). Platform list/get/patch/delete do not create rows and do not accept Celery `task_name` or `owner_ref`. Mechanism responses do not invent Source shape; the Metadata facade adds `work_kind` / `target`.

## 2. Public shape

```json
{
  "id": "sched_01HZX",
  "key": "structure:src_mes_prod:sched_01HZX",
  "name": "structure · mes-prod",
  "enabled": true,
  "work_kind": "structure",
  "target": {
    "source_id": "src_mes_prod",
    "source_key": "mes-prod"
  },
  "interval_seconds": null,
  "cron": "0 2 * * *",
  "schedule_timezone": "UTC",
  "running_timeout_sec": null,
  "last_run_at": "2026-08-13T10:00:00Z",
  "next_run_at": "2026-08-14T02:00:00Z",
  "last_job": {
    "id": "job_01HZX",
    "status": "succeeded",
    "finished_at": "2026-08-13T10:05:00Z",
    "error_code": null
  },
  "created_at": "2026-08-13T10:00:00Z",
  "updated_at": "2026-08-13T10:00:00Z"
}
```

Rules:

- Public fields never include `task_name`, `args_json`, `kwargs_json`, `system`, or `owner_ref`.
- `work_kind` is the closed catalog of domain work (first slice: `structure`), filled by the Metadata facade. System / mechanism-only rows may return `work_kind` / `target` null.
- `target` is facade projection of the work target (structure: Source id/key), **not** proof that the schedule is owned by Source. `target.source_key` is present when the facade can resolve the Source; after Source hard-delete, matching schedules are withdrawn by `owner_ref` so orphans should not remain on product paths.
- Cadence is exactly one of `interval_seconds` (positive int) or five-field `cron`. `schedule_timezone` is IANA; ignored for interval.
- `running_timeout_sec` is the optional **Running Time Limit** (positive int seconds). Null / omit / seed = no control. Mint copies it onto the Job. PATCH of this field does not rewrite in-flight Jobs.
- `last_run_at` is the Instant cursor of the last **consumed due** mint (Clock Instant). Operator run-now does not change it. Cron cross-slot skip does not change it. It is not Console “last run”.
- `next_run_at` is the stored commitment Instant. Null when `enabled=false`. Due is `enabled` and `next_run_at <= now`. GET returns the stored value; it is not computed on read.
- `last_job` is an observation join to the latest Job with `trigger_kind=schedule` and `trigger_ref` = this schedule id (any status). Null when none. Not cached on the schedule row.
- Several structure schedules may target one Source. Key `structure:{source_id}:{schedule_id}` is a Metadata facade naming convention (unique per row), not a schedule-table Source FK.

## 3. Endpoints

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `POST` | `/sources/{id}/schedules` | `jobs:run` | Insert a structure schedule for this Source (operator create path) |
| `GET` | `/sources/{id}/schedules` | `jobs:run` | List structure schedules whose target is this Source (**Offset Page**) |
| `GET` | `/schedules` | `jobs:run` | Platform list (default excludes `system=true`; tests may pass `?system=true`; **Offset Page**) |
| `GET` | `/schedules/{id}` | `jobs:run` | Get by id (system rows visible for debug) |
| `PATCH` | `/schedules/{id}` | `jobs:run` | Partial update: `enabled`, cadence, `schedule_timezone`, `name`, `running_timeout_sec` |
| `DELETE` | `/schedules/{id}` | `jobs:run` | Delete definition; unfinished Jobs for this schedule immediately cancelled |
| `POST` | `/schedules/{id}/run` | `jobs:run` | Mint a Job now (does not move `last_run_at` / `next_run_at`) |
| `GET` | `/schedules/{id}/jobs` | `jobs:run` | Jobs this schedule minted — see `docs/api-contracts-jobs.md` |

There is no `PUT/GET/DELETE /sources/{id}/schedule` (singular replace).

### `POST /sources/{id}/schedules` body

```json
{
  "kind": "structure",
  "cron": "0 2 * * *",
  "interval_seconds": null,
  "schedule_timezone": "Asia/Shanghai",
  "running_timeout_sec": null,
  "enabled": true,
  "name": null
}
```

Rules:

- `kind` must be `structure` in this slice.
- Exactly one of `cron` or `interval_seconds`.
- `running_timeout_sec` omit or null = no control. A present non-positive value is rejected (`SCHEDULE_RUNNING_TIMEOUT_INVALID`).
- Path `{id}` is the Source on the **facade** route; the facade validates a database Source with access, writes a unique key, sets Celery kwargs (`source_id`, `schedule_id`) and opaque `owner_ref` internally. The schedule table does not gain a Source FK.
- Always insert: `201`. Cursor `last_run_at=now`; `next_run_at` = next legal slot after now (or null if created disabled).
- Response `{ "schedule": { … } }` with `source_key` filled.

### `POST /schedules/{id}/run`

Empty body. `202` `{ "job": { … } }` (Job shape). `trigger_kind=schedule`, `trigger_ref` = schedule id, `created_by_user_id` = operator, `scheduled_for` null. Disabled schedules are allowed. System schedules → `SCHEDULE_SYSTEM_IMMUTABLE`. Always mints a Job — Source busy / disabled is not a schedule HTTP conflict. Does not update `last_run_at` / `next_run_at`.

### `PATCH /schedules/{id}` body

Any subset of `enabled`, `name`, `cron`, `interval_seconds`, `schedule_timezone`, `running_timeout_sec`. Setting `cron` clears `interval_seconds` and vice versa. Sending both non-null is rejected. A present `schedule_timezone` (including empty or null) is validated as IANA; omission leaves the stored zone. Present `running_timeout_sec` null clears to no-control; omission leaves the stored value; a present non-positive value is rejected. Empty or whitespace `name` restores the default `structure · {source_key}`. System rows are rejected.

- `enabled=false` → `next_run_at` null immediately; already queued/running Jobs keep running.
- `enabled=true` → recompute `next_run_at` from now (no pause catch-up).
- Cadence / timezone change → rewrite `next_run_at` immediately (while enabled); do not cancel already-minted Jobs.

### `GET /schedules`

**Offset Page** (newest first: `created_at DESC`, `id DESC`). Query params: `limit` (default **50**, max **200**), `offset` (default **0**), `system` (default `false`; `true` includes system rows for tests / debug).

Response: `{ "items": […], "total": N, "limit": L, "offset": O }`. `total` is the filtered set.

### `GET /sources/{id}/schedules`

Same **Offset Page** envelope, defaults, max, and ordering. Scoped to structure schedules whose `owner_ref` is this Source. Missing Source → `SOURCE_NOT_FOUND`. Empty page is `200` with `items: []` (allowed after the operator deletes the last schedule; a newly created database Source has one seed).

### `DELETE`

`204` empty body. Unfinished Jobs for this schedule are immediately cancelled (queued also revoked). Historical Jobs remain.

## 4. Errors

| code | When |
| --- | --- |
| `SCHEDULE_NOT_FOUND` | No Scheduled Task for this id |
| `SCHEDULE_SYSTEM_IMMUTABLE` | PATCH/DELETE/run-now of a `system=true` row |
| `SCHEDULE_CADENCE_INVALID` | Neither or both cadence fields; invalid cron; unknown IANA zone; non-positive interval |
| `SCHEDULE_RUNNING_TIMEOUT_INVALID` | Present `running_timeout_sec` is not a positive integer |
| `SCHEDULE_KIND_INVALID` | POST `kind` is not in the closed catalog |
| `JOB_INPUT_INVALID` | Structure schedule requires a database Source with access |
| `SOURCE_NOT_FOUND` | Facade path Source missing. Source delete withdraws structure schedules by `owner_ref` so orphans should not remain. |

`JOB_ALREADY_ACTIVE` and `JOB_SOURCE_DISABLED` are Job execution / domain errors, not schedule mint HTTP codes.

## 5. Console

- Module id `schedules` (`operations` group, list permission `jobs:run`): platform-wide domain schedules; edit cadence / enabled / delete; run-now; related Jobs. No system rows. No global create.
- Sources: related-schedules **workbench** at `/console/sources/:id/schedules` — toolbar create plus the same row actions as Operations (enable/disable, edit, delete, run-now, related Jobs). Console delete asks for confirmation; HTTP `DELETE` remains immediate.
- Do not label `last_run_at` as Last run; show `last_job` for observation and `next_run_at` for commitment. Disabled → paused (not “unknown next”).
- Create/edit may set optional **Running Time Limit**. Empty = no control. No new schedule-list column in this slice. Job detail may show the minted snapshot when non-null.

## 6. Non-Goals

- Global `POST /schedules` create
- Operator-supplied Celery `task_name` or product-writable `owner_ref`
- MCP schedule tools
- Catchup / backfill / RRule
- PUT replace of “the” structure schedule per Source
