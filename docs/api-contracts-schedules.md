# refraq API Contracts: Scheduled Tasks

## 1. Purpose

Contracts for operator management of domain **Scheduled Task** definitions (the clock layer).

Business rules: `docs/business-scheduled-tasks.md` (platform clock) and `docs/business-metadata.md` §4.2 (structure Source facade), root `CONTEXT.md`.
Auth: Session or User PAT. Permission: `jobs:run`.
Instants: [`docs/conventions-time.md`](conventions-time.md) (UTC `Z` on the wire).
HTTP protocol failures: [`docs/conventions-errors.md`](conventions-errors.md).

Create is domain-facade only. Platform list/get/patch/delete do not create rows and do not accept Celery `task_name`.

## 2. Public shape

```json
{
  "id": "sched_01HZX",
  "key": "structure:src_mes_prod",
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
- `target.source_key` is present when the facade can resolve the Source; platform list/get/patch fill it the same way when the Source still exists (`null` after orphaning is not expected in product paths because hard-delete cascades the clock).
- Cadence is exactly one of `interval_seconds` (positive int) or five-field `cron`. `schedule_timezone` is IANA; ignored for interval.
- `last_run_at` is an Instant cursor (last consumed fire), not a stored next-run.

## 3. Endpoints

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `PUT` | `/sources/{id}/schedule` | `jobs:run` | Create or replace this Source's structure clock (domain facade; only human create path) |
| `GET` | `/sources/{id}/schedule` | `jobs:run` | Get this Source's structure clock |
| `DELETE` | `/sources/{id}/schedule` | `jobs:run` | Delete this Source's structure clock |
| `GET` | `/schedules` | `jobs:run` | Platform list (default excludes `system=true`; tests may pass `?system=true`) |
| `GET` | `/schedules/{id}` | `jobs:run` | Get by id (system rows visible for debug) |
| `PATCH` | `/schedules/{id}` | `jobs:run` | Partial update: `enabled`, cadence, `schedule_timezone`, `name` |
| `DELETE` | `/schedules/{id}` | `jobs:run` | Delete (non-system) |

### `PUT /sources/{id}/schedule` body

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
- Path `{id}` is the Source; the facade validates a database Source with access, writes key `structure:{source_id}`, and sets Celery kwargs internally.
- Create (no existing row): `201`, `last_run_at=now` (cursor; first fire is the next future wall-clock slot).
- Replace (row exists): `200`; cadence / enabled / timezone / name replaced; `last_run_at` cursor kept.
- Response `{ "schedule": { … } }` with `source_key` filled.

### `PATCH /schedules/{id}` body

Any subset of `enabled`, `name`, `cron`, `interval_seconds`, `schedule_timezone`. Setting `cron` clears `interval_seconds` and vice versa. Sending both non-null is rejected. A present `schedule_timezone` (including empty or null) is validated as IANA; omission leaves the stored zone. System rows are rejected.

### `GET /schedules`

Newest `created_at` first. Default `include_system=false`. Query `system=true` includes system rows (tests / debug).

### `DELETE`

`204` empty body.

## 4. Errors

| code | When |
| --- | --- |
| `SCHEDULE_NOT_FOUND` | No Scheduled Task for this id or Source |
| `SCHEDULE_SYSTEM_IMMUTABLE` | PATCH/DELETE of a `system=true` row |
| `SCHEDULE_CADENCE_INVALID` | Neither or both cadence fields; invalid cron; unknown IANA zone; non-positive interval |
| `SCHEDULE_KIND_INVALID` | PUT `kind` is not in the closed catalog |
| `JOB_SOURCE_DISABLED` | Not used on PUT (disabled Source may still hold a clock); tick skips enqueue |
| `JOB_INPUT_INVALID` | Structure clock requires a database Source with access |
| `SOURCE_NOT_FOUND` | Facade path Source missing. Beat tick for a missing Source skips (not a Celery failure). Hard-delete cascades the structure clock so orphans should not remain. |

## 5. Console

- Module id `schedules` (`operations` group, list permission `jobs:run`): global domain clocks; edit cadence / enabled / delete. No system rows. No “run now”.
- Sources: **Run structure** (Job enqueue) plus **Schedule** (PUT this Source's clock).

## 6. Non-Goals

- Global `POST /schedules` create
- Operator-supplied Celery `task_name`
- MCP schedule tools
- Catchup / backfill / RRule
- Multiple structure clocks per Source
