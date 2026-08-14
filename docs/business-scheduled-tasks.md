# refraq Business Rules: Scheduled Tasks

## 1. Scope

This document defines the platform **Scheduled Task** mechanism: a cadence definition (the clock) that triggers work when due. Distinct from any **Job** instance. Not a product domain, not a Metadata business object, and not a field of **Source**.

Related boundaries:

- Terminology: `docs/glossary.md` and root `CONTEXT.md`.
- HTTP: `docs/api-contracts-schedules.md`.
- **Job** mechanism: `docs/business-jobs.md`.
- Metadata structure clock facade (`PUT /sources/{id}/schedule`) and hard-delete cascade: `docs/business-metadata.md`.

## 2. Object Model

Platform cadence definition. Does not contain extract SQL, transforms, or a dependency graph.

| Field | Notes |
| --- | --- |
| id / key | Stable id; domain key convention for structure: `structure:{source_id}` |
| name | Operator label |
| enabled | Pause without delete |
| cadence | Exactly one of `interval_seconds` or five-field `cron` |
| schedule_timezone | IANA; interprets cron wall clock; ignored for interval |
| last_run_at | Instant cursor of last consumed fire (not a stored next-run) |

Rules:

- Operator identity is a closed **work kind** plus **target**. Public JSON does not include Celery `task_name` / `args_json`.
- Create only via a **domain facade**. Platform `GET/PATCH/DELETE /schedules` list and edit cadence / enabled / delete. No global create.
- `PATCH` is RFC 5789 partial (cadence / timezone / enabled / name).
- Permission is `jobs:run`. No `schedules:*` key.
- System rows (`system=true`, e.g. stuck-Job reaper) stay enabled, are excluded from the default list and Console, and cannot be PATCHed or DELETEd via product APIs. Tests may pass `?system=true` to list them.
- When due, Beat sends a lightweight `enqueue_*` task. Domain work mints a **Job** with `trigger_kind=schedule` and `trigger_ref` = Scheduled Task id (`created_by` null). System work (reaper) does not mint a Job.
- Overlap: swallow `JOB_ALREADY_ACTIVE`; the schedule is not failed. Disabled / unusable / missing target: skip the tick (same rejection family as manual enqueue; missing target is not a Celery failure).
- Product cron does **not** catch up missed slots. After downtime, wait for the next legal wall-clock slot at or after now (current minute if it matches and is later than `last_run_at`). Interval schedules (including the reaper) may fire one catch-up beat.
- Manual Job enqueue is not a **Scheduled Task** firing; it remains `trigger_kind=user` and does not change cadence. Schedules have no “run now”.
- MCP does not expose Scheduled Task CRUD in this slice.
- Platform operational work and domain cadences share the same **Scheduled Task** table.
- Operator management is of the **definition** (cadence, timezone, enabled, target payload), not a second execution lifecycle beside **Job**.

## 3. Console

- Module id `schedules` lives in the **Operations** nav group (`operations`), list permission `jobs:run`: global domain clocks; edit cadence / enabled / delete. No system rows. No “run now”.
- Create lives on domain facades (for structure: the Sources module).

## 4. Non-Goals

- Treating Scheduled Task as a Metadata domain entity or mounting the Schedules module under the `metadata` nav group
- A separate schedule product or new engine
- Global `POST /schedules` create
- Operator-supplied Celery `task_name`
- MCP schedule tools
- Catchup / backfill / RRule
- A `schedules:*` permission key
- Console display or pause of system schedules
