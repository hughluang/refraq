# refraq API Contracts: Host

## 1. Purpose

This document defines `GET /host`, the read-only occupancy read for the Operations host screen.

Related boundaries:

- Console module: `docs/api-contracts-console.md`.
- Permission `host:read`: `docs/api-contracts-roles.md`.
- Errors and request IDs: `docs/conventions-errors.md`.
- Instants: `docs/conventions-time.md`.

The read queries the series store and returns host CPU occupancy. It is not the unpublished process `/metrics` endpoint, and it does not return process-capacity gauges. The browser calls the Console origin. The series store address is not part of this response.

## 2. Authorization

Session or User PAT. The read requires `host:read`.

- No credentials: `AUTH_UNAUTHENTICATED`, HTTP 401.
- Authenticated without `host:read`: `AUTH_FORBIDDEN`, HTTP 403. This includes the seeded operator Role and a Role that holds Source maintainer keys but not `host:read`.
- `super_admin` can read, because effective permissions are the catalog.
- A User PAT whose Role holds `host:read` can read with no Session cookie.

`console:access` and `jobs:run` do not grant this read. A **Source Access Level** does not grant it. Existing custom Roles do not receive the key until it is granted. Foundation Upgrade does not rewrite stored permission lists to add it.

## 3. `GET /host`

Purpose: read current CPU tiles and the CPU mode and run-queue charts for one span.

The only query parameter is `span`: `hour`, `day`, or `retained`. An omitted span is `day`. Any other value is `REQUEST_INVALID`, HTTP 422.

The client sends that span. It does not send a query expression, a step, or a time. The server captures one end Instant from the platform clock and uses it for every query in the request.

| `span` | Window | `step_seconds` |
| --- | --- | --- |
| `hour` | 3600 seconds | 30 |
| `day` | 86400 seconds | 121 |
| `retained` | 1296000 seconds, the store time-retention limit used as a bounded query window | 1803 |

`step_seconds` is `max(30, ceil(window / 719))` in whole seconds. Range evaluation includes both endpoints, so dividing by 720 could return 721 points. Each returned series has at most 720 points.

The response includes `span`, `start`, `end`, and `step_seconds`. Step is computed from the query window. A leading stretch where every returned series is absent is removed from `start`. Step is not recomputed after that trim. An empty store returns empty tiles and charts and still returns the query window's `start`, `end`, and `step_seconds`.

Tiles are the last sample within 60 seconds. No sample in that window is JSON `null`, not zero. Rate expressions use a lookback of at least 120 seconds, including when the step is 30. Chart gaps stay empty: `v` is `null`, with no fill across the gap.

### 3.1 CPU

| Reading | Series |
| --- | --- |
| `tiles.cpu.online_count` | `count(node_cpu_seconds_total{mode="idle"})`, last sample within 60 seconds |
| `tiles.cpu.busy_share` | Sum of per-mode rates for modes other than `idle`, `iowait`, `guest`, and `guest_nice`, divided by the sum of per-mode rates for modes other than `guest` and `guest_nice`. Rate lookback is 120 seconds. The value counts only when a sample exists within 60 seconds |
| `charts.cpu_modes` | `rate(node_cpu_seconds_total[120s])` for every reported mode, including `guest` and `guest_nice` |
| `charts.run_queue` | `node_procs_running` as recorded. Not a rate and not load average |

Guest modes appear on the mode chart and are not added into `busy_share`.

### 3.2 Response: `200`

```json
{
  "span": "day",
  "start": "2026-11-11T00:00:00Z",
  "end": "2026-11-12T00:00:00Z",
  "step_seconds": 121,
  "tiles": { "cpu": { "online_count": 4, "busy_share": 0.25 } },
  "charts": {
    "cpu_modes": [{ "mode": "user", "samples": [{ "t": "2026-11-12T00:00:00Z", "v": 0.1 }] }],
    "run_queue": [{ "t": "2026-11-12T00:00:00Z", "v": 2 }]
  }
}
```

`start`, `end`, and each sample `t` are Instants in UTC with a trailing `Z`. `v` is `null` when that step has no sample. The body has no `entity_id` and no `channel_id`.

An empty store uses the same tile and chart keys, with `online_count` and `busy_share` set to `null` and both chart arrays empty.

## 4. `HOST_SERIES_UNAVAILABLE`

When the series store query cannot be completed, the response is Problem Details:

- Code: `HOST_SERIES_UNAVAILABLE`
- HTTP 503
- `Content-Type: application/problem+json`
- No `Retry-After`

The body is not a success payload of zeros. This 503 is the outbound store being unreachable. It is not the platform capacity rejection.

## 5. Non-Goals

- Publishing the series store, or any collector, to the browser.
- Changing process `/metrics`, `/healthz`, or `/readyz`.
- Thresholds, forecasts, status chips, or mail from this read.
- Create, edit, or delete of a host record.
