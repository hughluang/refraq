# refraq API Contracts: Data Channel

## 1. Purpose

This document defines the HTTP contract for **Data Channel** definitions and runs: the node type catalog, channel create, read, edit, and delete, draft save, validate, publish with its confirmation list, **Channel Version** reads, the activation switch, manual runs, and the run list. Paths address a channel by opaque `id`.

Run records with node executions, editor execution (execute up to a node, pinned data, write dry run), **Global Variable**s, **Source Mirror**s, and the **Notification Channel** are not defined here.

Related boundaries:

- Business rules: `docs/business-data-channel.md`
- Scheduled Task rows synced from Scheduled nodes: `docs/api-contracts-schedules.md`
- Platform Job observe and cancel: `docs/api-contracts-jobs.md`
- Business Entity definitions referenced by nodes: `docs/api-contracts-entity.md`
- Problem Details and Problem Codes: `docs/conventions-errors.md`
- **Offset Page** lists: `docs/conventions-pagination.md`
- **Instant** wire form: `docs/conventions-time.md`
- Terminology: `docs/glossary.md`

## 2. Cross-Cutting Rules

### 2.1 Transport

Success responses use `application/json`. Every HTTP failure uses RFC 9457 Problem Details (`application/problem+json`) with `type` derived as `urn:refraq:problem:{CODE}`. First-party clients branch on `code`.

Authentication is a Session cookie or a **User PAT** Bearer token. Unauthenticated requests return `401 AUTH_UNAUTHENTICATED`. Authenticated callers lacking the required **Permission** return `403`. Every permission in this document is `platform`-scoped.

Every response echoes `X-Request-ID`. Instants on the wire are UTC with a `Z` suffix. Unknown fields on a request object are rejected with `422 REQUEST_INVALID`.

### 2.2 Offset Page

Collection lists use the **Offset Page** envelope `{ "items", "total", "limit", "offset" }`. Each list declares its default and max `limit`. Out-of-range `limit` or `offset` is `422 REQUEST_INVALID`. An `offset` past the end is `200` with empty `items` and the same `total`.

### 2.3 Identifiers

| Resource | Example | Rule |
| --- | --- | --- |
| Data Channel | `chn_01HZX` | Opaque server-issued id |
| Channel Version | `3` | Positive integer, numbered from 1 per channel |
| Node | `nd_7f3a9c` | Client-assigned when the node is created; 1 to 64 characters of ASCII letters, digits, `_`, and `-`; unique within a graph; stable across saves and versions |
| Edge | `ed_19b2` | Client-assigned; same character rule; unique within a graph |
| Job | `job_01HZX` | Platform Job id (`docs/api-contracts-jobs.md`) |

## 3. Resource Shapes

### 3.1 Data Channel

```json
{
  "id": "chn_01HZX",
  "name": "Material master",
  "description": "Material master from U9 and PLM",
  "active": false,
  "draft_revision": 12,
  "draft_updated_at": "2026-10-09T08:00:00Z",
  "latest_version": { "number": 3, "published_at": "2026-10-08T09:30:00Z" },
  "created_at": "2026-10-01T02:00:00Z",
  "updated_at": "2026-10-09T08:00:00Z"
}
```

- `name` is required, trimmed, 1 to 200 characters, and not unique. `description` is optional, at most 2000 characters, or `null`.
- `active` is the activation switch. It starts `false` and changes only through §5.10.
- `latest_version` is `null` until the first publish.

### 3.2 Graph

```json
{
  "nodes": [
    {
      "id": "nd_trigger",
      "type": "trigger.manual",
      "name": "Run manually",
      "position": { "x": 0, "y": 0 },
      "config": {},
      "on_error": "stop",
      "retry": null
    },
    {
      "id": "nd_read",
      "type": "read.entity",
      "name": "Read suppliers",
      "position": { "x": 240, "y": 0 },
      "config": { "entity_id": "ent_01HZX", "filters": [] },
      "on_error": "stop",
      "retry": { "max_tries": 3, "wait_sec": 10 }
    },
    {
      "id": "nd_write",
      "type": "write.entity",
      "name": "Write materials",
      "position": { "x": 480, "y": 0 },
      "config": {
        "entity_id": "ent_02ABC",
        "mode": "upsert",
        "match_key": null,
        "mapping": [
          { "attribute": "sku", "value": "{{ item[\"code\"].strip() }}" },
          { "attribute": "name", "value": "{{ item[\"name\"] }}" }
        ],
        "on_incompatible_head": "fail"
      },
      "on_error": "stop",
      "retry": null
    }
  ],
  "edges": [
    { "id": "ed_1", "source": { "node_id": "nd_trigger", "port": "main" }, "target": { "node_id": "nd_read", "port": "main" } },
    { "id": "ed_2", "source": { "node_id": "nd_read", "port": "main" }, "target": { "node_id": "nd_write", "port": "main" } }
  ],
  "settings": { "run_timeout_sec": null, "error_channel_id": null }
}
```

Node fields:

| Field | Rule |
| --- | --- |
| `id` | §2.3 |
| `type` | A node type id from the catalog (§3.7) |
| `name` | Trimmed, 1 to 128 characters, unique within the graph |
| `position` | Canvas coordinates; numbers; not interpreted by the server |
| `config` | Object validated against the node type's `config_schema` at validate and publish. Save accepts any object |
| `on_error` | `stop` (default), `continue`, or `error_output` |
| `retry` | `null`, or `{ "max_tries", "wait_sec" }` with `max_tries` from 1 through 10 and `wait_sec` from 0 through 3600 |

Edge `source.port` and `target.port` name ports declared by the node types. Graph `settings.run_timeout_sec` is `null` or a positive integer of seconds at most 252460800. `settings.error_channel_id` is `null` or another Data Channel id.

Write Entity configuration (`write.entity`):

| Field | Rule |
| --- | --- |
| `entity_id` | Target Business Entity id |
| `mode` | `upsert`, `create`, `update`, or `delete` |
| `match_key` | `null` means the target head's **Business Key**; otherwise the name of a `unique` attribute on the head. `row_id` is never accepted |
| `mapping` | List of `{ "attribute", "value" }`; `attribute` names a head attribute at most once; `value` is an expression. `delete` ignores it |
| `on_incompatible_head` | `fail` (default) or `skip` |

### 3.3 Channel Version

```json
{
  "channel_id": "chn_01HZX",
  "number": 3,
  "graph": { "nodes": [], "edges": [], "settings": { "run_timeout_sec": null, "error_channel_id": null } },
  "published_at": "2026-10-08T09:30:00Z",
  "published_by_user_id": "usr_01HZX",
  "published_by_name": "Alice"
}
```

`published_by_name` is presentation only and is `null` when the User no longer resolves. List items omit `graph`.

### 3.4 Problem Entry

Validation reports problems as result documents, not as Problem Details:

```json
{ "code": "CHANNEL_GRAPH_CYCLE", "node_id": "nd_read", "edge_id": "ed_2", "detail": "Cycle does not pass through a Loop node" }
```

`node_id` and `edge_id` are each the offending node or edge, or `null`. `detail` is English occurrence text. Codes are listed in §6.2.

### 3.5 Confirmation List

```json
{
  "draft_revision": 12,
  "mirrors_to_open": [
    { "object_id": "obj_01HZX", "locator": "obj/u9-prod/dbo/cbo_itemmaster" }
  ],
  "runs_to_cancel": [
    { "job_id": "job_01HZX", "version": 2, "started_at": "2026-10-09T07:58:00Z" }
  ],
  "missing_run_timeout": true
}
```

Sections are empty lists, or `false`, when there is nothing to show.

### 3.6 Channel Run

```json
{
  "job_id": "job_01HZX",
  "status": "succeeded",
  "outcome": "completed",
  "version": 3,
  "trigger_kind": "user",
  "trigger_ref": "usr_01HZX",
  "trigger_node_id": "nd_trigger",
  "trigger_actor_name": "Alice",
  "trigger_schedule_name": null,
  "ignore_checkpoints": false,
  "created_at": "2026-10-09T08:00:00Z",
  "started_at": "2026-10-09T08:00:01Z",
  "finished_at": "2026-10-09T08:00:41Z",
  "error_code": null,
  "error_message": null
}
```

- `status` is the Job status (`queued`, `running`, `succeeded`, `failed`, `cancelled`).
- `outcome` is `completed` or `skipped` when `status` is `succeeded`, otherwise `null`.
- `version` is the Channel Version the runner resolved at start, or `null` before the run starts or when it ended before resolving one.
- `trigger_kind` is `user` for a manual run, `schedule` for a Scheduled node, and `system` for platform-event and change-arrival triggers. `trigger_ref`, `trigger_actor_name`, and `trigger_schedule_name` follow the Job contract.
- Duration is derived by clients from `started_at` and `finished_at`.

### 3.7 Node Type

```json
{
  "type": "write.entity",
  "family": "write",
  "entry": false,
  "inputs": [{ "port": "main" }],
  "outputs": [{ "port": "main" }, { "port": "error" }],
  "config_schema": { "type": "object" },
  "permission": null
}
```

- `family` is `trigger`, `read`, `transform`, `volume`, `state`, or `write`.
- `entry` is `true` for trigger types; they declare no inputs.
- `config_schema` is a JSON Schema object that the Console renders as the configuration panel and the server enforces at validate and publish.
- `permission` names the extra Permission needed to add or edit a node of this type (`channel:code_write` for `transform.code`), or `null`.
- Display labels are Console i18n keys derived from `type`; the catalog does not carry localized text.

## 4. Job Kind `channel_run`

### 4.1 Lifecycle

A `channel_run` Job follows the platform Job lifecycle (`docs/business-jobs.md`). It takes no execution lock and never ends with `JOB_ALREADY_ACTIVE`. Cancel uses `POST /jobs/{id}/cancel`.

### 4.2 Input

```json
{ "channel_id": "chn_01HZX", "trigger_node_id": "nd_trigger", "ignore_checkpoints": false }
```

The input carries no version. The runner resolves the current published version at start.

### 4.3 Result

On `succeeded` only:

```json
{ "schema": "channel_run.v1", "channel_id": "chn_01HZX", "version": 3, "outcome": "completed" }
```

`outcome` is `completed` or `skipped`. Failed and cancelled runs leave `result` `null`.

## 5. Endpoints

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `GET` | `/channel-node-types` | `channel:read` | Node type catalog |
| `POST` | `/channels` | `channel:write` | Create a channel with an empty draft |
| `GET` | `/channels` | `channel:read` | List channels (**Offset Page**) |
| `GET` | `/channels/{id}` | `channel:read` | Get one channel |
| `PATCH` | `/channels/{id}` | `channel:write` | Edit `name` and `description` |
| `DELETE` | `/channels/{id}` | `channel:write` | Delete the channel |
| `GET` | `/channels/{id}/draft` | `channel:read` | Read the draft graph |
| `PUT` | `/channels/{id}/draft` | `channel:write` | Replace the draft graph |
| `POST` | `/channels/{id}/draft/validate` | `channel:write` | Validate the stored draft |
| `POST` | `/channels/{id}/publish/preview` | `channel:write` | Compute the confirmation list |
| `POST` | `/channels/{id}/publish` | `channel:write` | Publish the draft as a new version |
| `GET` | `/channels/{id}/versions` | `channel:read` | List versions (**Offset Page**) |
| `GET` | `/channels/{id}/versions/{number}` | `channel:read` | Read one version with its graph |
| `POST` | `/channels/{id}/activate` | `channel:run` | Turn the activation switch on |
| `POST` | `/channels/{id}/deactivate` | `channel:run` | Turn the activation switch off |
| `POST` | `/channels/{id}/runs` | `channel:run` | Start a manual run |
| `GET` | `/channels/{id}/runs` | `channel:read` | List this channel's runs (**Offset Page**) |

### 5.1 `GET /channel-node-types`

`200` `{ "items": [ … ] }` with every node type (§3.7). The catalog is a whole-set read, ordered by `family` then `type`.

### 5.2 `POST /channels`

```json
{ "name": "Material master", "description": null }
```

`201` `{ "channel": { … } }`. The draft starts as `{ "nodes": [], "edges": [], "settings": { "run_timeout_sec": null, "error_channel_id": null } }` with `draft_revision` 1. `active` is `false`.

### 5.3 `GET /channels`

Query: `q` (optional literal substring of `name`), `active` (`true` | `false` | omitted), `limit` (default 50, max 200), `offset` (default 0). Ordered by `created_at DESC`, `id DESC`.

### 5.4 `PATCH /channels/{id}`

Any subset of `name` and `description`. Present `description` `null` clears it. `200` `{ "channel": { … } }`. Does not touch the draft, versions, or schedule rows. Synced schedule rows keep their stored names.

### 5.5 `DELETE /channels/{id}`

`204`. Withdraws schedule rows whose `owner_ref` is `channel:{id}`, requests cancel of the channel's other unfinished runs, and removes the channel, its draft, its versions, its checkpoints, and its run records. Historical Jobs remain. Rows already written to Entity Tables stay.

### 5.6 `GET` and `PUT /channels/{id}/draft`

`GET` returns `{ "draft_revision", "draft_updated_at", "graph" }`.

`PUT` body:

```json
{ "base_revision": 12, "graph": { "nodes": [], "edges": [], "settings": { "run_timeout_sec": null, "error_channel_id": null } } }
```

- `base_revision` must equal the stored `draft_revision`; otherwise `409 CHANNEL_DRAFT_CONFLICT`.
- Save checks shape only: identifier rules, unique node and edge ids, field types and ranges in §3.2. It does not check node configuration against the catalog, references, or graph rules; a draft may be incomplete.
- Adding a node whose type declares a `permission`, or changing such a node's `config`, requires that Permission (`403`).
- `200` `{ "draft_revision", "draft_updated_at", "graph" }` with `draft_revision` incremented by one. Save never changes a version or a schedule row.

### 5.7 `POST /channels/{id}/draft/validate`

Empty body. Validates the stored draft. `200`:

```json
{ "draft_revision": 12, "valid": false, "problems": [ { "code": "CHANNEL_GRAPH_NO_TRIGGER", "node_id": null, "edge_id": null, "detail": "Graph has no trigger node" } ] }
```

An invalid graph is a `200` result, not a Problem Details failure. Validate writes nothing.

### 5.8 `POST /channels/{id}/publish/preview` and `POST /channels/{id}/publish`

Preview takes an empty body and returns `200` with the confirmation list (§3.5) for the stored draft. It writes nothing. It does not require the draft to be valid.

Publish body:

```json
{ "draft_revision": 12 }
```

- `draft_revision` must equal the stored revision, so the published graph is the previewed graph; otherwise `409 CHANNEL_DRAFT_CONFLICT`.
- An invalid draft is refused with `422 CHANNEL_GRAPH_INVALID`; `detail` names the first problem, and the full list comes from validate.
- The caller must hold every Permission declared by node types present in the draft.
- `201` `{ "version": { … }, "confirmation": { … } }`, where `confirmation` is the list as applied at publish. Publish stores the version, reconciles schedule rows, requests cancel of older-version runs, and requests opening of the listed mirrors (`docs/business-data-channel.md` §3.5). It does not change `active`.

### 5.9 `GET /channels/{id}/versions` and `GET /channels/{id}/versions/{number}`

List query: `limit` (default 50, max 200), `offset` (default 0). Ordered by `number DESC`. Items omit `graph`. Get returns `{ "version": { … } }` with `graph`. Unknown number is `404 CHANNEL_VERSION_NOT_FOUND`.

### 5.10 `POST /channels/{id}/activate` and `POST /channels/{id}/deactivate`

Empty body. `200` `{ "channel": { … } }`. Idempotent: activating an active channel, or deactivating an inactive one, succeeds without change. Activate sets every synced schedule row `enabled`; deactivate disables them and does not cancel queued or running Jobs. Activating a channel with no published version is allowed and has no schedule rows to enable.

### 5.11 `POST /channels/{id}/runs`

```json
{ "ignore_checkpoints": false, "trigger_node_id": "nd_trigger" }
```

- `trigger_node_id` names a Manual trigger node in the current published version. It may be omitted when that version has exactly one Manual trigger node.
- `ignore_checkpoints` defaults to `false`.
- Allowed while the channel is inactive.
- `202` `{ "run": { … } }` (§3.6) with `status` `queued`, `trigger_kind` `user`, and `trigger_ref` the acting User.
- No published version is `409 CHANNEL_NOT_PUBLISHED`. A missing, non-Manual, or ambiguous trigger node is `422 CHANNEL_TRIGGER_INVALID`.

### 5.12 `GET /channels/{id}/runs`

Query: `status` (optional Job status), `limit` (default 50, max 200), `offset` (default 0). Ordered by `created_at DESC`, `id DESC`. Items are Channel Runs (§3.6) of every trigger kind for this channel.

## 6. Errors

### 6.1 HTTP Problem Codes

| Code | HTTP | When |
| --- | --- | --- |
| `CHANNEL_NOT_FOUND` | 404 | No Data Channel for this id |
| `CHANNEL_VERSION_NOT_FOUND` | 404 | No version with this number on the channel |
| `CHANNEL_DRAFT_CONFLICT` | 409 | `base_revision` or `draft_revision` is not the stored draft revision |
| `CHANNEL_GRAPH_INVALID` | 422 | Publish of a draft that fails validation |
| `CHANNEL_NOT_PUBLISHED` | 409 | Manual run of a channel with no published version |
| `CHANNEL_TRIGGER_INVALID` | 422 | Manual run names a missing or non-Manual trigger node, or omits it when the version has several |
| `REQUEST_INVALID` | 422 | Unknown fields, malformed identifiers, or out-of-range fields |

### 6.2 Validation Problem Codes

| Code | When |
| --- | --- |
| `CHANNEL_GRAPH_NO_TRIGGER` | The graph has no trigger node |
| `CHANNEL_GRAPH_TRIGGER_INPUT` | A trigger node has an inbound edge |
| `CHANNEL_GRAPH_UNREACHABLE` | A node is not reachable from any trigger node |
| `CHANNEL_GRAPH_CYCLE` | A cycle does not pass through a Loop node |
| `CHANNEL_GRAPH_EDGE_INVALID` | An edge names an unknown node or port |
| `CHANNEL_NODE_TYPE_UNKNOWN` | A node names an unknown node type |
| `CHANNEL_NODE_CONFIG_INVALID` | A node configuration does not satisfy its `config_schema` |
| `CHANNEL_NODE_NAME_DUP` | Two nodes share a name |
| `CHANNEL_REFERENCE_UNRESOLVED` | A configuration names an Entity, attribute, Catalog Object, Locator, Source, or Data Channel that does not resolve |
| `CHANNEL_MATCH_KEY_INVALID` | A write node's match key does not resolve: no Business Key for the default, or a named attribute that is missing, not `unique`, or `row_id` |

### 6.3 Job Error Codes

| Code | When |
| --- | --- |
| `CHANNEL_RUN_TIMEOUT` | The graph run timeout elapsed; the run log names the node it stopped at |
| `CHANNEL_WRITE_INCOMPATIBLE` | A write node with policy `fail` met a head its mapping is incompatible with |
| `CHANNEL_ITEM_LIMIT_EXCEEDED` | One node execution exceeded the in-memory item limit |
| `CHANNEL_NODE_FAILED` | A node failed with `on_error` `stop`; the run log names the node and its error |

`JOB_WORKER_LOST` applies as for every Job. `JOB_RUNNING_TIMEOUT` does not occur, because channel schedule rows carry no **Running Time Limit**.

## 7. Non-Goals

1. Run records with per-node-execution input and output, and editor execution.
2. Rerun and resume endpoints.
3. A channel-scoped cancel route; cancel is the platform Job cancel.
4. Creating, editing, deleting, or running channel schedule rows through the schedule surface.
5. MCP tools for Data Channel.
