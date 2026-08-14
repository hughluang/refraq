# refraq Business Rules: Jobs

## 1. Scope

This document defines the platform **Job** mechanism: a durable asynchronous execution record with an observable lifecycle. It is not a Metadata business object and not owned by **Source**.

Related boundaries:

- Terminology: `docs/glossary.md` and root `CONTEXT.md`.
- Job shape: `docs/adr/0008-job-generic-input.md`.
- Queue runtime: `docs/adr/0004-redis-queue-for-ingestion.md`, `docs/adr/0006-celery-platform-async-runtime.md`.
- HTTP: `docs/api-contracts-jobs.md`.
- **Scheduled Task** (the clock that may enqueue Jobs): `docs/business-scheduled-tasks.md`.
- Metadata **structure** kind, Source facade, single-flight, and **Structure Diff**: `docs/business-metadata.md`.

## 2. Object Model

Platform durable asynchronous execution. Each product domain interprets `kind` and `input` for its own tasks. Metadata structure collection is one Job `kind`, not the definition of Job.

| Field | Notes |
| --- | --- |
| id | Job id |
| kind | Discriminator; domains add values (`structure` \| `semantics_refresh` \| …) |
| status | `queued` \| `running` \| `succeeded` \| `failed` \| `cancelled` |
| input | Generic object; domain interprets per `kind` |
| result | Nullable generic JSON; platform does not interpret. Written only on successful terminal. Other kinds stay `null` (not `{}`) |
| summary | Human-readable enqueue snapshot of the work target; not a domain foreign key |
| trigger | `trigger_kind` / `trigger_ref` — how the Job was started |
| created_by | User id (null when a **Scheduled Task** fires) |
| timestamps / error summary / log | Operational visibility |

Rules:

- Job is **not** owned by Source. Do not treat `source_id` as a universal Job column — it lives in `input` when required.
- Domains expose enqueue and list facades for work that matters to them. Platform-wide observe uses `GET /jobs` and `GET /jobs/{id}` / `.../logs` / cancel. There is no global `POST /jobs` create in this phase.
- Jobs are durable records; queue transport is Redis-backed via Celery.
- Observing Jobs (list or detail, platform-wide or domain-scoped) uses public Job fields only. Kind-specific outcome fields stay inside **Job result** (and on domain records such as **Structure Diff**), not as public Job attributes.
- Job lists do not include **Job result** as a column. Job detail may present it as the uninterpreted JSON document and does not unpack kind-specific keys into Job chrome.
- Permission is `jobs:run` (enqueue/cancel via domain facades; list/view Jobs; same key also manages domain **Scheduled Task** definitions — see `docs/business-scheduled-tasks.md`). There is no separate `jobs:read` key in this slice.

## 3. Console

- Module id `jobs` lives in the **Operations** nav group (`operations`), list permission `jobs:run`: global Job list and observe (logs/detail).
- Enqueue lives on domain facades (for structure: the Sources module), not on the global Jobs page.

## 4. Non-Goals

- Treating Job as a Metadata domain entity or mounting the Jobs module under the `metadata` nav group
- Global `POST /jobs` as the only create path
- Promoting domain foreign keys onto universal Job fields
- A `schedules:*` permission key (clock management shares `jobs:run`)
