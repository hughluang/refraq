# Time Conventions

Authoritative Instant / Schedule Timezone contract for refraq.
Hard trade-offs and rationale: [`docs/adr/0022-unified-time-contract.md`](adr/0022-unified-time-contract.md).
Domain terms: root `CONTEXT.md`, [`docs/glossary.md`](glossary.md).

## 1. Two concepts (do not mix)

| Concept | Meaning | Storage / wire |
|---------|---------|----------------|
| **Instant** | Absolute moment on the timeline | Aware UTC in process; `timestamptz` in Postgres; RFC 3339 with offset on the wire (outbound always `Z`) |
| **Schedule Timezone** | IANA zone on a **Scheduled Task** that interprets **cron** wall-clock fields | Separate string column; **not** stored inside an Instant; **ignored** for `interval_seconds` |

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

## 5. Runtime

- Deploy default process `TZ=UTC` (Dockerfile / Compose / `.env.example`). Override via standard `TZ` env only; no `APP_TIMEZONE`.
- Production must run with UTC. Declare `tzdata` so IANA data exists without relying on the host OS.
- Celery: assert `enable_utc=True` and `timezone="UTC"`.

## 6. Scheduled Task wall clock

- Every Scheduled Task has **Schedule Timezone** (IANA, default `"UTC"`).
- **Cron** uses that zone for wall-clock interpretation (DST rules below).
- **`interval_seconds`** is a UTC absolute interval and **ignores** Schedule Timezone. After downtime, interval schedules (including the system reaper) may fire one catch-up beat.
- Product **cron** does **not** catch up missed slots. After downtime, the next fire is the next legal wall-clock slot at or after now (the current minute if it matches the expression and that slot Instant is later than `last_run_at`).
- `last_run_at` and Job lifecycle stamps remain Instants. `last_run_at` is a consumed-fire cursor, not a stored next-run.
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

## 9. Deferred / do not reverse direction

Product or ecosystem items that may land later must **not** rewrite Instant storage or the daily-for-all cron DST rule:

- RFC 9557 / IXDTF `[Zone]` suffixes on the wire (accept/ignore or reject at the boundary; do not store zone inside Instant)
- `whenever.Instant` (or similar) as the in-process Instant type (stdlib aware UTC remains the kernel)
- Epoch-ms / unix-seconds as the Instant wire format for HTTP/MCP
- Boundary helpers that treat naive datetime as UTC “for compatibility”
- Encoding a viewer’s Display Timezone into Instant JSON (offset or `[Zone]`)

## 10. Implementation entry

Unique code entry: `backend.core.time` (Clock, `utc_now`, Instant field, `UtcDateTime`, format/parse helpers).
See [`docs/modules.md`](modules.md) and [`docs/backend-layout.md`](backend-layout.md).
