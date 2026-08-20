# refraq Business Rules: Jobs

## 1. Scope

This document defines the platform **Job** mechanism: a durable asynchronous execution record with an observable lifecycle. It is not a Metadata business object and not owned by **Source**.

Related boundaries:

- Terminology: `docs/glossary.md` and root `CONTEXT.md`.
- Job shape: `docs/adr/0008-job-generic-input.md`.
- Queue runtime: `docs/adr/0004-redis-queue-for-ingestion.md`, `docs/adr/0006-celery-platform-async-runtime.md`.
- HTTP: `docs/api-contracts-jobs.md`.
- **Scheduled Task** (the schedule that mints domain Jobs): `docs/business-scheduled-tasks.md`.
- Metadata **structure** / join-detection kinds, Source facade, **Kind execution lock**, and **Structure Diff**: `docs/business-metadata.md`.
- Schedule-first minting: `docs/adr/0025-clock-first-structure-jobs.md`.
- **Running Time Limit** (schedule definition, Job snapshot): `docs/adr/0027-running-time-limit-on-schedule.md`.

## 2. Object Model

Platform durable asynchronous execution. Each product domain interprets `kind` and `input` for its own tasks. Metadata structure collection is one Job `kind`, not the definition of Job.

| Field | Notes |
| --- | --- |
| id | Job id |
| kind | Discriminator; domains add values (`structure` \| `join_detection` \| …) |
| status | `queued` \| `running` \| `succeeded` \| `failed` \| `cancelled` |
| input | Generic object; domain interprets per `kind` |
| result | Nullable generic JSON; platform does not interpret. Written only on successful terminal. Other kinds stay `null` (not `{}`) |
| summary | Human-readable enqueue snapshot of the work target; not a domain foreign key |
| trigger | `trigger_kind` / `trigger_ref` — how the Job was started |
| trigger presentation | `trigger_actor_name` (User display name) and `trigger_schedule_name` (**Scheduled Task** name); not identity |
| scheduled_for | Due-slot Instant consumed for an automatic fire; null for operator run-now. Idempotency key with `trigger_ref` when not null |
| running_timeout_sec | Minted **Running Time Limit** snapshot (nullable positive seconds). Null = reaper does not mark `JOB_RUNNING_TIMEOUT`. Not a live read of the schedule |
| created_by | User id (null when Beat fires; set when an operator run-now fires the schedule) |
| timestamps / error summary / log | Operational visibility |

Rules:

- Job is **not** owned by Source. Do not treat `source_id` as a universal Job column — it lives in `input` when required.
- Structure and join-detection **Jobs** are minted only by a **Scheduled Task** (due tick or operator run-now). There is no Source HTTP enqueue and no MCP enqueue in this phase. Platform-wide observe uses `GET /jobs` and `GET /jobs/{id}` / `.../logs` / cancel. Related Jobs for a schedule: `GET /schedules/{id}/jobs`. There is no global `POST /jobs` create.
- Entering execution requires a `queued → running` claim (CAS). Broker redelivery of a non-queued Job must not re-run domain work.
- An unexpected runner abort (the Celery task raises) must terminalize the Job `failed` with `JOB_EXECUTION_FAILED`. Occupancy renews every still-`running` claim for a living worker identity; leaving the row `running` after the task is gone keeps a false `RUNNING` until that worker process dies.
- **Occupancy** (Job primitive; shares Beat with schedules only because the platform has one periodic clock): the worker renews declarations on its running Jobs; a system Scheduled Task marks stale occupancy `JOB_WORKER_LOST`. The stale window is the `job_lost_detection_sec` **System Parameter** (seed 60). Widening is live; tightening waits one old renew interval (`max(5, previous/3)` s) before the reaper cutoff shrinks. Lost-detection SLA assumes Beat is alive: if Beat is down, occupancy reaping stops; bringing up the API alone does not clear a false `RUNNING`. On worker start, abandon leftover running claims for this worker identity immediately (no freshness filter) as `JOB_WORKER_LOST` — not a global reap; a same-identity restart must not treat the previous attempt as still running.
- **Running Time Limit** is defined on the **Scheduled Task**, not as a Job or env primitive. Mint copies `running_timeout_sec` onto the Job. The same system reaper marks a still-occupied run `JOB_RUNNING_TIMEOUT` when that snapshot is not null and `started_at` is older than the snapshot. Null snapshot: skip. Cooperative CAS `running → failed`; not process kill. The structure runner treats a terminal Job (`cancelled` or `failed`) as stop and does not apply a catalog snapshot or persist a **Structure Diff** after that stamp. Collect already in flight may finish. PATCH of the schedule field does not rewrite in-flight Jobs.
- **Kind execution lock** / Source usability are Metadata execution rules on structure and join-detection Jobs, not Job-table ownership by Source and not schedule mint gates.
- Jobs are durable records; queue transport is Redis-backed via Celery.
- Observing Jobs uses public Job fields only. Kind-specific outcome fields stay inside **Job result** (and on domain records such as **Structure Diff**), not as public Job attributes.
- Job lists do not include **Job result** as a column. Job detail may present it as the uninterpreted JSON document and does not unpack kind-specific keys into Job chrome.
- Console Triggered-by is one column: User → display name; schedule → `trigger_schedule_name` (fallback `trigger_ref`). Do not put schedule name into `trigger_actor_name`.
- Permission is `jobs:run` (run-now / cancel; list/view Jobs; same key also manages domain **Scheduled Task** definitions — see `docs/business-scheduled-tasks.md`). There is no separate `jobs:read` key in this slice.

## 3. Console

- Module id `jobs` lives in the **Operations** nav group (`operations`), list permission `jobs:run`: global Job list and observe (logs/detail).
- Structure minting lives on **Scheduled Task**. Source related-schedules workbench (`/console/sources/:id/schedules`) creates schedules and can enable/disable, edit, delete, run-now, and open related Jobs; Operations `schedules` is the platform-wide list with the same management actions and no global create. Not on the global Jobs page and not as Source “Run structure”.

## 4. Non-Goals

- Treating Job as a Metadata domain entity or mounting the Jobs module under the `metadata` nav group
- Global `POST /jobs` as the only create path
- Promoting domain foreign keys onto universal Job fields
- A `schedules:*` permission key (schedule management shares `jobs:run`)
- Source-scoped Job list HTTP (`GET /sources/{id}/jobs`)
