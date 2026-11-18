# Time Conventions

Authoritative Instant / Schedule Timezone contract for refraq.
Domain terms: `docs/glossary.md`.

## 1. Two concepts (do not mix)

| Concept | Meaning | Storage / wire |
|---------|---------|----------------|
| **Instant** | Absolute moment on the timeline | Aware UTC in process; `timestamptz` in Postgres; RFC 3339 with offset on the wire (outbound always `Z`) |
| **Schedule Timezone** | IANA zone that interprets **cron** wall-clock fields for every **Scheduled Task** | System Parameter `schedule_timezone` (seed `UTC`); **not** a field of one row and **not** stored inside an Instant; **ignored** for `interval_seconds` |

Celery `timezone` / `enable_utc` is worker message time, **not** business Schedule Timezone.
**Display Timezone** (User preference) formats Instants in the Management Console only; HTTP / MCP Instant JSON stays UTC `Z` (see §8).

## 2. Process rules

- In-process Instants are always **timezone-aware** with `timezone.utc` (or equivalent zero offset after normalization).
- Compare and arithmetic only on aware values.
- Obtain “now” only via `Clock.now()` / `backend.core.time.utc_now()` (never `datetime.utcnow` / `utcfromtimestamp`).
- Clock is process-scoped (`get_clock` / `set_clock`); tests use `FixedClock` and must reset.
- **Business store/service code must not** call `ensure_aware_utc` or manual `.astimezone(UTC)` as “insurance”. Normalization belongs only in boundary helpers (`UtcDateTime`, Instant field, format helpers). Needing insurance means a boundary leak.

## 3. Persistence

- Instant columns use `UtcDateTime` → `TIMESTAMP WITH TIME ZONE` (`timestamptz`).
- Bind rejects naive datetimes; results are normalized to `timezone.utc`.
- Database sessions pin `TimeZone=UTC` (defense against offset-less literals; display conversion is **not** delegated to session TZ because boundaries speak Instant only).
- Instant columns have **no** `server_default`: application Clock is the write source; omitting a value fails.
- Historical naive columns migrated as **UTC** (`AT TIME ZONE 'UTC'`), matching prior `utcnow` write semantics.

## 4. API / MCP / Job logs

- **Inbound:** RFC 3339 with a required offset (`Z`, `+00:00`, `+08:00`, …). No offset → validation error (e.g. 422). Any legal offset is accepted and normalized to aware UTC.
- **Outbound:** one formatter from `backend.core.time` — HTTP, MCP, and Job log lines all emit UTC with `Z`.
- Schema Instant fields use the shared Instant type from `core.time` (not bare `datetime`, and not bare `AwareDatetime` alone — that type only requires awareness, not UTC normalize / `Z` serialize).

### 4.1 OpenAPI date-time and Console display

`format: date-time` on a field is the Instant contract, for requests and responses. A non-null value is an offset RFC 3339 timestamp and is guaranteed parseable. A nullable field has one empty value: `null`. Omitted keys are absent, not an empty string.

A success response keeps Instant values as JSON strings. `apiClient` (`frontend/src/lib/api.ts`) returns that JSON unchanged and remembers a non-empty `X-Request-ID` for an object body. Display formats the received string with the User locale and Display Timezone. An illegal platform Instant string fails only the display point that shows it, as problem `API_CONTRACT_INVALID`; other fields on the page stay. The run execution list passes that response's `X-Request-ID` into `<Instant>`, which shows the id only when one is passed. `showContractInstant` (`frontend/src/lib/datetime.ts`, directly or through `useShowInstant`) reports the same contract problem and does not attach a request id. `useFormatInstant` still raises `UnreadableInstantError`.

`date` (`YYYY-MM-DD`), `time` (`HH:MM`), durations (`interval_seconds`, a leading `-P` interval), and cron wall-clock fields are not Instants. Do not shift them by a timezone.

## 5. Runtime

- Deploy default process `TZ=UTC` (Dockerfile / Compose / `.env.example`). Override via standard `TZ` env only; no `APP_TIMEZONE`.
- Production must run with UTC. Declare `tzdata` so IANA data exists without relying on the host OS.
- Celery: assert `enable_utc=True` and `timezone="UTC"`.

## 6. Scheduled Task wall clock

- **Schedule Timezone** is the System Parameter `schedule_timezone` (IANA, seed `"UTC"`). Every cron schedule uses that one zone (DST rules below).
- The row stores `commitment_timezone`: the zone that produced the current `next_run_at`. It is not on the public wire. A successful write of the parameter realigns `next_run_at` for enabled cron rows whose commitment zone differs, before the response, and does not mint a Job. Beat sync repeats that realign and is a no-op when commitments already match. Enabling a paused cron row recomputes from the current zone.
- **`interval_seconds`** is a UTC absolute interval and **ignores** Schedule Timezone. After downtime, interval schedules (including the system reaper) may fire one catch-up beat.
- Product **cron** recovers one valid stored commitment, not a history of missed slots. An enabled row requires delivered `due_at == next_run_at <= now`, with the original due identity legal under the current expression, Schedule Timezone, start bound, and consumed cursor. Processing may occur outside a matching cron minute or after days of downtime. Preserve the original due Instant as `scheduled_for`; after consumption, advance directly to the next legal fire strictly after the processing Clock Instant. Never substitute the current minute or enumerate uncommitted slots. Replacement, pause/resume, and delete boundaries: `docs/business-scheduled-tasks.md`.
- Due processing samples Clock after the schedule row lock. `scheduled_for` is the original planned Instant; `created_at` is the actual Job mint Instant; `started_at` is the actual successful execution claim Instant. These are separate facts. Queued and cancelled-before-claim Jobs have null `started_at`; failed claims and duplicate deliveries do not fabricate or rewrite timestamps. Claim time means platform execution ownership, not necessarily the first business operation. Execution duration uses `started_at`, excluding scheduling delay and queue wait.
- `is_delayed_recovery` is persisted at a new enabled-cron mint when processing Clock is at least `due_at + 60 seconds`, using UTC Instant arithmetic, not display wall time. This minute-granularity classification is not a recovery grace period or runtime/queue timeout. Interval, run-now, and disabled/deleted cancelled mints are false. Historical false means recovery was not recorded, not proof of no delay. Lifecycle transitions and duplicate consumption preserve the flag (`docs/business-jobs.md`).
- `last_run_at` is the consumed-fire mint cursor, not `scheduled_for`, actual execution start, business success, or a stored next-run. Uniqueness repair retains the original Job `created_at` as last while computing cron next from the current processing Instant. All lifecycle and cursor stamps remain Instants.
- Do not repoint Celery process timezone to the business schedule zone.

### DST (same rule for all cron)

For cron expansion in the Schedule Timezone, **every** cron expression (including hourly) uses one wall-clock rule:

| Case | Rule |
|------|------|
| Nonexistent local time (spring forward) | Fire at the **next legal** local time |
| Ambiguous local time (fall back) | Fire on the **second** occurrence (`fold=1`) once — hourly does **not** fire twice |
| `interval_seconds` | Unaffected (UTC absolute) |

This matches Dagster’s **daily / weekly / monthly** DST handling. Dagster’s **hourly** path differs (skip gap to next cron match; fire both fold=0 and fold=1 on fall-back); refraq deliberately does **not** follow that split.

## 7. Forbidden (CI + review)

- `datetime.utcnow` / `datetime.utcfromtimestamp`
- Naive values in Instant API/ORM fields
- `naive.isoformat() + "Z"` (or equivalent strftime `Z` masking)
- Interpreting offset-less input via a non-UTC session
- Long-lived utcnow shims or naive-compatible Instant read paths
- Business-layer `ensure_aware_utc` / manual UTC “insurance”
- Treating Celery `timezone` as Schedule Timezone
- Mixing Session Redis TTL / `time.time()` epoch expiry into the Instant column contract

## 8. Display Timezone (Console edge only)

**Display Timezone** is an optional IANA preference on a **User** (`users.display_timezone`). The **Management Console** uses it to format Instants for that operator (`null` = follow the browser). HTTP, MCP, and Job log Instant strings continue to use `format_instant` → UTC **`Z`**. Do not bind actor Display TZ into Instant serializers or MCP dumps.

Display Timezone and **Schedule Timezone** share one catalog (`backend.core.time_zones`): zones named in tzdata `zone1970.tab`, plus `UTC`. Historical link names are aliases of that set, not extra choices. A **Display Timezone** write, and the upgrade fold of stored zones, store the current id (`Asia/Calcutta` is stored as `Asia/Kolkata`). `GET /time-zones` returns each id with its aliases (`docs/api-contracts-account.md`). The Schedule Timezone parameter enum is that same id list. A historical alias is not a member of the enum, and a settings write does not rewrite it.

When the browser rejects the stored id, formatting tries each alias, then formats in UTC and labels the text `UTC`. It does not switch to the browser zone.

A Console field that types an Instant (not Schedule Start) interprets that wall time in the same effective zone: the Display Timezone when the browser accepts it, otherwise the first accepted alias, otherwise UTC. An empty preference uses the browser zone, or UTC when that zone cannot be read. The field states the zone. Schedule Start stays wall time in the Schedule Timezone (§6).

## 9. Deferred / do not reverse direction

Product or ecosystem items that may land later must **not** rewrite Instant storage or the daily-for-all cron DST rule:

- RFC 9557 / IXDTF `[Zone]` suffixes on the wire (accept/ignore or reject at the boundary; do not store zone inside Instant)
- `whenever.Instant` (or similar) as the in-process Instant type (stdlib aware UTC remains the kernel)
- Epoch-ms / unix-seconds as the Instant wire format for HTTP/MCP
- Boundary helpers that treat naive datetime as UTC “for compatibility”
- Encoding a viewer’s Display Timezone into Instant JSON (offset or `[Zone]`)

## 10. Implementation entry

Unique Instant entry: `backend.core.time` (Clock, `utc_now`, Instant field, `UtcDateTime`, format/parse helpers). Shared zone catalog: `backend.core.time_zones` (`iana_zone_ids`, `zone_aliases`, `canonical_zone_id`).
See [`docs/modules.md`](modules.md) and [`docs/backend-layout.md`](backend-layout.md).
