# refraq API Contracts: Scheduled Tasks

## 1. Purpose

Contracts for operator management of domain **Scheduled Task** definitions (the schedule layer) and firing them.

Business rules: `docs/business-scheduled-tasks.md` (platform Scheduled Task) and `docs/business-metadata.md` §4.2 (Metadata structure **facade** onto schedules — not schedule ownership by Source), root `CONTEXT.md`, `docs/adr/0026-seed-structure-schedule-on-source-create.md`, `docs/adr/0027-running-time-limit-on-schedule.md`.
Auth: Session or User PAT. Permission: `jobs:run`.
Instants: [`docs/conventions-time.md`](conventions-time.md) (UTC `Z` on the wire).
HTTP protocol failures: [`docs/conventions-errors.md`](conventions-errors.md).

Create is domain-facade (`POST /sources/{id}/schedules`) plus the database Source create-time seed and a mutating Source update (missing product-default schedule kinds). Platform list/get/patch/delete do not create rows and do not accept Celery `task_name` or `owner_ref`. Mechanism responses do not invent Source shape; the Metadata facade adds `work_kind` / `target`.

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
  "running_timeout_sec": null,
  "deletable": true,
  "last_run_at": "2026-08-13T10:00:00Z",
  "next_run_at": "2026-08-14T02:00:00Z",
  "recent_jobs": [
    {
      "id": "job_01HZX",
      "status": "succeeded",
      "created_at": "2026-08-13T10:00:00Z",
      "started_at": "2026-08-13T10:00:01Z",
      "finished_at": "2026-08-13T10:05:00Z",
      "error_code": null
    }
  ],
  "created_at": "2026-08-13T10:00:00Z",
  "updated_at": "2026-08-13T10:00:00Z"
}
```

Rules:

- Public fields never include `task_name`, `args_json`, `kwargs_json`, `hidden`, `locked`, `undeletable`, `store_only`, `owner_ref`, or `commitment_timezone`. `deletable` is the inverse of `undeletable`.
- `work_kind` is the closed catalog of domain work (`structure` \| `join_detection` \| `catalog_embed`), filled by the Metadata facade. Store-only rows return `work_kind` / `target` null. `catalog_embed` returns `target` null.
- `target` is facade projection of the work target (Source id/key for `structure` and `join_detection`), **not** proof that the schedule is owned by Source. `target.source_key` is present when the facade can resolve the Source; after Source hard-delete, matching schedules are withdrawn by `owner_ref` so orphans should not remain on product paths.
- Cadence is exactly one of `interval_seconds` (positive int) or five-field `cron`. Cron wall clock is the `schedule_timezone` **System Parameter**, not a field of the row. Interval schedules ignore it.
- `running_timeout_sec` is the optional **Running Time Limit** (positive int seconds). Null / omit / seed = no control. Mint copies it onto the Job. PATCH of this field does not rewrite in-flight Jobs.
- `last_run_at` is the Instant cursor of the last **consumed due** mint (Clock Instant). Operator run-now does not change it. Cron cross-slot skip does not change it. It is not Console “last run”.
- `next_run_at` is the stored commitment Instant. Null when `enabled=false`. Due is `enabled` and `next_run_at <= now`. GET returns the stored value; it is not computed on read.
- `recent_jobs` is an observation join to the latest 20 Jobs with `trigger_kind=schedule` and `trigger_ref` = this schedule id (any status), ordered by `created_at` oldest first, so the last element is the last run. Empty array when none. Not cached on the schedule row. List endpoints load it for the whole page in one query.
- Several schedules of each kind may target one Source. Keys `structure:{source_id}:{schedule_id}` and `join_detection:{source_id}:{schedule_id}` are Metadata facade naming conventions (unique per row), not a schedule-table Source FK.

## 3. Endpoints

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `POST` | `/sources/{id}/schedules` | `jobs:run` | Insert a Source-targeted schedule (`work_kind=structure` or `join_detection`) |
| `GET` | `/sources/{id}/schedules` | `jobs:run` | List schedules whose target is this Source (both work kinds; **Offset Page**) |
| `GET` | `/schedules` | `jobs:run` | Platform list (default excludes `hidden`; tests may pass `?hidden=true`; **Offset Page**) |
| `GET` | `/schedules/{id}` | `jobs:run` | Get by id (hidden rows visible for debug) |
| `PATCH` | `/schedules/{id}` | `jobs:run` | Partial update: `enabled`, cadence, `name`, `running_timeout_sec` |
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
  "running_timeout_sec": null,
  "enabled": true,
  "name": null
}
```

Rules:

- `kind` must be `structure` or `join_detection`.
- Exactly one of `cron` or `interval_seconds`.
- `running_timeout_sec` omit or null = no control. A present non-positive value is rejected (`SCHEDULE_RUNNING_TIMEOUT_INVALID`).
- Unknown fields on the request object are rejected (`422` `REQUEST_INVALID`). `schedule_timezone` is not a field of this body.
- Path `{id}` is the Source on the **facade** route; the facade validates a database Source with access, writes a unique key, sets Celery kwargs (`source_id`, `schedule_id`) and opaque `owner_ref` internally. The schedule table does not gain a Source FK.
- Always insert: `201`. Cursor `last_run_at=now`; `next_run_at` = next legal slot after now (or null if created disabled).
- Response `{ "schedule": { … } }` with `source_key` filled.

### `POST /schedules/{id}/run`

Empty body. `202` `{ "job": { … } }` (Job shape). `trigger_kind=schedule`, `trigger_ref` = schedule id, `created_by_user_id` = operator, `scheduled_for` null. Disabled schedules are allowed. Locked schedules → `SCHEDULE_SYSTEM_IMMUTABLE`. Always mints a Job — Source busy / disabled is not a schedule HTTP conflict. Does not update `last_run_at` / `next_run_at`. The site `catalog_embed` schedule uses this same route.

### `PATCH /schedules/{id}` body

Any subset of `enabled`, `name`, `cron`, `interval_seconds`, `running_timeout_sec`. Setting `cron` clears `interval_seconds` and vice versa. Sending both non-null is rejected. Unknown fields on the request object are rejected (`422` `REQUEST_INVALID`); `schedule_timezone` is one such field. Present `running_timeout_sec` null clears to no-control; omission leaves the stored value; a present non-positive value is rejected. Empty or whitespace `name` restores that work kind's default: `structure · {source_key}`, `join_detection · {source_key}`, or `catalog embed` for the site schedule. Locked rows are rejected.

- `enabled=false` → `next_run_at` null immediately; already queued/running Jobs keep running.
- `enabled=true` → recompute `next_run_at` from now (no pause catch-up).
- Cadence change → rewrite `next_run_at` immediately (while enabled) using the current **Schedule Timezone**, and store that zone as `commitment_timezone`; do not cancel already-minted Jobs.

### `GET /schedules`

**Offset Page** (newest first: `created_at DESC`, `id DESC`). Query params: `limit` (default **50**, max **200**), `offset` (default **0**), `hidden` (default `false`; `true` includes hidden rows for tests / debug).

Response: `{ "items": […], "total": N, "limit": L, "offset": O, "cron_timezone": "UTC" }`. `total` is the filtered set. `cron_timezone` is the effective **Schedule Timezone** System Parameter, the same value on every page.

### `GET /sources/{id}/schedules`

Same **Offset Page** envelope, including `cron_timezone`, defaults, max, and ordering. Scoped to schedules whose `owner_ref` is this Source (all work kinds). Missing Source → `SOURCE_NOT_FOUND`. Empty page is `200` with `items: []` (allowed after the operator deletes the last schedule; a newly created database Source has the product-default seeds).

### `DELETE`

`204` empty body. Unfinished Jobs for this schedule are immediately cancelled (queued also revoked). Historical Jobs remain. An undeletable row is `SCHEDULE_UNDELETABLE`.

## 4. Errors

| code | When |
| --- | --- |
| `SCHEDULE_NOT_FOUND` | No Scheduled Task for this id |
| `SCHEDULE_SYSTEM_IMMUTABLE` | PATCH or run-now of a locked row |
| `SCHEDULE_UNDELETABLE` | DELETE of an undeletable row |
| `SCHEDULE_CADENCE_INVALID` | Neither or both cadence fields; invalid cron; non-positive interval |
| `SCHEDULE_RUNNING_TIMEOUT_INVALID` | Present `running_timeout_sec` is not a positive integer |
| `SCHEDULE_KIND_INVALID` | POST `kind` is not in the closed catalog |
| `JOB_INPUT_INVALID` | A Source-targeted schedule requires a database Source with access |
| `SOURCE_NOT_FOUND` | Facade path Source missing. Source delete withdraws Source-targeted schedules by `owner_ref` so orphans should not remain. |
| `REQUEST_INVALID` | Unknown fields on `POST /sources/{id}/schedules` or `PATCH /schedules/{id}` |

`JOB_ALREADY_ACTIVE` and `JOB_SOURCE_DISABLED` are Job execution / domain errors, not schedule mint HTTP codes.

## 5. Console

- Module id `schedules` (`operations` group, list permission `jobs:run`): platform-wide domain schedules, including site `catalog_embed`; edit cadence / enabled; delete when `deletable`; run-now; related Jobs. No hidden rows. No global create. The list identity column is the raw work kind. The platform list appends the Source key in that same cell (`{work_kind} · {source_key}`, or `source_id` when the key is absent). `catalog_embed` shows only `catalog_embed`. The Source workbench shows only the work kind. A custom name appears on a second line only when it differs from the work-kind default (`structure · {source_key}`, `join_detection · {source_key}`, or `catalog embed`). The list does not show the schedule id.
- Sources: related-schedules **workbench** at `/console/sources/:id/schedules` — toolbar create plus the same row actions as Operations (enable/disable, edit, delete, run-now, related Jobs). Console delete asks for confirmation; HTTP `DELETE` remains immediate.
- Do not label `last_run_at` as Last run; the list shows a Recent runs strip from `recent_jobs` for observation (one bar per Job, colored by status, height by duration, hover for details, click opens related Jobs) and `next_run_at` for commitment. Disabled → paused (not “unknown next”).
- Create/edit may set optional **Running Time Limit**. Empty = no control. No schedule-list timezone column. Preset wall-clock sentences (the cadence option and the read-only cron phrase) include `cron_timezone` in the same sentence. Custom cron keeps that zone on the field description and does not write it into the expression. When editing a saved schedule whose cadence expression is unchanged, the form shows that row's next-run text with the same **Display Timezone** formatting as the list and states that it is the list's next run. A changed cadence says the list recalculates on save and does not invent a time. Create does not predict a next run. The next-run column header names the **Display Timezone** once (the browser zone when the preference is null). Cell text and recent-run times do not repeat the zone. Job detail may show the minted Running Time Limit snapshot when non-null.

## 6. Non-Goals

- Global `POST /schedules` create
- Operator-supplied Celery `task_name` or product-writable `owner_ref`
- MCP schedule tools
- Catchup / backfill / RRule
- PUT replace of “the” schedule per Source or per work kind
