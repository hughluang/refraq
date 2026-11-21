# refraq Business Rules: Scheduled Tasks

## 1. Scope

This document defines the platform **Scheduled Task** mechanism: the scheduling foundation that turns a cadence intent into observable, withdrawable **Job** attempts. Distinct from any **Job** instance. Not a product domain, not a Metadata business object, and not a field of **Source**. Structure, join-detection, `catalog_embed`, and `entity_embed` **Jobs** are minted only this way. `catalog_embed` uses one site schedule (`key` `catalog_embed:site`). `entity_embed` uses one site schedule (`key` `entity_embed:site`). Rules: `docs/business-model-services.md` and `docs/business-entity.md`. A **Data Channel** Scheduled node mints `channel_run` **Jobs** this way; the same Job kind is also minted by manual runs and by Data Channel triggers.

Related boundaries:

- Terminology: `docs/glossary.md`.
- HTTP: `docs/api-contracts-schedules.md`.
- **Job** mechanism: `docs/business-jobs.md`.
- Metadata structure schedule **facade** (`POST/GET /sources/{id}/schedules`), Source create-time seed, **owner_ref** withdraw on Source delete, and mutating Source-update ensure: `docs/business-metadata.md`.
- Data Channel publish sync of `channel_run` schedules, activation, and delete withdraw: `docs/business-data-channel.md` §3.6, §3.7, §7.2.
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

1. **Due event is atomic** — a tick is consumed only when a Job attempt exists for that tick; Job mint and commitment consumption share one transaction.
2. **Recover one stored commitment** — an enabled cron schedule consumes its valid stored `next_run_at` once, even after that minute or after downtime. Preserve that Instant as `scheduled_for`, then advance directly to the next legal fire strictly after the consumption Clock Instant. Do not enumerate uncommitted historical slots.
3. **Pause ≠ in-flight cancel ≠ withdraw** — pause clears commitment; an already-minted Job is not cancelled by pause; withdraw / delete immediately terminalizes unfinished Jobs.

## 3. Object Model

Platform cadence definition. Does not contain extract SQL, transforms, a dependency graph, or a **Source** foreign key. A Data Channel workflow graph lives on its **Channel Version**, not on the schedule; domain targets live on the work / facade projection, not as schedule ownership.

| Field | Notes |
| --- | --- |
| id / key | Stable id; unique per row. Domain facades choose key shape (Metadata: `structure:{source_id}:{schedule_id}` and `join_detection:{source_id}:{schedule_id}`; Data Channel: `channel_run:{channel_id}`) |
| name | Operator label. Facades may supply defaults (Metadata: `structure · {source_key}` and `join_detection · {source_key}`; not unique per Source; Data Channel: `channel_run · {channel name} · {node name}`). PATCH empty/whitespace may restore that default |
| enabled | Pause automatic due-ticks without delete; run-now still allowed |
| cadence | Exactly one of `interval_seconds` (an integer from 1 through 252460800 seconds, 2922 days, the same 8-year horizon as cron) or five-field `cron`. Cron accepts `*`, a number, `a-b`, `*/n`, `a-b/n`, `n/step`, and comma lists. Ranges: minute 0–59, hour 0–23, day-of-month 1–31, month 1–12, day-of-week 0–7 (`7` is Sunday). Day-of-month and day-of-week cannot both be anything other than `*`. A cron write must have a fire within 8 years |
| start_at | Optional **Schedule Start** Instant (`SCHEDULE_START_AT_INVALID` when out of range). Null = start immediately. Interval: anchor of the fire grid `start_at + k * interval` (k ≥ 0); the first fire is `start_at` itself when it is in the future. Cron: lower bound; the first fire is the first legal slot at or after `start_at` rounded up to the minute. Stored as written; a past value stays as the anchor. At most 252460800 seconds after now on write |
| commitment_timezone | Zone that produced the stored `next_run_at`. Not on the public wire. Cron uses the **Schedule Timezone** System Parameter; this column lets Beat see that a parameter change has not been applied yet |
| running_timeout_sec | Optional **Running Time Limit** (positive seconds, at most 252460800, the same 8-year horizon as cadence). Null / omit / seed = no control. Mint copies this onto the Job; the reaper does not live-read it. Cooperative stamp; not process kill |
| owner_ref | Opaque caller association written by the domain facade; product HTTP cannot set it; null only for store-only rows |
| last_run_at | Instant of the last **consumed due event** (Clock Instant when the Job was minted for that tick, not the scheduled Instant, actual execution start, or business success; run-now does not move it). Creation initializes the cursor to now |
| next_run_at | One stored, recoverable commitment Instant; null when disabled. Due iff `enabled` and `next_run_at <= Clock.now()`. Not a ledger of historical slots and not computed on GET |

Rules:

- Operator identity is a closed **work kind** plus **target** projected by the facade. Public JSON does not include Celery `task_name` / `args_json` / `owner_ref`, or the trait flags. It does include `deletable`. Mechanism `schedule_out` does not invent Source shape; Metadata `public_schedule` adds `work_kind` / `target`. Closed work kinds: `structure` \| `join_detection` \| `catalog_embed` \| `entity_embed` \| `channel_run`. `catalog_embed` and `entity_embed` have no Source target. `channel_run` targets a **Data Channel** and its Scheduled node. Both embed schedules seed cron `0 3 * * *`, evaluated in the site `schedule_timezone` (the parameter seed is UTC).
- Create via a **domain facade** (today: `POST /sources/{id}/schedules`), plus Metadata’s create-time seed when registering a database **Source**, plus a mutating Source update when a database Source is missing a product-default schedule kind, plus Data Channel publish sync. Platform `GET/PATCH/DELETE /schedules` list and edit cadence / enabled / delete. No global create. No PUT replace.
- **Data Channel publish sync.** `channel_run` rows are a by-product of publishing a Data Channel version; there is no create facade. Publish reconciles the version's single trigger with one row keyed `channel_run:{channel_id}`: a Scheduled trigger inserts or updates the row, a cadence or `start_at` change rewrites `next_run_at`, and any other trigger withdraws the row (cancelling its unfinished Jobs). Editing a draft changes no row. Rows carry `owner_ref` `channel:{channel_id}`, traits `locked` + `undeletable`, and a null `running_timeout_sec`; the Data Channel run timeout lives in its graph settings, not here. `enabled` follows the channel's activation switch: activation enables every row, deactivation disables them without cancelling running Jobs. Deleting the channel withdraws its rows by `owner_ref`. Operators observe these rows and cannot PATCH, run-now, or DELETE them. Cron uses the **Schedule Timezone** like every other row.
- The schedule is **not owned by** Source / Entity / Serving. Facades register schedules; `owner_ref` is an opaque string (Metadata structure uses a facade-chosen literal such as `metadata:source:{id}`). The scheduler never parses it and never scans kwargs for Source id.
- Job ↔ schedule association is `trigger_kind=schedule` and `trigger_ref` = schedule id. **Kind execution lock** is Metadata runner control at Job **execution**, not a schedule lock.
- `PATCH` is RFC 5789 partial (cadence / `start_at` / enabled / name / `running_timeout_sec`). Changing cadence or `start_at` rewrites `next_run_at` and `commitment_timezone` from the current **Schedule Timezone** and the resulting `start_at`; a cadence change without `start_at` keeps the stored anchor. Present `start_at` null clears it (start immediately); a value beyond the 8-year horizon is rejected (`SCHEDULE_START_AT_INVALID`). Already-minted Jobs keep running (including their minted Running Time Limit snapshot). Present `running_timeout_sec` null clears the definition to no-control; omission leaves the stored value. Non-positive, or a value above 252460800 seconds, is rejected (`SCHEDULE_RUNNING_TIMEOUT_INVALID`).
- **Schedule Timezone** is the `schedule_timezone` System Parameter (seed `UTC`), not a field of the row. Interval schedules ignore it. A successful write realigns `next_run_at` for enabled cron rows whose `commitment_timezone` differs, before the response, without minting a Job. Beat sync repeats that realign and is a no-op when commitments already match. Enabling a paused cron row recomputes from the current zone.
- Permission is `jobs:run`. No `schedules:*` key.
- Trait flags replace a single system bit. `hidden` drops the row from the default list and Console. `locked` rejects PATCH and run-now. `undeletable` rejects DELETE (`deletable` is false on the wire). `store_only` advances the commitment and does not mint a Job; Beat does not inject `due_at`. The stuck-Job reaper sets all four, stays enabled, and has a null `owner_ref`. Tests may pass `?hidden=true` to list hidden rows. Beat copies the reaper row's `interval_seconds` from the `job_lost_detection_sec` **System Parameter** on sync; it does not recompute `next_run_at`. Operators never PATCH that row. The site `catalog_embed` and `entity_embed` schedules set only `undeletable`. Data Channel `channel_run` rows set `locked` + `undeletable` and stay visible. Data Channel background duties (event and change-arrival dispatch, Change Log cleanup, run data retention) are system rows with all four traits and in-code intervals. Run data retention is keyed `channel_run_record_retention`, named `Purge channel run records`, and runs hourly as `backend.channel.tasks.purge_run_records`. It deletes channel run records whose Job is terminal and whose `created_at` is older than `channel_run_record_retention_days`, and their node executions. Jobs stay. The entity change-log retention sweep is a separate hidden, `locked`, `undeletable`, `store_only` system row, not the channel duty Change Log cleanup. Its key is `entity_change_log_retention`, its name is `Purge Entity change logs`, its interval is 86400 seconds in code, and its task is `backend.worker.tasks.purge_change_logs`. It stays enabled and has a null `owner_ref`. While an entity's effective record has recording on and retention is a whole number of days, a pass deletes that entity's entries whose transaction time is earlier than now minus that many days. Never-expire and recording off delete nothing. The duty does not publish a version.
- **Due dispatch:** Beat selects enabled rows with `next_run_at <= Clock.now()`. Whether a tick is **consumed** is decided only by that column — not by a Celery crontab `is_due(last_run_at)` clock. Beat may debounce **delivery** of the same in-memory commitment Instant (one send, then wait for store reload / `BEAT_SYNC_EVERY_SEC` retry) so it does not tight-loop before the worker writes the next commitment.
  - **Cron stored commitment:** an enabled row mints only when `next_run_at` exists, delivered `due_at == next_run_at`, and `due_at <= now`. The original due Instant must be legal under the current expression, Schedule Timezone, and `start_at`, and later than the consumed cursor. Legality uses the same DST-aware next-fire expansion from `due_at - 1 microsecond`; its result must equal `due_at`. The processing minute need not match cron. Hours or days late still consume only this one commitment, including a commitment left during Beat downtime.
  - **Cron cursor update:** sample Clock after acquiring the schedule row lock. In the same transaction, mint with `scheduled_for = due_at`, set `last_run_at` to the actual mint Instant, and set `next_run_at` to the first legal fire strictly after this processing Instant. Never remap to the processing minute or enumerate intervening slots. A uniqueness conflict preserves the existing Job and its timestamps and recovery flag; a valid consumption may repair `last_run_at` from that Job's original `created_at`, but computes the next cron fire from the current processing Instant, not historical creation time.
  - **Non-consumption:** future deliveries (`not_due`), a missing enabled commitment (`no_commitment`), and deliveries unequal to the stored commitment (`commitment_replaced`) do not mint or move cursors. Invalid cron/start identities also do not mint. Repeated consumed deliveries are non-minting (`commitment_replaced`, or defensively `already_consumed`) and never rewind cursors. Cadence/start changes, timezone realignment, and pause/resume can replace the commitment. Identity is the Instant, not a definition revision: an unchanged due Instant remains the same identity.
  - **Recovery classification:** new enabled-cron mints set `is_delayed_recovery=true` exactly when the Clock Instant sampled after acquiring the schedule row lock is at least `due_at + 60 seconds`; +5s and +59s are false, +60s is true. This UTC difference classifies creation provenance, not an expiry/grace period, queue deadline, or execution result. There is no recovery age limit; normal creation followed by a late execution claim does not become recovery.
  - **Interval:** a past `next_run_at` means one catch-up tick. Without `start_at`, after mint `next_run_at = mint Instant + interval` (must be `≥ now`); there is no wall-clock anchor grid. With `start_at`, after mint `next_run_at` is the first grid point `start_at + k * interval` strictly after now; missed grid points are skipped, not fired in a burst.
  - **Start bound:** a cron slot before the first minute at or after `start_at` is not a legal slot, so a stale delivery after `start_at` moved later does not mint.
  - Due path is idempotent on `(trigger_ref, scheduled_for)` when `scheduled_for` is not null.
- Operator run-now (`POST /schedules/{id}/run`) mints a Job with the same trigger fields and `created_by` = the operator. It does **not** update `last_run_at` or `next_run_at`. Disabled schedules accept run-now. Locked rows reject it. Run-now Jobs have `scheduled_for` null. Due tick and run-now both snapshot `running_timeout_sec` from the definition at mint.
- The scheduler does **not** interpret Source usability or **Kind execution lock**. Domain Jobs always mint; same-kind lock contention / disabled Source fail on the Job during execution (`failed` + domain `error_code`), never as schedule skip or HTTP 409 from the schedule surface.
- `channel_run` Jobs take no execution lock. Runs of one Data Channel may overlap, including two due ticks of the same row; the scheduler does not skip a tick because an earlier `channel_run` Job is still running. A due tick of an inactive channel, or of a Scheduled node no longer in the current published version, still mints and the Job ends `cancelled`.
- The schedule decides only when a `channel_run` Job is minted. `last_run_at` and `scheduled_for` are never Data Channel checkpoints; recovery does not reset or advance business checkpoints. Overlap and checkpoint semantics remain domain rules.
- In-flight due (delivery already started, Job row not yet inserted) that meets disable or delete still mints a `cancelled` Job, with `is_delayed_recovery=false`, and never executes domain work or restores the definition/commitment. For a paused cron row, the due must not be future, must remain legal under current cron/start/timezone rules, and must be later than the consumed cursor; `next_run_at` stays null. A deleted row retains the delivered due identity and uniqueness protection without recreating the definition. The message alone does not prove it was sent before pause; there is no delivery receipt or definition revision.
- Pause (`enabled=false`): set `next_run_at` null immediately; already queued/running Jobs **keep running** (not cancelled by pause). Re-enable recomputes `next_run_at` from now (no catch-up of paused time), still honoring the stored `start_at` (interval grid stays anchored; cron stays bounded).
- **Withdraw:** caller asks the scheduler to remove definitions matching `owner_ref`. Deletes matching definitions; unfinished Jobs for those schedules are immediately CAS'd to `cancelled` (queued also revoked). Historical Jobs remain. Single-row delete uses `DELETE /schedules/{id}` (same cancel unfinished Jobs). Scheduler does not FK-cascade from Source.
- Recovering one stored cron commitment is not historical backfill: even a minutely cron delayed for days mints at most one Job for its stored due identity, not every intervening slot. This bound is per schedule, not a site-wide recovery concurrency limit. Interval may still fire one catch-up beat while enabled; store-only duties, run-now, execution overlap, and checkpoints retain their existing rules.
- MCP does not expose Scheduled Task CRUD or run-now in this slice.
- Platform operational work and domain cadences share the same **Scheduled Task** table.
- Operator management is of the **definition** plus run-now; fired work is observed as **Jobs**, including `GET /schedules/{id}/jobs`. Observation "recent runs" joins the latest related Jobs (newest is the last run); it is not `last_run_at`.

## 4. Console

- Module id `schedules` lives in the **Operations** nav group (`operations`), list permission `jobs:run`: platform-wide domain schedules, including the site `catalog_embed` and `entity_embed` schedules and Data Channel `channel_run` rows; edit cadence / enabled; delete when `deletable`; run-now; related Jobs. The list displays enabled and does not change it; create and edit forms change `enabled` for editable rows. `channel_run` rows are read-only (no edit, delete, or run-now); their cadence is edited on the Scheduled node and applied by publish, and enabled follows channel activation. No hidden rows. No global create.
- Source “related schedules” is a **Source-scoped workbench** at `/console/sources/:id/schedules` (not a sidebar module, not registered as `sources.show`): toolbar create plus the same row actions (edit, delete, run-now, related Jobs). The Enabled column displays the value; create and edit change it. `jobs:run` gates the surface.
- Console delete asks for confirmation; HTTP `DELETE` remains immediate.
- Screen copy uses **schedule**. Do not label `last_run_at` as "Last run"; the list shows a Recent runs strip of the latest related Jobs. Disabled rows show paused, not "unknown next".
- Create/edit may set optional **Running Time Limit**. Empty = no control. No new schedule-list column in this slice.
- Create/edit may set optional **Schedule Start** for either cadence. Empty = start immediately; there is no separate toggle. The picker uses the **Schedule Timezone**.

## 5. Non-Goals

- Treating Scheduled Task as a Metadata domain entity or mounting the Schedules module under the `metadata` nav group
- A separate schedule product or new engine
- Global `POST /schedules` create
- Operator-supplied Celery `task_name` or product-writable `owner_ref`
- MCP schedule tools
- Historical slot backfill / RRule / configurable lateness grace / materialized future Jobs; single stored-commitment recovery is supported
- Schedule end time (`end_at`)
- A `schedules:*` permission key
- Console display or pause of hidden schedules
- Using **Kind execution lock** as the Job–schedule relationship
- Cron preview N / scheduler health in Operations (deferred)
- Interpreting Source / Metadata inside the scheduler
- Treating Source delete as schedule ORM cascade or kwargs `source_id` scan (use **owner_ref** withdraw)
