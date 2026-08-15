# refraq API Contracts: Scheduled Tasks

## 1. Purpose

Contracts for operator management of domain **Scheduled Task** definitions (the schedule layer) and firing them.

Business rules: `docs/business-scheduled-tasks.md` (platform Scheduled Task) and `docs/business-metadata.md` §4.2 (structure Source facade), root `CONTEXT.md`, `docs/adr/0026-seed-structure-schedule-on-source-create.md`.
Auth: Session or User PAT. Permission: `jobs:run`.
Instants: [`docs/conventions-time.md`](conventions-time.md) (UTC `Z` on the wire).
HTTP protocol failures: [`docs/conventions-errors.md`](conventions-errors.md).

Create is domain-facade (`POST /sources/{id}/schedules`) plus the database Source create-time seed and a mutating Source update (zero structure schedules). Platform list/get/patch/delete do not create rows and do not accept Celery `task_name`.

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
  "last_run_at": "2026-08-13T10:00:00Z",
  "created_at": "2026-08-13T10:00:00Z",
  "updated_at": "2026-08-13T10:00:00Z"
}
```

Rules:

- Public fields never include `task_name`, `args_json`, `kwargs_json`, or `system`.
- `work_kind` is the closed catalog of domain work (first slice: `structure`). System rows are not in the default list; a debug GET may return `work_kind` / `target` null.
- `target.source_key` is present when the facade can resolve the Source; platform list/get/patch fill it the same way when the Source still exists (`null` after orphaning is not expected in product paths because hard-delete cascades schedules).
- Cadence is exactly one of `interval_seconds` (positive int) or five-field `cron`. `schedule_timezone` is IANA; ignored for interval.
- `last_run_at` is an Instant cursor (last consumed **due** fire), not a stored next-run. Operator run-now does not change it.
- Several structure schedules may target one Source. Key is unique per row: `structure:{source_id}:{schedule_id}`.

## 3. Endpoints

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `POST` | `/sources/{id}/schedules` | `jobs:run` | Insert a structure schedule for this Source (operator create path) |
| `GET` | `/sources/{id}/schedules` | `jobs:run` | List structure schedules whose target is this Source |
| `GET` | `/schedules` | `jobs:run` | Platform list (default excludes `system=true`; tests may pass `?system=true`) |
| `GET` | `/schedules/{id}` | `jobs:run` | Get by id (system rows visible for debug) |
| `PATCH` | `/schedules/{id}` | `jobs:run` | Partial update: `enabled`, cadence, `schedule_timezone`, `name` |
| `DELETE` | `/schedules/{id}` | `jobs:run` | Delete (non-system) |
| `POST` | `/schedules/{id}/run` | `jobs:run` | Mint a Job now (does not move `last_run_at`) |
| `GET` | `/schedules/{id}/jobs` | `jobs:run` | Jobs this schedule minted — see `docs/api-contracts-jobs.md` |

There is no `PUT/GET/DELETE /sources/{id}/schedule` (singular replace).

### `POST /sources/{id}/schedules` body

```json
{
  "kind": "structure",
  "cron": "0 2 * * *",
  "interval_seconds": null,
  "schedule_timezone": "Asia/Shanghai",
  "enabled": true,
  "name": null
}
```

Rules:

- `kind` must be `structure` in this slice.
- Exactly one of `cron` or `interval_seconds`.
- Path `{id}` is the Source; the facade validates a database Source with access, writes a unique key, and sets Celery kwargs (`source_id`, `schedule_id`) internally.
- Always insert: `201`, `last_run_at=now` (cursor; first due fire is the next future wall-clock slot).
- Response `{ "schedule": { … } }` with `source_key` filled.

### `POST /schedules/{id}/run`

Empty body. `202` `{ "job": { … } }` (Job shape). `trigger_kind=schedule`, `trigger_ref` = schedule id, `created_by_user_id` = operator. Disabled schedules are allowed. System schedules → `SCHEDULE_SYSTEM_IMMUTABLE`. Structure single-flight → `JOB_ALREADY_ACTIVE` (not swallowed). Does not update `last_run_at`.

### `PATCH /schedules/{id}` body

Any subset of `enabled`, `name`, `cron`, `interval_seconds`, `schedule_timezone`. Setting `cron` clears `interval_seconds` and vice versa. Sending both non-null is rejected. A present `schedule_timezone` (including empty or null) is validated as IANA; omission leaves the stored zone. Empty or whitespace `name` restores the default `structure · {source_key}`. System rows are rejected.

### `GET /schedules`

Newest `created_at` first. Default `include_system=false`. Query `system=true` includes system rows (tests / debug).

### `GET /sources/{id}/schedules`

Same public shape, filtered to schedules whose target is this Source. Missing Source → `SOURCE_NOT_FOUND`. Empty list is `200` with `items: []` (allowed after the operator deletes the last schedule; a newly created database Source has one seed).

### `DELETE`

`204` empty body.

## 4. Errors

| code | When |
| --- | --- |
| `SCHEDULE_NOT_FOUND` | No Scheduled Task for this id |
| `SCHEDULE_SYSTEM_IMMUTABLE` | PATCH/DELETE/run-now of a `system=true` row |
| `SCHEDULE_CADENCE_INVALID` | Neither or both cadence fields; invalid cron; unknown IANA zone; non-positive interval |
| `SCHEDULE_KIND_INVALID` | POST `kind` is not in the closed catalog |
| `JOB_SOURCE_DISABLED` | Not used on create (disabled Source may still hold a schedule); due tick skips enqueue; run-now returns this |
| `JOB_ALREADY_ACTIVE` | Run-now when a non-terminal structure Job exists for the target Source |
| `JOB_INPUT_INVALID` | Structure schedule requires a database Source with access |
| `SOURCE_NOT_FOUND` | Facade path Source missing. Beat tick for a missing Source skips (not a Celery failure). Hard-delete cascades structure schedules so orphans should not remain. |

## 5. Console

- Module id `schedules` (`operations` group, list permission `jobs:run`): platform-wide domain schedules; edit cadence / enabled / delete; run-now; related Jobs. No system rows. No global create.
- Sources: related-schedules **workbench** at `/console/sources/:id/schedules` — toolbar create plus the same row actions as Operations (enable/disable, edit, delete, run-now, related Jobs). Console delete asks for confirmation; HTTP `DELETE` remains immediate.

## 6. Non-Goals

- Global `POST /schedules` create
- Operator-supplied Celery `task_name`
- MCP schedule tools
- Catchup / backfill / RRule
- PUT replace of “the” structure schedule per Source
