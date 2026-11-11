# refraq API Contracts: Host

## 1. Purpose

This document defines `GET /host`, the read-only occupancy read for the Operations host screen.

Related boundaries:

- Console module: `docs/api-contracts-console.md`.
- Permission `host:read`: `docs/api-contracts-roles.md`.
- Errors and request IDs: `docs/conventions-errors.md`.
- Instants: `docs/conventions-time.md`.

The read queries the series store and returns host CPU, memory, swap, filesystem, disk, pressure, and Postgres occupancy. It is not the unpublished process `/metrics` endpoint, and it does not return process-capacity gauges or Compose supply settings. The browser calls the Console origin. The series store address is not part of this response.

## 2. Authorization

Session or User PAT. The read requires `host:read`.

- No credentials: `AUTH_UNAUTHENTICATED`, HTTP 401.
- Authenticated without `host:read`: `AUTH_FORBIDDEN`, HTTP 403. This includes the seeded operator Role and a Role that holds Source maintainer keys but not `host:read`.
- `super_admin` can read, because effective permissions are the catalog.
- A User PAT whose Role holds `host:read` can read with no Session cookie.

`console:access` and `jobs:run` do not grant this read. A **Source Access Level** does not grant it. Existing custom Roles do not receive the key until it is granted. Foundation Upgrade does not rewrite stored permission lists to add it.

## 3. `GET /host`

Purpose: read current host tiles and the host charts for one span.

The only query parameter is `span`: `hour`, `day`, or `retained`. An omitted span is `day`. Any other value is `REQUEST_INVALID`, HTTP 422.

The client sends that span. It does not send a query expression, a step, or a time. The server captures one end Instant from the platform clock and uses it for every query in the request.

| `span` | Window | `step_seconds` |
| --- | --- | --- |
| `hour` | 3600 seconds | 30 |
| `day` | 86400 seconds | 121 |
| `retained` | 1296000 seconds, the store time-retention limit used as a bounded query window | 1803 |

`step_seconds` is `max(30, ceil(window / 719))` in whole seconds. Range evaluation includes both endpoints, so dividing by 720 could return 721 points. Each returned series has at most 720 points.

The response includes `span`, `start`, `end`, and `step_seconds`. Step is computed from the query window. A leading stretch where every returned series is absent is removed from `start`. CPU mode, run queue, filesystem available, disk, pressure, and Postgres chart series all take part in that trim. Step is not recomputed after the trim. An empty store returns empty tiles and charts and still returns the query window's `start`, `end`, and `step_seconds`.

Tiles are the last sample within 60 seconds. No sample in that window is JSON `null`, not zero. Rate expressions use a lookback of at least 120 seconds, including when the step is 30. Chart gaps stay empty: `v` is `null`, with no fill across the gap.

### 3.1 CPU

| Reading | Series |
| --- | --- |
| `tiles.cpu.online_count` | `count(node_cpu_seconds_total{mode="idle"})`, last sample within 60 seconds |
| `tiles.cpu.busy_share` | Sum of per-mode rates for modes other than `idle`, `iowait`, `guest`, and `guest_nice`, divided by the sum of per-mode rates for modes other than `guest` and `guest_nice`. Rate lookback is 120 seconds. The value counts only when a sample exists within 60 seconds |
| `charts.cpu_modes` | `rate(node_cpu_seconds_total[120s])` for every reported mode, including `guest` and `guest_nice` |
| `charts.run_queue` | `node_procs_running` as recorded. Not a rate and not load average |

Guest modes appear on the mode chart and are not added into `busy_share`.

### 3.2 Memory and swap

| Reading | Series |
| --- | --- |
| `tiles.memory.total_bytes` | `node_memory_MemTotal_bytes`, last sample within 60 seconds |
| `tiles.memory.used_bytes` | `node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes`, last sample within 60 seconds |
| `tiles.swap.total_bytes` | `node_memory_SwapTotal_bytes`, last sample within 60 seconds |
| `tiles.swap.used_bytes` | Swap total minus `node_memory_SwapFree_bytes` |

`used_bytes` is `null` when either series it depends on is absent. A present `0` stays `0`. Swap total `0` and swap free `0` therefore stay `used_bytes` `0` and `total_bytes` `0`.

### 3.3 Filesystems

Filesystem rows come from `node_filesystem_size_bytes` and `node_filesystem_avail_bytes`, identified by the collector's reported mount (`mountpoint`) and type (`fstype`). The read does not apply a second mount exclusion list. It omits a row whose mount is `/var/lib/postgresql`.

| Reading | Rule |
| --- | --- |
| `tiles.filesystems[].used_bytes` | Size minus available. `null` when either series is absent for that mount and type |
| `tiles.filesystems[].total_bytes` | `node_filesystem_size_bytes`. `null` when that series is absent |
| `tiles.filesystems[].used_share` | `used_bytes / total_bytes` when `total_bytes` is non-zero. `null` when the share cannot be calculated |
| `tiles.filesystems[].free_inodes` | `node_filesystem_files_free`. `null` when that series is absent, not zero |
| `charts.filesystems[].available` | `node_filesystem_avail_bytes` as recorded over the span. Not a rate |
| `charts.filesystems[].delta` | Each available sample minus the previous sample in the returned span. The first sample is `null`. A sample whose previous sample has no value is `null` |

Tiles use the last sample within 60 seconds. The same mount omission applies to the chart.

### 3.4 Disk

Disk charts are grouped by `device` and are not summed across devices.

| Reading | Series |
| --- | --- |
| `charts.disks[].busy_share` | `rate(node_disk_io_time_seconds_total[120s])` |
| `charts.disks[].queue_length` | `rate(node_disk_io_time_weighted_seconds_total[120s])` |

A device that has samples for only one of the two series has an empty array for the other. An empty array is not a series of zeros.

### 3.5 Pressure

Pressure charts are the rates of the CPU, memory, and I/O waiting and stalled counters, each with a 120 second lookback:

- `node_pressure_cpu_waiting_seconds_total`
- `node_pressure_cpu_stalled_seconds_total`
- `node_pressure_memory_waiting_seconds_total`
- `node_pressure_memory_stalled_seconds_total`
- `node_pressure_io_waiting_seconds_total`
- `node_pressure_io_stalled_seconds_total`

`charts.pressure` has `cpu`, `memory`, and `io`. Each has `waiting` and `stalled`. A counter with no series is an empty array, not zeros. A recorded zero stays zero. The CPU stalled counter can be absent; that array stays empty.

### 3.6 Postgres

Postgres tiles are the last sample within 60 seconds. No sample in that window is `null`, not zero. A recorded zero stays zero. Chart counters are the recorded samples, not rates and not per-step deltas. A chart with no samples is an empty array. `max_connections` is the only connection ceiling. `superuser_reserved_connections` is not subtracted.

| Reading | Series |
| --- | --- |
| `tiles.postgres.backends` | Sum of `last_over_time(pg_stat_database_numbackends[60s])` |
| `tiles.postgres.max_connections` | `last_over_time(pg_settings_max_connections[60s])` |
| `charts.postgres.backends` | Sum of `pg_stat_database_numbackends` as recorded |
| `charts.postgres.idle_in_transaction` | Sum of `pg_stat_activity_count` for state `idle in transaction`, as recorded |
| `charts.postgres.idle_in_transaction_aborted` | Sum of `pg_stat_activity_count` for state `idle in transaction (aborted)`, as recorded |
| `charts.postgres.checkpoint_timed` | `pg_stat_checkpointer_num_timed_total` as recorded |
| `charts.postgres.checkpoint_requested` | `pg_stat_checkpointer_num_requested_total` as recorded |
| `charts.postgres.checkpoint_write_time` | `pg_stat_checkpointer_write_time_total` as recorded |
| `charts.postgres.checkpoint_sync_time` | `pg_stat_checkpointer_sync_time_total` as recorded |
| `charts.postgres.checkpoint_buffers_written` | `pg_stat_checkpointer_buffers_written_total` as recorded |
| `charts.postgres.temp_files` | Sum of `pg_stat_database_temp_files` as recorded |
| `charts.postgres.temp_bytes` | Sum of `pg_stat_database_temp_bytes` as recorded |

Database series are summed across their labels. The checkpointer series has no such labels. Idle states use an exact state match, so `idle in transaction` does not include `idle in transaction (aborted)`.

### 3.7 Response: `200`

```json
{
  "span": "day",
  "start": "2026-11-11T00:00:00Z",
  "end": "2026-11-12T00:00:00Z",
  "step_seconds": 121,
  "tiles": {
    "cpu": { "online_count": 4, "busy_share": 0.25 },
    "memory": { "used_bytes": 600, "total_bytes": 1000 },
    "swap": { "used_bytes": 0, "total_bytes": 0 },
    "filesystems": [
      {
        "mount": "/",
        "type": "ext4",
        "used_bytes": 750,
        "total_bytes": 1000,
        "used_share": 0.75,
        "free_inodes": null
      }
    ],
    "postgres": { "backends": 7, "max_connections": 100 }
  },
  "charts": {
    "cpu_modes": [{ "mode": "user", "samples": [{ "t": "2026-11-12T00:00:00Z", "v": 0.1 }] }],
    "run_queue": [{ "t": "2026-11-12T00:00:00Z", "v": 2 }],
    "filesystems": [
      {
        "mount": "/",
        "type": "ext4",
        "available": [
          { "t": "2026-11-11T00:00:00Z", "v": 250 },
          { "t": "2026-11-12T00:00:00Z", "v": 200 }
        ],
        "delta": [
          { "t": "2026-11-11T00:00:00Z", "v": null },
          { "t": "2026-11-12T00:00:00Z", "v": -50 }
        ]
      }
    ],
    "disks": [
      {
        "device": "sda",
        "busy_share": [{ "t": "2026-11-12T00:00:00Z", "v": 0.2 }],
        "queue_length": [{ "t": "2026-11-12T00:00:00Z", "v": 1.25 }]
      }
    ],
    "pressure": {
      "cpu": {
        "waiting": [{ "t": "2026-11-12T00:00:00Z", "v": 0.01 }],
        "stalled": []
      },
      "memory": { "waiting": [], "stalled": [] },
      "io": { "waiting": [], "stalled": [] }
    },
    "postgres": {
      "backends": [{ "t": "2026-11-12T00:00:00Z", "v": 7 }],
      "idle_in_transaction": [{ "t": "2026-11-12T00:00:00Z", "v": 3 }],
      "idle_in_transaction_aborted": [],
      "checkpoint_timed": [{ "t": "2026-11-12T00:00:00Z", "v": 11 }],
      "checkpoint_requested": [{ "t": "2026-11-12T00:00:00Z", "v": 4 }],
      "checkpoint_write_time": [{ "t": "2026-11-12T00:00:00Z", "v": 2500.5 }],
      "checkpoint_sync_time": [{ "t": "2026-11-12T00:00:00Z", "v": 12.5 }],
      "checkpoint_buffers_written": [{ "t": "2026-11-12T00:00:00Z", "v": 80 }],
      "temp_files": [{ "t": "2026-11-12T00:00:00Z", "v": 5 }],
      "temp_bytes": [{ "t": "2026-11-12T00:00:00Z", "v": 1500 }]
    }
  }
}
```

`start`, `end`, and each sample `t` are Instants in UTC with a trailing `Z`. `v` is `null` when that step has no sample. The body has no `entity_id` and no `channel_id`.

An empty store uses the same tile and chart keys. `online_count`, `busy_share`, memory bytes, swap bytes, `tiles.postgres.backends`, and `tiles.postgres.max_connections` are `null`. Filesystem, disk, CPU mode, and run-queue arrays are empty. Each pressure side is an empty array. Each Postgres chart array is empty.

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
- Returning `shm_size`, `shared_buffers`, `work_mem`, or `effective_cache_size`.
- Create, edit, or delete of a host record.
