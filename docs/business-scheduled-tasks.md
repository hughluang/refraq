# refraq Business Rules: Scheduled Tasks

## 1. Scope

This document defines the platform **Scheduled Task** mechanism: a cadence definition that triggers work when due. Distinct from any **Job** instance. Not a product domain, not a Metadata business object, and not a field of **Source**. It is the only Console/HTTP/MCP path that mints domain **Jobs**.

Related boundaries:

- Terminology: `docs/glossary.md` and root `CONTEXT.md`.
- HTTP: `docs/api-contracts-schedules.md`.
- **Job** mechanism: `docs/business-jobs.md`.
- Metadata structure schedule facade (`POST/GET /sources/{id}/schedules`), Source create-time seed, hard-delete cascade, and mutating Source-update ensure: `docs/business-metadata.md`.
- Schedule-first minting: `docs/adr/0025-clock-first-structure-jobs.md`.
- Create-time seed: `docs/adr/0026-seed-structure-schedule-on-source-create.md`.

## 2. Object Model

Platform cadence definition. Does not contain extract SQL, transforms, or a dependency graph.

| Field | Notes |
| --- | --- |
| id / key | Stable id; structure key `structure:{source_id}:{schedule_id}` (unique per row) |
| name | Operator label (default `structure · {source_key}`; not unique per Source). PATCH empty/whitespace restores that default. |
| enabled | Pause automatic due-ticks without delete; run-now still allowed |
| cadence | Exactly one of `interval_seconds` or five-field `cron` |
| schedule_timezone | IANA; interprets cron wall clock; ignored for interval |
| last_run_at | Instant cursor of last consumed **due** fire (not a stored next-run; run-now does not move it) |

Rules:

- Operator identity is a closed **work kind** plus **target**. Public JSON does not include Celery `task_name` / `args_json`.
- Create via a **domain facade** (`POST /sources/{id}/schedules`), plus the create-time seed when registering a database **Source**, plus a mutating Source update when a database Source has zero structure schedules. Platform `GET/PATCH/DELETE /schedules` list and edit cadence / enabled / delete. No global create. No PUT replace.
- One Source may have several structure schedules. Job ↔ schedule association is `trigger_kind=schedule` and `trigger_ref` = schedule id, not Source single-flight.
- `PATCH` is RFC 5789 partial (cadence / timezone / enabled / name).
- Permission is `jobs:run`. No `schedules:*` key.
- System rows (`system=true`, e.g. stuck-Job reaper) stay enabled, are excluded from the default list and Console, and cannot be PATCHed, DELETEd, or run-now via product APIs. Tests may pass `?system=true` to list them.
- When due, Beat delivers the domain minting task keyed by the schedule row. That task mints a **Job** with `trigger_kind=schedule` and `trigger_ref` = Scheduled Task id (`created_by` null). System work (reaper) does not mint a Job.
- Operator run-now (`POST /schedules/{id}/run`) is the same firing for the Job (`trigger_kind=schedule`, `trigger_ref` = schedule id) with `created_by` = the operator. It does **not** update `last_run_at`. Disabled schedules accept run-now. System rows reject it.
- Overlap of structure work: `JOB_ALREADY_ACTIVE` is **structure** catalog-write serialization per Source, not a schedule lock. Beat swallows it (the schedule is not failed). Run-now returns it to the operator.
- Disabled / unusable / missing target: due tick skips (missing target is not a Celery failure).
- Product cron does **not** catch up missed slots. After downtime, wait for the next legal wall-clock slot at or after now (current minute if it matches and is later than `last_run_at`). Interval schedules (including the reaper) may fire one catch-up beat.
- MCP does not expose Scheduled Task CRUD or run-now in this slice.
- Platform operational work and domain cadences share the same **Scheduled Task** table.
- Operator management is of the **definition** (cadence, timezone, enabled, target payload) plus run-now; fired work is observed as **Jobs**, including `GET /schedules/{id}/jobs`.

## 3. Console

- Module id `schedules` lives in the **Operations** nav group (`operations`), list permission `jobs:run`: platform-wide domain schedules; edit cadence / enabled / delete; run-now; related Jobs. No system rows. No global create.
- Source “related schedules” is a **Source-scoped workbench** for that Source’s structure schedules: toolbar create plus the same row actions (enable/disable, edit, delete, run-now, related Jobs). `jobs:run` gates the surface.
- Console delete asks for confirmation; HTTP `DELETE` remains immediate.

## 4. Non-Goals

- Treating Scheduled Task as a Metadata domain entity or mounting the Schedules module under the `metadata` nav group
- A separate schedule product or new engine
- Global `POST /schedules` create
- Operator-supplied Celery `task_name`
- MCP schedule tools
- Catchup / backfill / RRule
- A `schedules:*` permission key
- Console display or pause of system schedules
- Using structure single-flight as the Job–schedule relationship
