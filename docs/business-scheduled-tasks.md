# refraq Business Rules: Scheduled Tasks

## 1. Scope

This document defines the platform **Scheduled Task** mechanism: the scheduling foundation that turns a cadence intent into observable, withdrawable **Job** attempts. Distinct from any **Job** instance. Not a product domain, not a Metadata business object, and not a field of **Source**. It is the only Console/HTTP/MCP path that mints domain **Jobs**.

Related boundaries:

- Terminology: `docs/glossary.md` and root `CONTEXT.md`.
- HTTP: `docs/api-contracts-schedules.md`.
- **Job** mechanism: `docs/business-jobs.md`.
- Metadata structure schedule **facade** (`POST/GET /sources/{id}/schedules`), Source create-time seed, **owner_ref** withdraw on Source delete, and mutating Source-update ensure: `docs/business-metadata.md`.
- Schedule-first minting: `docs/adr/0025-clock-first-structure-jobs.md`.
- Create-time seed: `docs/adr/0026-seed-structure-schedule-on-source-create.md`.
- **Running Time Limit**: `docs/adr/0027-running-time-limit-on-schedule.md`.
- Time / due rules: `docs/conventions-time.md`.

## 2. Service outline

```text
Intent (definition: cadence / timezone / enabled / optional Running Time Limit / opaque owner_ref)
  → Commitment (stored next_run_at; not a debt ledger)
    → Due (consuming a tick = minting one Job, one atomic event)
      → Attempt fate (queued → running → terminal)  ← Job
  Intent change: cadence rewrite only rewrites commitment;
  pause clears commitment; withdraw cancels unfinished attempts
```

Three verbs:

1. **Due event is atomic** — a tick is consumed only when a Job attempt exists for that tick. Skipping a missed cron slot only advances commitment (`next_run_at`), not `last_run_at`.
2. **Current wall-clock slot still due** — if the current legal slot (minute-aligned, expression still matches) has not been consumed, mint that tick. Do not treat every `next_run_at < now` as expired.
3. **Pause ≠ in-flight cancel ≠ withdraw** — pause clears commitment; an already-minted Job is not cancelled by pause; withdraw / delete immediately terminalizes unfinished Jobs.

## 3. Object Model

Platform cadence definition. Does not contain extract SQL, transforms, a dependency graph, or a **Source** foreign key. Dispatched work may later be structure collection, a script, or a DAG/Workflow; those graphs and domain targets live on the work / facade projection, not as schedule ownership.

| Field | Notes |
| --- | --- |
| id / key | Stable id; unique per row. Domain facades choose key shape (Metadata structure: `structure:{source_id}:{schedule_id}`) |
| name | Operator label. Facades may supply defaults (Metadata: `structure · {source_key}`; not unique per Source). PATCH empty/whitespace may restore that default |
| enabled | Pause automatic due-ticks without delete; run-now still allowed |
| cadence | Exactly one of `interval_seconds` or five-field `cron` |
| schedule_timezone | IANA; interprets cron wall clock; ignored for interval |
| running_timeout_sec | Optional **Running Time Limit** (positive seconds). Null / omit / seed = no control. Mint copies this onto the Job; the reaper does not live-read it. Cooperative stamp; not process kill |
| owner_ref | Opaque caller association written by the domain facade; product HTTP cannot set it; null only for system rows |
| last_run_at | Instant of the last **consumed due event** (Clock Instant when the Job was minted for that tick — not "last successful run"; run-now does not move it; cron cross-slot skip does not move it) |
| next_run_at | Stored commitment Instant; null when disabled. Due iff `enabled` and `next_run_at <= Clock.now()`. Not computed on GET |

Rules:

- Operator identity is a closed **work kind** plus **target** projected by the facade. Public JSON does not include Celery `task_name` / `args_json` / `owner_ref`. Mechanism `schedule_out` does not invent Source shape; Metadata `public_schedule` adds `work_kind` / `target`.
- Create via a **domain facade** (today: `POST /sources/{id}/schedules`), plus Metadata’s create-time seed when registering a database **Source**, plus a mutating Source update when a database Source has zero structure schedules. Platform `GET/PATCH/DELETE /schedules` list and edit cadence / enabled / delete. No global create. No PUT replace.
- The schedule is **not owned by** Source / Entity / Serving. Facades register schedules; `owner_ref` is an opaque string (Metadata structure uses a facade-chosen literal such as `metadata:source:{id}`). The scheduler never parses it and never scans kwargs for Source id.
- Job ↔ schedule association is `trigger_kind=schedule` and `trigger_ref` = schedule id. Structure single-flight is Metadata catalog-write serialization on the Source at Job **execution**, not a schedule lock.
- `PATCH` is RFC 5789 partial (cadence / timezone / enabled / name / `running_timeout_sec`). Changing cadence or timezone rewrites `next_run_at` only; already-minted Jobs keep running (including their minted Running Time Limit snapshot). Present `running_timeout_sec` null clears the definition to no-control; omission leaves the stored value. Non-positive is rejected (`SCHEDULE_RUNNING_TIMEOUT_INVALID`).
- Permission is `jobs:run`. No `schedules:*` key.
- System rows (`system=true`, e.g. stuck-Job reaper) stay enabled, are excluded from the default list and Console, and cannot be PATCHed, DELETEd, or run-now via product APIs. Their `owner_ref` is null. Tests may pass `?system=true` to list them. Beat copies the reaper row's `interval_seconds` from the `job_lost_detection_sec` **System Parameter** on sync; it does not recompute `next_run_at`. Operators never PATCH that row.
- **Due dispatch:** Beat selects enabled rows with `next_run_at <= Clock.now()`. Whether a tick is **consumed** is decided only by that column — not by a Celery crontab `is_due(last_run_at)` clock. Beat may debounce **delivery** of the same in-memory commitment Instant (one send, then wait for store reload / `BEAT_SYNC_EVERY_SEC` retry) so it does not tight-loop before the worker writes the next commitment.
  - **Cron current slot:** if the current legal wall-clock slot still matches and is later than the consumed cursor, mint that tick (`scheduled_for` = that slot Instant). Same transaction: insert Job, set `last_run_at` = Clock Instant, write next legal `next_run_at`. The slot Instant is that minute's start; Clock may already be seconds into the minute.
  - **Cron cross-slot:** if the delivered / committed Instant is not the current legal slot, do **not** mint that Instant (no catch-up of missed slots) and do **not** change `last_run_at`. Then: if the current legal slot still matches and is later than the consumed cursor, rewrite `next_run_at` to **that current-slot Instant** and, in the **same due handling**, consume that identity a second time to mint the Job — do not remap the stale Instant onto a different `scheduled_for` in the first consumption. If the whole handling fails, Beat may redeliver the **stale** Instant; the worker runs the same second-consume path again. Otherwise (current slot empty or already consumed) advance `next_run_at` to the next legal slot after the current minute. "After now" is the matching wall-clock minute, not Instant `≥ Clock.now()`.
  - **Interval:** a past `next_run_at` means one catch-up tick. After mint, `next_run_at = mint Instant + interval` (must be `≥ now`). No wall-clock anchor grid.
  - Due path is idempotent on `(trigger_ref, scheduled_for)` when `scheduled_for` is not null.
- Operator run-now (`POST /schedules/{id}/run`) mints a Job with the same trigger fields and `created_by` = the operator. It does **not** update `last_run_at` or `next_run_at`. Disabled schedules accept run-now. System rows reject it. Run-now Jobs have `scheduled_for` null. Due tick and run-now both snapshot `running_timeout_sec` from the definition at mint.
- The scheduler does **not** interpret Source usability or structure single-flight. Domain Jobs always mint; structure collision / disabled Source fail on the Job during execution (`failed` + domain `error_code`), never as schedule skip or HTTP 409 from the schedule surface.
- In-flight due (delivery already started, Job row not yet inserted) that meets disable or delete still mints and immediately marks the Job `cancelled`; that tick is consumed. Delivery carries the commitment Instant being consumed; the worker honors that Instant as the tick identity even when pause has cleared `next_run_at` or the definition row is already gone.
- Pause (`enabled=false`): set `next_run_at` null immediately; already queued/running Jobs **keep running** (not cancelled by pause). Re-enable recomputes `next_run_at` from now (no catch-up of paused time).
- **Withdraw:** caller asks the scheduler to remove definitions matching `owner_ref`. Deletes matching definitions; unfinished Jobs for those schedules are immediately CAS'd to `cancelled` (queued also revoked). Historical Jobs remain. Single-row delete uses `DELETE /schedules/{id}` (same cancel unfinished Jobs). Scheduler does not FK-cascade from Source.
- Product cron does **not** catch up missed slots beyond the current-slot rule above. Interval may fire one catch-up beat while enabled.
- MCP does not expose Scheduled Task CRUD or run-now in this slice.
- Platform operational work and domain cadences share the same **Scheduled Task** table.
- Operator management is of the **definition** plus run-now; fired work is observed as **Jobs**, including `GET /schedules/{id}/jobs`. Observation "last run" joins the latest related Job; it is not `last_run_at`.

## 4. Console

- Module id `schedules` lives in the **Operations** nav group (`operations`), list permission `jobs:run`: platform-wide domain schedules; edit cadence / enabled / delete; run-now; related Jobs. No system rows. No global create.
- Source “related schedules” is a **Source-scoped workbench** at `/console/sources/:id/schedules` (not a sidebar module, not registered as `sources.show`): toolbar create plus the same row actions (enable/disable, edit, delete, run-now, related Jobs). `jobs:run` gates the surface.
- Console delete asks for confirmation; HTTP `DELETE` remains immediate.
- Screen copy uses **schedule**. Do not label `last_run_at` as "Last run". Disabled rows show paused, not "unknown next".
- Create/edit may set optional **Running Time Limit**. Empty = no control. No new schedule-list column in this slice.

## 5. Non-Goals

- Treating Scheduled Task as a Metadata domain entity or mounting the Schedules module under the `metadata` nav group
- A separate schedule product or new engine
- Global `POST /schedules` create
- Operator-supplied Celery `task_name` or product-writable `owner_ref`
- MCP schedule tools
- Catchup / backfill / RRule / Late / materialized future Jobs
- A `schedules:*` permission key
- Console display or pause of system schedules
- Using structure single-flight as the Job–schedule relationship
- Cron preview N / scheduler health in Operations (deferred)
- Interpreting Source / Metadata inside the scheduler
- Treating Source delete as schedule ORM cascade or kwargs `source_id` scan (use **owner_ref** withdraw)
