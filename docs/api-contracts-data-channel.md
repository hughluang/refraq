# refraq API Contracts: Data Channel

## 1. Purpose

This document defines the HTTP contract for **Data Channel** definitions and runs: the node type catalog, channel create, read, edit, and delete, draft save, validate, publish with its confirmation list, **Channel Version** reads, the activation switch, on-demand runs, the run list, run detail, the execution list, one execution's stored output, container rounds of a container execution, a **Node Sample** of one node against a run, **Template Preview**, dataset-row reads, and the **Channel Variable** list and manual delete. Paths address a channel by opaque `id`.

**Source Mirror**s are not defined here. **Webhook** HTTP is `docs/api-contracts-webhooks.md`. **Email Account** HTTP is `docs/api-contracts-email-accounts.md`. **HTTP Account** HTTP is `docs/api-contracts-http-accounts.md`. Global Variable HTTP is `docs/api-contracts-global-variables.md`.

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
| Channel Note | `nt_intro` | Client-assigned; same character rule as a node id; unique across the node, edge, and note ids of the graph |
| Job | `job_01HZX` | Platform Job id (`docs/api-contracts-jobs.md`) |
| Dataset | `ds_01HZX` | Opaque server-issued id. The reference carries this id and no physical relation |

## 3. Resource Shapes

### 3.1 Data Channel

```json
{
  "id": "chn_01HZX",
  "name": "Material master",
  "description": "Material master from U9 and PLM",
  "active": false,
  "failure_streak": 0,
  "persistently_failing": false,
  "draft_revision": 12,
  "draft_updated_at": "2026-10-09T08:00:00Z",
  "latest_version": { "number": 3, "published_at": "2026-10-08T09:30:00Z" },
  "tags": [{ "id": "tag_01ABC", "name": "finance" }],
  "tag_revision": 2,
  "created_at": "2026-10-01T02:00:00Z",
  "updated_at": "2026-10-09T08:00:00Z"
}
```

- `name` is required, trimmed, 1 to 200 characters, and not unique. `description` is optional, at most 2000 characters, or `null`.
- `active` is the activation switch. It starts `false` and changes only through §5.10.
- `failure_streak` is the count of published failure episodes (§6.8 of the business rules). It starts at 0.
- `persistently_failing` is true when `failure_streak` is at least 3.
- `latest_version` is `null` until the first publish.
- `tags` is `{ "id", "name" }[]`, ordered by comparison form, then id. `tag_revision` starts at 1 and increases by 1 only when the set changes. List items, detail, and the create response include both. Comparison form is not a response field. Replacing Tags does not change `draft_revision`, `draft_updated_at`, or `updated_at`.

### 3.2 Graph

```json
{
  "nodes": [
    {
      "id": "nd_trigger",
      "ref": "run_manually",
      "type": "trigger.manual",
      "name": "Run manually",
      "position": { "x": 0, "y": 0 },
      "config": { "payload": {} },
      "on_error": "stop",
      "retry": null
    },
    {
      "id": "nd_read",
      "ref": "read_suppliers",
      "type": "read.sql",
      "name": "Read suppliers",
      "position": { "x": 240, "y": 0 },
      "config": { "sql": "SELECT code, name FROM suppliers", "statement_timeout_sec": 30 },
      "on_error": "stop",
      "retry": null
    },
    {
      "id": "nd_write",
      "ref": "write_materials",
      "type": "write.entity",
      "name": "Write materials",
      "position": { "x": 480, "y": 0 },
      "config": {
        "entity_id": "ent_02ABC",
        "mode": "upsert",
        "match_key": null,
        "source": "{{ self.read_suppliers.output.rows }}",
        "mapping": [
          { "attribute": "sku", "key": "code" },
          { "attribute": "name", "key": "name" }
        ],
        "on_incompatible_head": "fail"
      },
      "on_error": "stop",
      "retry": { "max_tries": 3, "wait_sec": 5 }
    }
  ],
  "edges": [
    { "id": "ed_1", "source": { "node_id": "nd_trigger", "port": "main" }, "target": { "node_id": "nd_read", "port": "main" } },
    { "id": "ed_2", "source": { "node_id": "nd_read", "port": "main" }, "target": { "node_id": "nd_write", "port": "main" } }
  ],
  "notes": [
    {
      "id": "nt_intro",
      "position": { "x": 40, "y": 80 },
      "size": { "width": 280, "height": 140 },
      "text": "Suppliers land in the material entity."
    }
  ],
  "settings": { "run_timeout_sec": null, "run_retry_limit": null, "error_channel_id": null }
}
```

Node fields:

| Field | Rule |
| --- | --- |
| `id` | §2.3 |
| `ref` | A Python identifier, 1 to 64 characters, unique within the graph. It does not start with `_`, is not a Python keyword, and is not `nodes`, `channel`, `run`, or `platform`. Templates name this node's output as `self.<ref>` |
| `type` | A node type id from the catalog (§3.7) |
| `type_version` | Integer, default `1`. Must equal the node type's current `type_version` |
| `name` | Trimmed, 1 to 128 characters, unique within the graph |
| `position` | Canvas coordinates; numbers; not interpreted by the server. When `parent` is set, the coordinates are relative to that container's frame. A container is a **For**, a Batch Read, or an **Until** |
| `parent` | Optional node id of a For, a Batch Read, or an Until, omitted when the node is not a direct child of one. JSON `null` means no parent. A stored node omits `parent` when it has none. The server stores no frame size |
| `config` | Object validated against the node type's `config_schema` at validate and publish. Save accepts any object |
| `on_error` | `stop`, `continue`, or `error_output`. `error_output` fails validation unless the node type declares an `error` output |
| `retry` | `null`, or `{ "max_tries", "wait_sec" }`. `max_tries` is 1 to 10 and includes the first execution. `wait_sec` is 0 to 3600. Null executes once |

Edge `source.port` and `target.port` name ports declared by the node types. An edge orders execution and selects a branch. It does not carry items. A container is a **For**, a Batch Read, or an **Until**. An edge from S to T crosses a container frame when the two `parent` values differ and S is not T's parent. Two omitted `parent` values are equal. A crossing is `CHANNEL_LOOP_BODY_INVALID` in either direction, including an edge from a body node to its container. The only edge that may enter a frame is that container's `each` port connected to a node whose `parent` is that container, and `each` connects only to such a node. `done` connects only to a node outside that frame. A `parent` that names a missing node or a node that is not a For, a Batch Read, or an Until, or a parent chain that contains a cycle, is `CHANNEL_LOOP_BODY_INVALID`. A For, a Batch Read, and an Until may nest in any combination. A cycle among edges is `CHANNEL_GRAPH_CYCLE`. Graph `settings.run_timeout_sec` is `null` or a positive integer of seconds at most 252460800. `settings.run_retry_limit` is `null` or an integer 0 to 10. `settings.error_channel_id` is `null` or another Data Channel id. Publish requires that channel's current published version to use `trigger.error` as its only trigger.

`notes` is optional and defaults to an empty list. A graph has at most 200 **Channel Note**s. Draft save, validate, and template preview accept this same graph shape.

Note fields:

| Field | Rule |
| --- | --- |
| `id` | §2.3 |
| `position` | `{ "x", "y" }`. Numbers. The server does not interpret them |
| `size` | `{ "width", "height" }`. Numbers. `width` is 160 to 2000 inclusive. `height` is 80 to 2000 inclusive |
| `text` | 0 to 4000 characters |

An unknown field on a note, on its `position`, or on its `size` is `422 REQUEST_INVALID`. A duplicate note id, or a note id equal to a node id or an edge id, is `422 REQUEST_INVALID` and names the field `graph`. More than 200 notes is `422 REQUEST_INVALID`.

A response that returns a stored graph omits `notes` when that graph has none. A client treats a missing `notes` as an empty list. Saving `notes` as `[]` stores no `notes` key.

A Channel Note does not take part in execution, validation problems, connections, or node-type permission checks.

Write Entity configuration (`write.entity`):

| Field | Rule |
| --- | --- |
| `entity_id` | Target Business Entity id |
| `mode` | `upsert`, `create`, `update`, or `delete` |
| `match_key` | `null` means the target head's **Business Key**; otherwise the name of a `unique` attribute on the head. `row_id` is never accepted |
| `source` | A template whose value is a list of objects or a **Dataset Reference** `{dataset_id, columns, count}` with no `relation`. Static JSON is the text itself. `{{ }}` calculates. A reference is resolved by `dataset_id` against the registry. Mapping renames columns by name the same way it renames object keys. A list longer than 100000 objects fails the node with `CHANNEL_ITEM_LIMIT_EXCEEDED` and the message `Use Materialize or Dataset Query, then Batch Read.` |
| `mapping` | List of `{ "attribute", "key" }`; `attribute` names a head attribute at most once; `key` is the source-object key renamed to it. Unmapped source keys are written under their own name. Every mode applies the list |
| `on_incompatible_head` | `fail` (default) or `skip` |
| `statement_timeout_sec` | Integer seconds from 1 to 3600. Absent means 300. Wall-clock limit of the whole write. Before each statement the remaining time is that statement's server timeout |

A dataset source is staged in full, validated in full, and written in one transaction. Any failure rolls the execution back and leaves the target unchanged. A list source is the same one transaction. One round of a Batch Read is one such transaction; the rounds are not combined. A dataset the node cannot read fails the node with `CHANNEL_DATASET_UNAVAILABLE`.

SQL configuration (`read.sql`):

| Field | Rule |
| --- | --- |
| `source` | Required object. `{"kind":"entity"}` or `{"kind":"source","source_id":"<Source id>"}`. `kind` `entity` rejects `source_id`. `kind` `source` requires `source_id`. Absent or any other shape is `CHANNEL_NODE_CONFIG_INVALID`. Validate and publish do not default a missing source to the entity database. A `source_id` that does not resolve is `CHANNEL_REFERENCE_UNRESOLVED` |
| `sql` | A template. Each `{{ }}` result is spliced as text, and the author quotes literals in the statement. The rendered text must be exactly one statement; otherwise the node fails with `CHANNEL_SQL_NOT_ONE_STATEMENT` and the driver is not called. On the entity database, unqualified names resolve in schema `entity_data` |
| `statement_timeout_sec` | Integer seconds from 1 to 3600. Absent means 30 |

A successful SQL execution returns `{rows, count, rowcount}`. `rows` is an array of objects and `count` is its length. Both are empty and 0 when the statement returns no result set. `rowcount` is an integer when the driver reports an affected-row count, otherwise `null`. More than 100000 rows fails the node with `CHANNEL_ITEM_LIMIT_EXCEEDED` and the message `Use Dataset Query, then Batch Read.` SQL does not return a **Dataset Reference**. Text that is not exactly one statement fails the node with `CHANNEL_SQL_NOT_ONE_STATEMENT` before the driver runs. A database error fails the node with `CHANNEL_NODE_FAILED` and the database message.

Scheduled trigger configuration (`trigger.scheduled`):

| Field | Rule |
| --- | --- |
| `cron` | Five-field cron, or `null`. Exactly one of `cron` and `interval_seconds` |
| `interval_seconds` | Integer seconds from 1 to 252460800, or `null` |
| `start_at` | Optional Instant, or `null` |

Variable configuration (`state.variable`):

| Field | Rule |
| --- | --- |
| `scope` | `site`, `channel`, or `run`. Omitted is `site`. `site` is a **Global Variable**, `channel` is a **Channel Variable**, and `run` is a **Run Variable** |
| `operation` | `get`, `set`, `delete`, `set_if_absent`, or `compare_and_set` |
| `name` | A string template. The result matches `^[A-Za-z0-9_.:-]{1,128}$` |
| `value` | A JSON template for `set`, `set_if_absent`, and `compare_and_set` |
| `expected` | A JSON template for `compare_and_set` |
| `ttl_sec` | Optional positive integer seconds on a `site` or `channel` write, or `null`. A non-null value with `scope` `run` is `CHANNEL_NODE_CONFIG_INVALID` |

Manual trigger configuration (`trigger.manual`):

| Field | Rule |
| --- | --- |
| `payload` | A JSON object copied into the node's output. The keys `triggered_by` and `triggered_at` are reserved and rejected. Absent means `{}` |

Set Fields configuration (`transform.set_fields`):

| Field | Rule |
| --- | --- |
| `fields` | Array of `{name, value}`. `name` is 1–128 characters and unique. `value` is a JSON template (`x-refraq-template` any JSON value) |

Output is one object, keys in list order. Ports: input `main`, output `main`.

If configuration (`transform.if`):

| Field | Rule |
| --- | --- |
| `condition` | A boolean template |

Output is `{"value": bool}`. Ports: input `main`, outputs `true` and `false`. The live output is `true` or `false`.

Filter configuration (`transform.filter`):

| Field | Rule |
| --- | --- |
| `items` | A template whose value is a list of objects |
| `combinator` | `all` (default) or `any` |
| `conditions` | Array of `{key, operator, value}`. `operator` is `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `contains`, `starts_with`, `ends_with`, `is_null`, or `is_not_null`. `value` is a JSON template, evaluated once, and is omitted for `is_null` and `is_not_null` |

Output is `{"rows", "count", "dropped"}`. Ports: input `main`, output `main`.

Merge configuration (`transform.merge`):

| Field | Rule |
| --- | --- |
| `mode` | `append`, `by_key`, or `by_position` |
| `inputs` | At least two templates, each a list of objects |
| `key` | A field name, or null. Required, and a non-empty string, when `mode` is `by_key` |
| `join` | `inner` (default), `left`, or `full`. `append` ignores it |

Output is `{"rows", "count"}`. Ports: input `main` (more than one incoming edge is allowed), output `main`.

Deduplicate configuration (`transform.deduplicate`):

| Field | Rule |
| --- | --- |
| `items` | A template whose value is a list of objects |
| `keys` | At least one field name |

Output is `{"rows", "count", "removed"}`. Ports: input `main`, output `main`.

For configuration (`volume.for`):

| Field | Rule |
| --- | --- |
| `items` | A JSON array template. Each element is any JSON value. More than 100000 elements fails the node with `CHANNEL_ITEM_LIMIT_EXCEEDED` and the message `Use Materialize or Dataset Query, then Batch Read.` |

Ports are the input `main` and the outputs `each` and `done`. There is no `loop` port, and `each` is not a loop-back port. During a round the output visible to the body is `{"current", "index", "count"}` for that element. The stored output adds `"iterations"`. `current` is the last element and `index` is its zero-based position; both are null when `items` is empty. `count` is the number of elements, 0 when `items` is empty. `iterations` is an array of one object per element, in order, and is `[]` when `items` is empty. Each object's keys are the `ref` values of direct child nodes that ran on that element, sorted by `ref`. Each value is that node's output. A node that did not run is omitted, not stored as null. A round in which no child ran is `{}`. An If that ran stores that node's output; a branch that did not run adds no key. A nested For stores one key whose value is that For's whole output. The body does not read `iterations` or an earlier element, and may read outputs of nodes upstream of the For. A node reached from `done` reads the stored output, including `iterations`, and does not name a child node. After each element, the UTF-8 byte length of the compact JSON of `iterations` is measured: `,` and `:` with no extra whitespace, and characters outside ASCII are not written as `\u` escapes. Above 16 MiB (16777216 bytes) the node fails with `CHANNEL_ITERATION_VOLUME_EXCEEDED`. `done` runs after the body, including when `items` is empty.

Until configuration (`volume.until`):

| Field | Rule |
| --- | --- |
| `until` | A boolean template, the same declared type as an If `condition`. Required. It may name ancestors of this Until and this Until's direct children. Naming a direct child is the exception to the ancestor-only rule. Text with no `{{ }}` is parsed once as JSON |
| `max_iterations` | Required integer from 1 to 100000. No default. Missing, below 1, or above 100000 fails validation with `CHANNEL_NODE_CONFIG_INVALID` |

Ports are the input `main` and the outputs `each` and `done`. There is no `loop` port, and `each` is not a loop-back port. The node is a container: a direct child sets `parent` to this node's id. A For, a Batch Read, and an Until may nest in any combination. The Until executes once and then runs its direct children once per round. During a round the output visible to the body is `{"previous", "index"}`. `index` starts at 0. `previous` is null on round 0. On a later round it is one object whose keys are the `ref` values of direct child nodes that ran in the previous round, sorted by `ref`, and whose values are those nodes' outputs. A node that did not run is omitted, not stored as null. The stored success output is `{"index", "count", "iterations"}` and has no `previous`. `count` is the number of rounds run, including the round that made `until` true. `index` is that last round's index. `iterations` is an array of one object per round, in order, and uses the same key rules as a For. An empty body is legal, and each empty round still evaluates `until`. A node reached from `done` reads the stored output and does not name a child node. After each round, the UTF-8 byte length of the compact JSON of `iterations` is measured the same way as for a For: `,` and `:` with no extra whitespace, and characters outside ASCII are not written as `\u` escapes. Above 16 MiB (16777216 bytes) the node fails with `CHANNEL_ITERATION_VOLUME_EXCEEDED` and the message `Until iteration output exceeds 16 MiB.` When `max_iterations` rounds have finished and `until` is still false, the node fails with `CHANNEL_UNTIL_MAX_ITERATIONS` and the message `Until reached max_iterations before its condition became true.` The failed execution stores the finished rounds in the same output shape, and `done` does not run. A body `on_error` of `stop` fails the run and does not run `done`. Writes committed by earlier rounds stay committed. Until adds no duration field. The channel run timeout stays the wall-clock limit checked between node executions.

Dataset Query configuration (`volume.dataset_query`):

| Field | Rule |
| --- | --- |
| `source` | Same object as SQL `source` |
| `sql` | A template. The rendered text must be exactly one statement for the source engine. Otherwise the node fails with `CHANNEL_SQL_NOT_ONE_STATEMENT` and the driver is not called |
| `statement_timeout_sec` | Integer seconds from 1 to 3600. Absent means 300. Wall-clock limit of the whole import |

Ports are the input `main` and the outputs `main` and `error`. A successful execution returns `{dataset, count}`. `dataset` is a **Dataset Reference** `{dataset_id, columns, count}` with no `relation`. `columns` is `[{name, type}]` and `type` is a **Normalized Type**. `count` is the number of rows. On the entity database the platform runs the author's query as the body of one statement that creates the dataset table on the owner connection with `search_path` `entity_data`. `_ord` is arrival order. A query that contains `ORDER BY` keeps that order when the database keeps it, and the platform does not guarantee it. On a registered **Source** (PostgreSQL, Oracle, or MSSQL) the platform streams the result into the dataset. Each call to the source uses the remaining wall-clock time as its timeout. PostgreSQL and Oracle run that read in a read-only transaction so the statement cannot write; that transaction is not an extra snapshot promise. MSSQL does not change isolation level, and a long read is not snapshot-consistent. A database error, including snapshot-too-old or a lock wait, fails the node with the database message and is not retried. Between chunks of a streamed Source the run checks the wall-clock deadline, cancel, supersede, and the capacity ceiling. Crossing the ceiling fails the node with `CHANNEL_DATASET_QUOTA_EXCEEDED` and drops that attempt's table. An entity-database create is one statement: it checks the ceiling only before that statement and may exceed it by one dataset. A Dataset Query may be a direct child of a container. One execution creates one dataset row and one table. Inside a container, each round is its own execution and therefore its own dataset. Quota is checked per create. Retention is unchanged.

Materialize configuration (`volume.materialize`):

| Field | Rule |
| --- | --- |
| `items` | A template whose value is a list of objects. More than 100000 objects fails the node with `CHANNEL_ITEM_LIMIT_EXCEEDED` and the message `Use Materialize or Dataset Query, then Batch Read.` |

Ports are the input `main` and the outputs `main` and `error`. A successful execution returns the same `{dataset, count}` as Dataset Query. Column types are inferred from the whole list: boolean, integer, float, and string stay themselves; mixed integer and float is float; an integer that does not fit in a 64-bit integer is decimal; an object, an array, or mixed types is json; an all-null column is string. The physical column follows that **Normalized Type**. The list is copied in chunks, and the capacity ceiling is checked after each chunk. A Materialize may be a direct child of a container. One execution creates one dataset, as for Dataset Query. Quota is checked per create. Retention is unchanged.

Batch Read configuration (`volume.batch_read`):

| Field | Rule |
| --- | --- |
| `dataset` | A template whose value is a **Dataset Reference**. Any other value fails the node |
| `batch_size` | Integer from 1 to 100000. Absent means 1000 |

Ports are the input `main` and the outputs `each` and `done`. There is no `loop` port. The node is a container: a direct child sets `parent` to this node's id, and a For, a Batch Read, and an Until may nest in any combination. During a round the output visible to the body is `{"rows", "index", "count", "total"}`. `index` starts at 0. `rows` is every row whose `_ord` is in `(index × batch_size, (index + 1) × batch_size]`, in `_ord` order, and those objects omit `_ord`. That page is the full round input, not a preview. `count` is the number of batches. `total` is the number of rows. The stored output is `{"count", "total", "batch_size"}` and has no `iterations`. An empty dataset runs no child. `done` still runs. The path is not atomic: each round's write is its own transaction, and a failure leaves batches already committed. `stop` fails the run, does not run `done`, and the error names the failed batch `index`. A dataset the node cannot read fails the node with `CHANNEL_DATASET_UNAVAILABLE`.

Code configuration (`transform.code`):

| Field | Rule |
| --- | --- |
| `code` | Python source, the body of `def main(self)`. 1 byte to 64 KiB. `contentMediaType` is `text/x-python`. Validation compiles it in the parent process and does not execute it. A syntax error is `CHANNEL_CODE_INVALID` with `path` `["code"]` and the author's line number in `detail` |
| `timeout_sec` | Integer seconds from 1 to 300. Absent means 30 |

The returned value is the node output and must be JSON. Ports: input `main`, output `main`. A run failure is `CHANNEL_NODE_FAILED`. `error_detail.reason` is `network` (any socket or network attempt; the audit hook is the guard), `import` (a module outside the allow list), `timeout` (wall-clock over `timeout_sec`; the sandbox is killed, restarted, and replayed), `memory` (MemoryError under the address-space limit; the sandbox restarts afterwards), or `error` (any other exception: `error_detail` also carries `type`, `message`, and `line` in the author's code). One sandbox subprocess is reused for the run. The process CPU limit is a safety net; each call's wall-clock limit governs.

Live Source query configuration (`read.source_query`):

| Field | Rule |
| --- | --- |
| `source_id` | A registered Source id. `x-refraq-ref` is `source`. A value that does not resolve is `CHANNEL_REFERENCE_UNRESOLVED` |
| `sql` | A string template. Each `{{ }}` result is spliced as text. The rendered text is executed through Controlled Query (one read-only statement, `query_timeout_sec`, the row cap, and a `query.run` audit). The actor is the System Identity |
| `row_cap` | Integer of at least 1. Absent means 100. A cap above the platform `query_max_rows` fails the node |

A successful execution returns `{rows, count, truncated}`. `rows` is an array of objects keyed by column name. `count` is the length of `rows`. `truncated` is true when the result was cut at `row_cap`. Ports: input `main`, output `main`. A guard, timeout, or row-limit failure is `CHANNEL_NODE_FAILED` with the Controlled Query message. `error_detail.code` is that Controlled Query code. The node does not require `query:run`.

`config_schema` may carry the custom keyword `x-refraq-ref`. It is ignored by JSON Schema validation and tells the Console which control to render, and tells validation how to resolve the value:

| Value | Meaning |
| --- | --- |
| `entity` | A Business Entity id. The nearest such value in the same configuration is the entity context for attributes nested under it |
| `entity_attribute` | An attribute name on that entity context. A name that is not on the head is `CHANNEL_REFERENCE_UNRESOLVED` |
| `match_key` | A Write Entity match key: `null` or the name of a `unique` head attribute. Failure is `CHANNEL_MATCH_KEY_INVALID`, not an unresolved reference |
| `json` | A JSON object. Used by the Manual trigger payload |
| `sql_source` | The SQL node's `source` object. The Console renders one control listing the entity database and registered Sources |
| `source` | A registered Source id. A value that does not resolve is `CHANNEL_REFERENCE_UNRESOLVED` |

`config_schema` may also carry `x-refraq-template`. It is ignored by JSON Schema validation. Its value is the declared value type as a JSON Schema object, or `{ "from": "entity_attribute" }` when the type is the sibling attribute's **Attribute Type**. The stored value is always the template text. A template that does not parse is `CHANNEL_EXPRESSION_INVALID`. Text with no `{{ }}` that does not match the declared type is `CHANNEL_TEMPLATE_TYPE_MISMATCH`. A `self.<ref>` or `self.nodes["<name>"]` that is missing or not upstream is `CHANNEL_TEMPLATE_REF_INVALID`. A result whose type cannot be known until run time is `CHANNEL_TEMPLATE_TYPE_UNKNOWN` with severity `warning`.

### 3.3 Channel Version

```json
{
  "channel_id": "chn_01HZX",
  "number": 3,
  "graph": { "nodes": [], "edges": [], "settings": { "run_timeout_sec": null, "run_retry_limit": null, "error_channel_id": null } },
  "published_at": "2026-10-08T09:30:00Z",
  "published_by_user_id": "usr_01HZX",
  "published_by_name": "Alice"
}
```

`published_by_name` is presentation only and is `null` when the User no longer resolves. List items omit `graph`.

### 3.4 Problem Entry

Validation reports problems as result documents, not as Problem Details:

```json
{ "code": "CHANNEL_GRAPH_CYCLE", "node_id": "nd_read", "edge_id": "ed_2", "path": [], "detail": "The graph contains a cycle", "severity": "error" }
```

`severity` is `error` or `warning`. Only `error` makes the graph invalid.

`node_id` and `edge_id` are each the offending node or edge, or `null`. `path` is the configuration property segments when the failure names one, and is empty otherwise. A nested segment may be a property name or a list index. `detail` is English occurrence text. Codes are listed in §6.2.

A configuration schema failure uses one entry per failing property:

```json
{ "code": "CHANNEL_NODE_CONFIG_INVALID", "node_id": "nd_read", "edge_id": null, "path": ["statement_timeout_sec"], "detail": "None is not of type 'integer'", "severity": "error" }
```

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
  "target": "published",
  "version": 3,
  "draft_revision": null,
  "trigger_kind": "user",
  "trigger_ref": "usr_01HZX",
  "trigger_node_id": "nd_trigger",
  "trigger_actor_name": "Alice",
  "trigger_schedule_name": null,
  "ignore_checkpoints": false,
  "stop_at_node_id": null,
  "failed_node_id": null,
  "stopped_node_id": null,
  "created_at": "2026-10-09T08:00:00Z",
  "started_at": "2026-10-09T08:00:01Z",
  "finished_at": "2026-10-09T08:00:41Z",
  "error_code": null,
  "error_message": null
}
```

- `status` is the Job status (`queued`, `running`, `succeeded`, `failed`, `cancelled`).
- `outcome` is `completed` or `skipped` when `status` is `succeeded`, otherwise `null`.
- `target` is `draft` or `published` for an on-demand run, and `published` for every unattended run.
- `version` is the Channel Version a `published` run resolved at start, or `null` before it starts, when it ended before resolving one, or when `target` is `draft`.
- `draft_revision` is the frozen draft revision when `target` is `draft`, otherwise `null`.
- `failed_node_id` names the node whose `on_error` `stop` failed the run, or `null`. A `continue` or `error_output` execution does not set it.
- `stop_at_node_id` is the optional on-demand stop node, or `null` when the run executes every node reachable from the trigger.
- `stopped_node_id` names the node that was next when a timeout or a newer version stopped the run between nodes, or the node a user cancel interrupted, or `null` when cancel killed the process before that node was recorded.
- `trigger_kind` is `user` for an on-demand run or a rerun, `schedule` for a Scheduled node, `retry` for a Job minted by `run_retry_limit`, `error` for an error workflow, and `system` for platform-event and change-arrival triggers. `trigger_ref` is the acting User for `user`, the source Job id for `error`, and otherwise follows the Job contract. `trigger_actor_name` and `trigger_schedule_name` follow the Job contract.
- Duration is derived by clients from `started_at` and `finished_at`.

### 3.7 Node Type

```json
{
  "type": "write.entity",
  "family": "write",
  "label": "Write Entity",
  "summary": "Creates, updates, upserts, or deletes rows of a Business Entity.",
  "description": "Writes mapped attributes into the current head of one Business Entity. The match key is the head's Business Key unless the node names a unique attribute. When the published head no longer matches, the node fails the item or skips it.",
  "trigger": false,
  "inputs": [
    {
      "port": "main",
      "description": "Primary input port. It orders execution. The node reads an upstream output by name.",
      "coarse_type": "object"
    }
  ],
  "outputs": [
    {
      "port": "main",
      "description": "Primary output port of a successful execution. A downstream node reads that output by name.",
      "coarse_type": "object"
    },
    {
      "port": "error",
      "description": "Items that failed this node when on_error is error_output.",
      "coarse_type": "unknown"
    }
  ],
  "config_schema": { "type": "object" },
  "permission": null,
  "type_version": 1,
  "output_view": {
    "kind": "counts",
    "metrics": ["inserted", "updated", "unchanged", "deleted", "unmatched"]
  }
}
```

- `family` is `trigger`, `read`, `transform`, `volume`, `state`, `write`, or `action`.
- `output_view` is the type's **Output View** (`docs/business-data-channel.md` §4.2). `kind` is `record`, `rows`, `dataset`, `counts`, `container`, or `value`. `rows` is present when `kind` is `rows` and names the list key. `dataset` is present when `kind` is `dataset` and names the **Dataset Reference** key. `item` is present when `kind` is `container` and names the round-step key that holds the round's data: `current` for `volume.for`, `index` for `volume.until`, `rows` for `volume.batch_read`; it is a property of the type's `each` output schema. `metrics` is the display order of top-level measure keys, and is `[]` when the output has none. Every catalog type declares an `output_view`. When the type's `main` output schema is known, every key in `rows`, `dataset`, and `metrics` is a property of that schema. A type with no `main` output still declares `output_view`; the same key rule applies to the stored success output in `docs/business-data-channel.md` §4.3. The `error` port is not part of the view.
- `label`, `summary`, and `description` are English. `summary` is one sentence. `description` states the type's function and its place in a workflow.
- `trigger` is `true` for trigger types; they declare no inputs.
- Each port is `{ "port", "description", "coarse_type", "loop_back" }`. `port` is lower snake case. `coarse_type` is `object`, `items`, or `unknown`. `loop_back` is false on every port. `main` is the primary input or output port. It orders execution. An expression reads an upstream output by name; the port does not deliver items or a dataset reference from the previous node. `error` is an output that carries items the node failed when `on_error` is `error_output`.
- `type_version` is the current version of the node type. A node instance's `type_version` must match it.
- `config_schema` is a JSON Schema object that the Console renders as the configuration panel and the server enforces at validate and publish. Every property, including properties nested under array items, has `title` and `description`.
- `permission` names the extra Permission needed to add or edit a node of this type (`channel:code_write` for `transform.code`, `channel:source_query` for `read.source_query`), or `null`.
- The Console prefers locale keys `channelNodeTypes.<type>.label` and `channelNodeTypes.<type>.summary`, and falls back to the served English `label` and `summary`.

## 4. Job Kind `channel_run`

### 4.1 Lifecycle

A `channel_run` Job follows the platform Job lifecycle (`docs/business-jobs.md`). It takes no execution lock and never ends with `JOB_ALREADY_ACTIVE`. Cancel uses `POST /jobs/{id}/cancel`.

### 4.2 Input

```json
{
  "channel_id": "chn_01HZX",
  "target": "published",
  "ignore_checkpoints": false,
  "stop_at_node_id": null,
  "pin_version": false,
  "version": null,
  "retry_of_job_id": null,
  "error_source": null
}
```

`pin_version` defaults to false. When it is true, `version` is the published version number the runner must execute, and a newer version neither replaces it nor cancels the run. A `published` run with `pin_version` false resolves the current published version at start. A `draft` run executes the snapshot stored on the run record and ignores `pin_version`. `stop_at_node_id` is optional. When set, the run enters the graph's only trigger and executes that node's ancestor closure, including the node. `retry_of_job_id` is the previous Job in a `run_retry_limit` chain, or null. `error_source` is null except on an error workflow, where it is `{ "channel_id", "channel_name", "job_id", "version", "attempt", "error": { "code", "message", "node_id" } }`. Unattended schedule runs set `target` to `published`, omit `stop_at_node_id`, and omit a user-chosen trigger when the schedule names the node.

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
| `PUT` | `/channels/{id}/tags` | `channel:write` | Replace the channel's Tags |
| `POST` | `/channels/tags/add` | `channel:write` | Add Tags to the named channels |
| `POST` | `/channels/tags/remove` | `channel:write` | Remove Tags from the named channels |
| `DELETE` | `/channels/{id}` | `channel:write` | Delete the channel |
| `GET` | `/channels/{id}/variables` | `channel:read` | List the channel's **Channel Variable**s (**Offset Page**) |
| `DELETE` | `/channels/{id}/variables/{name}` | `channel:write` | Delete one live **Channel Variable** |
| `GET` | `/channels/{id}/draft` | `channel:read` | Read the draft graph |
| `PUT` | `/channels/{id}/draft` | `channel:write` | Replace the draft graph |
| `POST` | `/channels/{id}/draft/validate` | `channel:write` | Validate a graph without writing it |
| `POST` | `/channels/{id}/publish/preview` | `channel:write` | Compute the confirmation list |
| `POST` | `/channels/{id}/publish` | `channel:write` | Publish the draft as a new version |
| `GET` | `/channels/{id}/versions` | `channel:read` | List versions (**Offset Page**) |
| `GET` | `/channels/{id}/versions/{number}` | `channel:read` | Read one version with its graph |
| `POST` | `/channels/{id}/activate` | `channel:write` | Turn the activation switch on |
| `POST` | `/channels/{id}/deactivate` | `channel:write` | Turn the activation switch off |
| `POST` | `/channels/{id}/runs` | `channel:write` | Start an on-demand run |
| `POST` | `/channels/{id}/runs/{job_id}/rerun` | `channel:write` | Rerun a failed published run on its version |
| `GET` | `/channels/{id}/runs` | `channel:read` | List this channel's runs (**Offset Page**) |
| `GET` | `/channels/{id}/runs/{job_id}` | `channel:read` | Read one run with its graph and node summaries |
| `GET` | `/channels/{id}/runs/{job_id}/executions` | `channel:read` | List node executions (**Offset Page**) |
| `GET` | `/channels/{id}/runs/{job_id}/executions/{seq}/output` | `channel:read` | Page one node execution's stored output |
| `GET` | `/channels/{id}/runs/{job_id}/executions/{seq}/rounds` | `channel:read` | List container rounds of one execution (**Offset Page**) |
| `GET` | `/channels/{id}/runs/{job_id}/datasets/{dataset_id}/rows` | `channel:read` | Page dataset rows by `_ord` |
| `POST` | `/channels/{id}/runs/{job_id}/template-preview` | `channel:write` | Evaluate one template field against a run record |
| `POST` | `/channels/{id}/runs/{job_id}/node-sample` | `channel:write` | Read one node's sample against a run record |

### 5.1 `GET /channel-node-types`

`200` `{ "items": [ … ] }` with every node type (§3.7). The catalog is a whole-set read, ordered by `family` then `type`.

### 5.2 `POST /channels`

```json
{ "name": "Material master", "description": null, "tags": { "tag_ids": [], "names": [] } }
```

`name` is required. `description` is optional. `tags` is optional. `tag_ids` and `names` both default to empty. Any other field is `422 REQUEST_INVALID`.

An omitted `tags`, or both arrays empty, leaves the new channel with no Tags and `tag_revision` 1. `tag_ids` names existing Tags. `names` creates Tags in the same request. A rejected name or a set of more than ten leaves neither the channel nor a new Tag. A name that folds onto an existing Tag attaches it and does not return `TAG_NAME_CONFLICT`.

`201` `{ "channel": { … } }`. The draft starts as `{ "nodes": [], "edges": [], "settings": { "run_timeout_sec": null, "run_retry_limit": null, "error_channel_id": null } }` with `draft_revision` 1. `active` is `false`.

### 5.3 `GET /channels`

Query: `q` (optional case-insensitive substring of `name`; a blank or whitespace-only value is the same as omitting it; `%` and `_` match themselves), `active` (`true` | `false` | omitted), `tag_id` (repeatable), `limit` (default 50, max 200), `offset` (default 0). Ordered by `created_at DESC`, `id DESC`. `total` counts the filtered set.

Repeat `tag_id` to keep channels that carry any listed Tag. The condition combines with `q` and `active`: a channel must match every condition that is present. Omit `tag_id` to apply no Tag predicate. An id that is not a live Tag matches no channel and does not fail the list; other ids in the same query still match. The predicate is applied with `q` and `active` before paging. `total` counts that filtered set. Omitted `active` does not hide inactive channels.

The Console list omits `active` until the operator chooses active only or inactive only, and omits `tag_id` until a Tag is selected. Clearing the activation choice omits `active` again.

`GET /channels/{id}` returns `200` `{ "channel": { … } }`.

### 5.4 `PATCH /channels/{id}`

Any subset of `name` and `description`. Present `description` `null` clears it. `200` `{ "channel": { … } }`. Does not touch the draft or versions. A changed channel name rewrites the name of the synced schedule row without another publish. A description-only change leaves that schedule name as stored. A `tags` field is `422 REQUEST_INVALID` and leaves the Tag set and `tag_revision` unchanged.

### 5.4a `PUT /channels/{id}/tags`

Purpose: replace the channel's Tags. This is not a draft save and does not take the draft-run lock.

- Permission: `channel:write`. A caller without it receives `403 AUTH_FORBIDDEN` before the id is resolved, including when the body is invalid. `tag:write` is not required, including when `names` creates a Tag.

```json
{ "base_revision": 1, "tag_ids": [], "names": [] }
```

`tag_ids` and `names` are required arrays. Both empty clears the set. The cap counts the resulting set: an id already held, or a repeated id, counts once. More than ten is `422 TAG_LIMIT_EXCEEDED` and writes nothing of that request. The extension `subjects` is `[{ "kind": "channel", "id": "<channel id>" }]`.

`base_revision` must equal the stored revision. A stale revision is `409 TAG_ASSIGNMENT_CONFLICT` and leaves the newer set. The same set at the current revision is `200` and does not increment the revision.

Success `200`: `{ "tags": [{ "id", "name" }], "tag_revision": N }`. Tags are ordered by comparison form, then id.

Error order: unknown channel `404 CHANNEL_NOT_FOUND`; stale revision `409 TAG_ASSIGNMENT_CONFLICT`; an unknown `tag_ids` entry `404 TAG_NOT_FOUND`; an invalid name `422 TAG_NAME_INVALID`; more than ten `422 TAG_LIMIT_EXCEEDED`. A folded name attaches the existing Tag and does not change its stored display name.

The call is allowed while a draft run is queued or running, and while the channel is active or inactive. It does not change `draft_revision`, `draft_updated_at`, or the channel `updated_at`. A committed set change writes one audit event, resource type `channel`, action `tags.replace`, detail `{ "tag_ids": [ ... ] }` in response order. Each inline create also writes a Tag create event. An unchanged set writes neither.

### 5.4b `POST /channels/tags/add` and `POST /channels/tags/remove`

Purpose: add Tags to many channels, or remove Tags from them. Add only inserts. Remove only deletes. Neither replaces the set, takes `base_revision`, nor creates a Tag.

- Permission: `channel:write`. A caller without it receives `403 AUTH_FORBIDDEN` before any id is resolved. `tag:write` is not required.

```json
{ "channel_ids": ["chn_01HZX"], "tag_ids": ["tag_01HZX"] }
```

`channel_ids` and `tag_ids` are required arrays. Duplicates collapse, keeping the first occurrence. After that collapse, zero ids, more than 200 subject ids, zero Tag ids, or more than 10 Tag ids is `422 REQUEST_INVALID` and writes nothing. Any other field is `422 REQUEST_INVALID`.

The request is one transaction. Each subject's assignment is locked, and the add or remove applies to the set found under that lock.

Error order after the shape check: any unknown channel is `404 CHANNEL_NOT_FOUND` and `subjects` is `[{ "kind": "channel", "id" }]` for each such id, in request order after collapse; else, on add, an unknown Tag id is `404 TAG_NOT_FOUND`; else `422 TAG_LIMIT_EXCEEDED` and `subjects` lists every channel whose resulting set would exceed ten. One response, one code. A failure writes nothing of that request and writes no audit event. A Tag the subject already holds counts once toward the cap.

Remove ignores a Tag id the channel does not carry, including an id that is not a live Tag.

Success `200`:

```json
{ "subjects": [ { "id": "chn_01HZX", "tags": [{ "id": "tag_01HZX", "name": "Ledger" }], "tag_revision": 2 } ] }
```

Every requested channel is present once, in request order after collapse, including a channel whose set did not change. Tags are ordered by comparison form, then id. `tag_revision` increases by 1 only when that channel's set changes.

The call is allowed while a draft run is queued or running, and while the channel is active or inactive. It does not change `draft_revision`, `draft_updated_at`, or the channel `updated_at`. A subject whose set changed writes one audit event, resource type `channel`, action `tags.add` or `tags.remove`, detail `{ "tag_ids": [ ... ] }` in response order. A subject whose set did not change writes no event.

### 5.5 `DELETE /channels/{id}`

`204`. Withdraws schedule rows whose `owner_ref` is `channel:{id}`, requests cancel of the channel's other unfinished runs, and removes the channel, its draft, its versions, its checkpoints, its run records, its **Channel Variable**s, and its Tag assignments. A refused delete leaves the assignments. Historical Jobs remain. Rows already written to Entity Tables stay. **Global Variable**s stay.

### 5.6 `GET` and `PUT /channels/{id}/draft`

`GET` returns `{ "draft_revision", "draft_updated_at", "graph" }`. The graph is the stored document. A node that lacks `ref`, names an unknown type, or otherwise fails §3.2 is still returned. This read does not report those failures. Publish validates the stored draft and refuses it when that validation has an error. The validate endpoint accepts only a graph of the save shape; a document that fails that shape is `422`.

`PUT` body:

```json
{ "base_revision": 12, "graph": { "nodes": [], "edges": [], "settings": { "run_timeout_sec": null, "run_retry_limit": null, "error_channel_id": null } } }
```

- `base_revision` must equal the stored `draft_revision`; otherwise `409 CHANNEL_DRAFT_CONFLICT`.
- Save checks shape only: identifier rules, unique node, edge, and note ids, field types and ranges in §3.2. It does not check node configuration against the catalog, references, or graph rules; a draft may be incomplete. A change that only adds, edits, or removes notes does not require a node-type Permission.
- Compared with the stored draft, a node whose type declares a `permission` requires that Permission when the node is added (its id is absent, or the stored node with that id had another type) or when its `type`, `type_version`, or `config` changes. An unchanged guarded node does not. Deleting a guarded node does not. Missing the Permission is `403 AUTH_FORBIDDEN`; `detail` names the node.
- `200` `{ "draft_revision", "draft_updated_at", "graph" }` with `draft_revision` incremented by one. Save never changes a version or a schedule row.

### 5.7 `POST /channels/{id}/draft/validate`

```json
{ "graph": { "nodes": [], "edges": [], "settings": { "run_timeout_sec": null, "run_retry_limit": null, "error_channel_id": null } } }
```

`graph` is the same shape as a draft save (§3.2). The body is required. Validate checks that graph and does not read or write the stored draft. It does not record an audit event. A graph that fails the save shape is `422`. The channel must exist (`404` otherwise). `200`:

```json
{
  "valid": false,
  "problems": [
    { "code": "CHANNEL_GRAPH_NO_TRIGGER", "node_id": null, "edge_id": null, "path": [], "detail": "Graph has no trigger node", "severity": "error" }
  ],
  "ports": [
    { "node_id": "nd_read", "port": "main", "direction": "output", "coarse_type": "object", "schema": { "type": "object" } }
  ],
  "context": {
    "channel": { "type": "object" },
    "run": { "type": "object" },
    "platform": { "type": "object" }
  }
}
```

The response describes the submitted graph. `valid` is false when any problem has severity `error`. `ports` lists every declared port of that graph. `schema` is the refined JSON Schema, or `null` when it is not known. An invalid graph is a `200` result, not a Problem Details failure.

`context` is the JSON Schema of `self.channel`, `self.run`, and `self.platform`. It does not depend on the submitted graph. `channel` has `id`, `name`, `description`, `active`, and `settings` (`run_timeout_sec`, `run_retry_limit`, `error_channel_id`). `run` has `id`, `target`, `version`, `draft_revision`, `trigger_kind`, `started_at`, and `triggered_by` (`id`, `name`). `platform` has `site_name`, `schedule_timezone`, `now`, and `parameters`. `parameters` lists every registered System Parameter: an integer constraint is `integer`, and every other constraint is `string`.

### 5.8 `POST /channels/{id}/publish/preview` and `POST /channels/{id}/publish`

Preview takes an empty body and returns `200` with the confirmation list (§3.5) for the stored draft. It writes nothing. It does not require the draft to be valid.

Publish body:

```json
{ "draft_revision": 12 }
```

- `draft_revision` must equal the stored revision, so the published graph is the previewed graph; otherwise `409 CHANNEL_DRAFT_CONFLICT`.
- An invalid draft is refused with `422 CHANNEL_GRAPH_INVALID`; `detail` names the first error. The body carries `problems`, the errors that blocked the request, each shaped as in §5.7. The full list, including warnings, comes from validate.
- The caller must hold every Permission declared by node types present in the draft, including nodes that did not change. Missing one is `403 AUTH_FORBIDDEN`; `detail` names the node.
- `201` `{ "version": { … }, "confirmation": { … } }`, where `confirmation` lists the running published runs the new version will stop between nodes. Publish stores the version and reconciles the schedule row. It does not change `active` and it does not cancel Jobs itself.

### 5.9 `GET /channels/{id}/versions` and `GET /channels/{id}/versions/{number}`

List query: `limit` (default 50, max 200), `offset` (default 0). Ordered by `number DESC`. Items omit `graph`. Get returns `{ "version": { … } }` with the stored `graph`. A stored graph that does not meet §3.2 is still returned. Unknown number is `404 CHANNEL_VERSION_NOT_FOUND`.

### 5.10 `POST /channels/{id}/activate` and `POST /channels/{id}/deactivate`

Empty body. `200` `{ "channel": { … } }`. Idempotent: activating an active channel, or deactivating an inactive one, succeeds without change. Activate sets every synced schedule row `enabled`; deactivate disables them and does not cancel queued or running Jobs. Activating a channel with no published version is allowed and has no schedule rows to enable. Requires `channel:write`. Activation and deactivation do not change Tags or `tag_revision`.

### 5.11 `POST /channels/{id}/runs`

```json
{
  "target": "draft",
  "ignore_checkpoints": false,
  "stop_at_node_id": "nd_write"
}
```

- `target` is `draft` or `published`. `draft` freezes the current draft, which must validate; `published` requires a published version.
- `stop_at_node_id` is optional. Omit it, or send `null`, to execute every node reachable from the trigger. When set, the selected draft snapshot or published graph must be valid for that node's ancestor closure, including the node. Errors on nodes outside the closure do not refuse the start. A refusal carries `problems` as in the publish rule of §5.8, limited to errors inside the closure and errors that belong to no node; `detail` is the first of them. A missing stop node refuses with an empty `problems`. A stop node that is missing or not reachable from the trigger is `422 CHANNEL_GRAPH_INVALID`.
- A body that contains `pinned` is `422 REQUEST_INVALID`.
- The run enters the graph's only trigger node.
- `ignore_checkpoints` defaults to `false`. Checkpoint-aware node types define how this override affects their configured read and advance policy.
- The framework does not provide a dry-run mode or an execution row limit. Every node the run reaches performs its normal effects.
- Allowed while the channel is inactive.
- `202` `{ "run": { … } }` (§3.6). `trigger_kind` is `user` and `trigger_ref` is the acting User. The body is the Channel Run as stored when the handler returns, the same read as a following GET. `status` is `queued` and `outcome` is null when the worker has not finished. When the worker has already finished inside the request, `status`, `outcome`, and `failed_node_id` match that GET and §3.6.
- Target `published` with no published version is `409 CHANNEL_NOT_PUBLISHED`. A graph that does not have exactly one trigger is `422 CHANNEL_TRIGGER_INVALID`. An invalid draft is `422 CHANNEL_GRAPH_INVALID`.

### 5.12 `GET /channels/{id}/runs`

Query: `status` (optional Job status), `target` (`draft` | `published` | omitted), `limit` (default 50, max 200), `offset` (default 0). Ordered by `created_at DESC`, `job_id DESC`. Items are Channel Runs (§3.6) of every trigger kind for this channel.

### 5.13 `GET /channels/{id}/runs/{job_id}`

`200`:

```json
{
  "run": { },
  "graph": { "nodes": [], "edges": [], "settings": { "run_timeout_sec": null, "run_retry_limit": null, "error_channel_id": null } },
  "node_summaries": [
    {
      "node_id": "nd_read",
      "execution_count": 1,
      "status_counts": { "succeeded": 1 }
    }
  ]
}
```

`graph` is the snapshot the run executes, or `null` before a `published` run has resolved a version. `node_summaries` has one object per node that has at least one execution, ordered by that node's smallest `seq`. `execution_count` is the number of executions. `status_counts` maps each status that occurred (`running`, `succeeded`, `failed`, `skipped`) to its count. The response does not include `node_executions`. Executions are §5.17. Unknown `job_id` for this channel is `404 CHANNEL_RUN_NOT_FOUND`. Requires `channel:read`.

### 5.14 `GET /channels/{id}/runs/{job_id}/executions/{seq}/output`

Query: `path` (optional dot path into the output, such as `rows`), `limit` (default 50, max 200), `offset` (default 0).

When the value at `path` is a list, `200` is an **Offset Page** of its elements. Otherwise `200` is `{ "value": … }` and `limit` / `offset` are ignored. The value is the stored output, and the read pages that stored value. A successful execution stores its full output, including when a Batch Read is among its container ancestors, and is not preview-only. A stored output that carries the preview envelope reads as preview-only, pages that stored preview, and `preview_totals` holds the lengths recorded in the envelope (§5.17). An unknown `seq` is `404 CHANNEL_RUN_NOT_FOUND`. Requires `channel:read`.

### 5.15 `POST /channels/{id}/runs/{job_id}/template-preview`

```json
{
  "graph": { "nodes": [], "edges": [], "settings": { "run_timeout_sec": null, "run_retry_limit": null, "error_channel_id": null } },
  "node_id": "nd_write",
  "path": ["source"],
  "scope": [{ "container_node_id": "nd_for", "round": 0 }]
}
```

Evaluates the **Template Field** at `path` in node `node_id` of `graph` against run `job_id` of this channel (**Template Preview**, `docs/business-data-channel.md` §4.1). `graph` is the same shape as a draft save (§3.2), usually the graph on screen; the run may have executed an earlier graph. `path` is the configuration path, as in a problem entry (§3.4). `scope` is optional and has the same shape as a **Node Sample** scope (§5.19). Omit it to use that sample's default scope. The request executes no node and writes nothing. It does not record an audit event.

- Template validation (§5.7) applies to that field of `graph`. A field with a validation error is `failed` with that problem's `code`, and its `detail` as `message`.
- Upstream values are the Node Sample binding for `graph`, `node_id`, and `scope` (§5.19). The binding supplies the stored output. A preview-only record supplies the stored preview (§5.17). `self.channel`, `self.run`, and `self.platform` are the values the run recorded at start.
- Evaluation uses the run sandbox and the run's conversion to the declared value type. An expression failure is `failed` with `CHANNEL_NODE_FAILED`. A result that does not match the declared value type is `failed` with `CHANNEL_VALUE_TYPE_MISMATCH`. A sandbox that cannot start is `failed` with `CHANNEL_SANDBOX_FAILED`. `message` is the error the node would record.

`200` is one of:

```json
{
  "state": "ok",
  "value": [{ "code": "S-01" }],
  "truncated": false,
  "scope": [
    { "container_node_id": "nd_for", "container_seq": 2, "round": 0, "rounds_total": 3 }
  ],
  "bindings": [{ "node_id": "nd_read", "seq": 4, "source": "execution" }]
}
```

```json
{
  "state": "failed",
  "code": "CHANNEL_VALUE_TYPE_MISMATCH",
  "message": "Value does not match the declared type",
  "scope": [],
  "bindings": []
}
```

```json
{
  "state": "missing",
  "node_ids": ["nd_read"],
  "context": false,
  "scope": [],
  "bindings": [{ "node_id": "nd_read", "source": "execution" }]
}
```

- `value` is the result with each list cut to its first 100 elements. `truncated` is true when a list was cut (§5.17).
- `scope` is the scope the binding used, including a default filled in by the server, in the Node Sample shape (§5.19).
- `bindings` lists each upstream value the binding selected, in the same order as a Node Sample `upstream` array. `source` is `execution` or `round_step`. `seq` is present when `source` is `execution` and an execution was selected, and omitted otherwise.
- `node_ids` lists, in graph order, the named upstream nodes for which the binding has no value. `context` is true when the template reads `self.channel`, `self.run`, or `self.platform` and the run has no recorded context, such as a run that has not started.
- `failed` and `missing` are `200` result documents, not Problem Details failures. Every `200` includes `scope` and `bindings`.
- `node_id` and `path` that do not name a template field of `graph` are `422 REQUEST_INVALID`. A `scope` the Node Sample endpoint would reject is `422 REQUEST_INVALID`. A `graph` that fails the save shape is `422`. Unknown `job_id` for this channel is `404 CHANNEL_RUN_NOT_FOUND`.

### 5.16 `POST /channels/{id}/runs/{job_id}/rerun`

Empty body. Requires `channel:write`. The source run must be `failed` and `target` `published`, and it must have a version number. `202` `{ "run": { … } }` for a new Job pinned to that version (`pin_version` true, `trigger_kind` `user`). The new run does not set `retry_of_job_id`. `422` `CHANNEL_RUN_NOT_RERUNNABLE` otherwise. `404` `CHANNEL_RUN_NOT_FOUND` when the Job is not a run of this channel.

### 5.17 `GET /channels/{id}/runs/{job_id}/executions`

Query: `node_id` (optional), `container_seq` (optional integer), `round` (optional integer), `status` (optional: `running`, `succeeded`, `failed`, or `skipped`), `limit` (default 50, max 200), `offset` (default 0). `200` is an **Offset Page** ordered by `seq` ascending. Requires `channel:read`. Unknown `job_id` for this channel is `404 CHANNEL_RUN_NOT_FOUND`.

```json
{
  "seq": 4,
  "node_id": "nd_write",
  "container_seq": 2,
  "round": 0,
  "status": "succeeded",
  "started_at": "2026-10-09T08:00:03Z",
  "finished_at": "2026-10-09T08:00:04Z",
  "output_bytes": 4096,
  "output_preview": { "rows": [], "count": 100 },
  "output_truncated": false,
  "preview_only": false,
  "preview_totals": {},
  "input_preview": {
    "source": { "value": [{ "code": "S-01" }] }
  },
  "input_truncated": false,
  "input_totals": { "source": 1 },
  "error_code": null,
  "error_message": null,
  "error_detail": null
}
```

- `container_seq` and `round` are null when the execution is not inside a **For**, a Batch Read, or an Until. Otherwise `container_seq` is the `seq` of the direct container's execution, and `round` is the zero-based round index.
- `output_preview` is the stored output with each list cut to its first 100 elements. `output_truncated` is true when this response cut a list.
- `preview_only` is false and `preview_totals` is `{}`. A successful execution stores its full output, including when a Batch Read is among its container ancestors. A failed execution stores its full output. A stored output that carries the preview envelope reports `preview_only` true, and `preview_totals` maps each list's dot path to the length recorded in the envelope.
- `input_preview` is the execution's **Execution Input** (`docs/business-data-channel.md` §6.9) with each list cut to its first 100 elements. Each entry is `{ "value": … }` or `{ "error": { "code", "message" } }`, keyed by configuration path. `input_truncated` and `input_totals` follow the list rule below. When the execution recorded no input, `input_preview` and `input_totals` are `null` and `input_truncated` is false.
- A **Template Preview** reads this stored output. A preview-only record supplies the stored preview.

A list shown by `output_preview`, `input_preview`, a Template Preview `value`, a **Node Sample**, or a container-round `step_preview` keeps at most the first 100 elements of every list. On a Node Sample, on `input_truncated` / `input_totals`, and on `step_truncated` / `step_totals`, `truncated` is true when any list in that value is shorter than its original length, whether the record stored the short list or this response shortened it. `input_totals` and `step_totals` map every list's dot path to that original length, including a list that was not shortened. A dot path uses numeric segments for indexes. `output_truncated` on this list stays the cut this response applied. `preview_totals` stays `{}` unless the stored output carries the preview envelope, in which case it is the length map in that envelope. A Node Sample that returns an execution output folds those two sources into its own `truncated` and `totals`.

### 5.18 `GET /channels/{id}/runs/{job_id}/datasets/{dataset_id}/rows`

Query: `after_ord` (optional integer, default 0), `limit` (default 50, max 200). Requires `channel:read`. Paging these rows is part of reading the run record.

`200`:

```json
{
  "items": [
    { "_ord": 1, "code": "S-01" }
  ],
  "limit": 50,
  "next_after_ord": 50
}
```

Items are the rows with `_ord` greater than `after_ord`, ordered by `_ord` ascending. Each item includes `_ord` and the dataset columns. `next_after_ord` is the last `_ord` in `items`, or `null` when the page is empty or is the last page. This is not an **Offset Page**: the response has no `total` and no `offset`.

The registry row must belong to `job_id` and be readable. Otherwise `404` `CHANNEL_DATASET_UNAVAILABLE`. The problem carries `reason`: `not_found`, `expired`, `lost`, or `foreign_run`. `lost` means the registry row count is greater than 0 and the table has no row; the check does not count the table. `foreign_run` means the dataset is registered to a different Job than the path. Unknown `job_id` for this channel is `404 CHANNEL_RUN_NOT_FOUND`. `detail` stays English occurrence text. Reading rows does not consult the capacity ceiling.

### 5.19 `POST /channels/{id}/runs/{job_id}/node-sample`

```json
{
  "graph": { "nodes": [], "edges": [], "settings": { "run_timeout_sec": null, "run_retry_limit": null, "error_channel_id": null } },
  "node_id": "nd_write",
  "scope": [{ "container_node_id": "nd_for", "round": 0 }]
}
```

Reads a **Node Sample** of node `node_id` in `graph` against run `job_id` of this channel (`docs/business-data-channel.md` §4.1). `graph` is the same shape as a draft save (§3.2). `scope` is optional. Each entry is `{ "container_node_id", "round" }`, from the outermost frame inward, and `round` counts from 0. `container_round` is optional, an integer greater than or equal to 0. When `node_id` is an Until, it names that Until execution's own round. The sample's `node.input` then includes that round's `until` entry when the round has one, and the execution's stored input is not written. For any other node type, `container_round` is ignored. The request is read-only: it executes no node, reads no Source, and writes nothing. It does not record an audit event. Requires `channel:write`.

Binding, evaluated on the server for this endpoint and for Template Preview (§5.15):

1. Ancestors are the ancestor walk of `graph` (`docs/business-data-channel.md` §4.1). Executions match by node id.
2. An omitted `scope` is resolved. When the node has an execution, the scope is the round chain of its latest execution. Otherwise each For, Batch Read, or Until that contains the node uses that container's last recorded round. The response returns the resolved scope. Each level adds `container_seq` (the container execution's `seq`, or `null` when that frame has no recorded round) and `rounds_total` (how many rounds that container execution recorded, or 0).
3. An ancestor that is a container in the scope contributes that round's **Container Round** (`source` `round_step`): `{current, index, count}` for a For, `{rows, index, count, total}` for a Batch Read, and `{index}` plus `until` when that round has evaluated its condition for an Until. `until` is `{value}` or `{error: {code, message}}`. It does not contribute the container's stored output. An Until body reads `{previous, index}` at run time; `previous` is not on the round record. An ancestor whose parent is a container in the scope contributes its latest `succeeded` or `skipped` execution with that `container_seq` and `round` (`source` `execution`). Any other ancestor contributes its latest `succeeded` or `skipped` execution in the run (`source` `execution`).
4. The node itself contributes its latest execution inside the scope, of any status.

A selected `succeeded` execution has `state` `ok`. A selected `skipped` execution has `state` `ok`, `value` set to the stored output, and `error` set when that execution recorded an error. When the slot has no `succeeded` or `skipped` execution and has a `failed` execution, `state` is `failed`, `value` is the stored output when there is one, and `error` is that execution's error. When the slot has no execution, `state` is `not_recorded`. A round step that was recorded has `state` `ok`. A round that was not recorded has `state` `not_recorded` and `source` `round_step`. Ancestors that the node's templates name statically (`self.<ref>` or `self.nodes["<name>"]`) come first. The rest follow the graph's topological order.

`200`:

```json
{
  "scope": [
    { "container_node_id": "nd_for", "container_seq": 2, "round": 0, "rounds_total": 3 }
  ],
  "config_changed": false,
  "upstream": [
    {
      "node_id": "nd_read",
      "ref": "read_suppliers",
      "name": "Read suppliers",
      "type_id": "read.sql",
      "referenced": true,
      "state": "ok",
      "source": "execution",
      "seq": 4,
      "value": { "rows": [], "count": 1, "rowcount": 1 },
      "truncated": false,
      "totals": {},
      "preview_only": false,
      "error": null
    }
  ],
  "node": {
    "state": "ok",
    "seq": 5,
    "status": "succeeded",
    "output": { "inserted": 1, "updated": 0, "unchanged": 0, "deleted": 0, "unmatched": 0 },
    "output_truncated": false,
    "totals": {},
    "preview_only": false,
    "input": { "source": { "value": [{ "code": "S-01" }] } },
    "input_totals": { "source": 1 },
    "error": null
  }
}
```

- `config_changed` is true when the submitted node's `config` differs from that node in the graph the run executed, or when the snapshot has no node with that id.
- `referenced` is true when the node's templates statically name that ancestor.
- Upstream `state` is `ok`, `not_recorded`, or `failed`. `source` is `execution` or `round_step`. `seq` is null when no execution was selected. `value` is null when `state` is `not_recorded`. `truncated` and `totals` follow §5.17. `error` is null when the selected record has no error.
- Node `state` is `ok` for a `succeeded` execution, `running`, `failed`, or `skipped` for those statuses, and `not_recorded` when the scope contains no execution of the node. `status` is the execution status, or null. `output` is the stored output, or null. A `failed` or `skipped` execution keeps that stored output and sets `error` to `{ "code", "message" }` when the execution recorded an error. `input` is the Execution Input object, or null when none was recorded. `input_totals` is the input length map, or null when no input was recorded.
- List values follow §5.17. An execution stored in full supplies that output. `preview_only` is true only when the stored output carries the preview envelope, and then the sample supplies the stored preview. A round step, and a slot with no execution, are false. The settings panel does not page a rows view when `preview_only` is true.
- Unknown `job_id` for this channel is `404 CHANNEL_RUN_NOT_FOUND`. `node_id` that is not a node of `graph` is `422 REQUEST_INVALID`. A present `scope` that is not the outer-to-inner list of For, Batch Read, and Until frames containing the node, or a `round` that is not an integer greater than or equal to 0, is `422 REQUEST_INVALID`. A round with no recorded step is not that error: the sample returns `not_recorded`. A `graph` that fails the save shape is `422`.

### 5.20 `GET /channels/{id}/runs/{job_id}/executions/{seq}/rounds`

Query: `limit` (default 50, max 200), `offset` (default 0). Requires `channel:read`. `200` is an **Offset Page** of the execution's **Container Round**s, ordered by `round` ascending.

```json
{
  "items": [
    {
      "round": 0,
      "step_preview": { "current": { "code": "S-01" }, "index": 0, "count": 2 },
      "step_truncated": false,
      "step_totals": {},
      "status_counts": { "succeeded": 2 }
    }
  ],
  "total": 2,
  "limit": 50,
  "offset": 0
}
```

`step_preview` is the recorded step with each list cut to its first 100 elements. `step_truncated` and `step_totals` follow §5.17. A For step is `{current, index, count}`. A Batch Read step is `{rows, index, count, total}`, and `rows` keeps its first 100 elements with the original length in `step_totals`. An Until step is `{index}` when the round starts, and gains `until` (`{value}` or `{error: {code, message}}`) after the condition is evaluated. A round that stops before that evaluation has no `until` key. `previous` is not on the step. `status_counts` counts the executions of the container's direct children in that round (`container_seq` equal to `seq` and the same `round`) by status; it is `{}` for a round with no child execution. Unknown `job_id` for this channel, or an unknown `seq`, is `404 CHANNEL_RUN_NOT_FOUND`. A `seq` that exists and is not a For, Batch Read, or Until execution is `422 REQUEST_INVALID`.

### 5.21 `GET /channels/{id}/variables` and `DELETE /channels/{id}/variables/{name}`

`GET` permission is `channel:read`. Default `limit` 50, max 200. Items are ordered by `name`. An expired value is omitted. The body is an **Offset Page** of:

```json
{
  "name": "cursor",
  "value": { "at": "2026-10-12T00:00:00Z" },
  "expires_at": null,
  "updated_at": "2026-10-12T00:00:00Z"
}
```

`name` matches `^[A-Za-z0-9_.:-]{1,128}$`. `value` is JSON, at most 64 KiB encoded. `expires_at` is `null` when the value does not expire. `updated_at` is the Instant of the last write.

`DELETE` permission is `channel:write`. Success is `204` with no body. HTTP does not create or edit a value.

Check order: a name that does not match the name rule is `422 CHANNEL_VARIABLE_NAME_INVALID`; else a missing channel is `404 CHANNEL_NOT_FOUND` (the list does not return an empty page); else a delete of a name with no live value is `404 CHANNEL_VARIABLE_NOT_FOUND` and writes no audit event. That order applies to a `{name}` bound as one path segment. A URL whose decoded path contains `/` in the name position is not this operation; an unmatched route is `HTTP_NOT_FOUND`. A trailing slash resolves to the collection, which does not allow `DELETE`, and that is `HTTP_METHOD_NOT_ALLOWED`. A successful delete is a **Management Audit Event** with action `channel.owned_variable_delete`, resource type `channel_owned_variable`, resource id `{channel_id}/{name}`, and detail `{ "channel_id", "name" }`.

## 6. Errors

### 6.1 HTTP Problem Codes

| Code | HTTP | When |
| --- | --- | --- |
| `CHANNEL_NOT_FOUND` | 404 | No Data Channel for this id. A bulk Tag add or remove lists every such id in `subjects` as `{ "kind": "channel", "id" }`. A **Channel Variable** list or delete of a missing channel uses this code and does not return an empty page |
| `CHANNEL_VARIABLE_NAME_INVALID` | 422 | A **Channel Variable** name does not match the name rule |
| `CHANNEL_VARIABLE_NOT_FOUND` | 404 | A **Channel Variable** delete names no live value. No audit event is written |
| `CHANNEL_VERSION_NOT_FOUND` | 404 | No version with this number on the channel |
| `CHANNEL_DRAFT_CONFLICT` | 409 | `base_revision` or `draft_revision` is not the stored draft revision |
| `CHANNEL_GRAPH_INVALID` | 422 | Publish or an on-demand run whose scope has a validation error; the body carries `problems` |
| `CHANNEL_NOT_PUBLISHED` | 409 | On-demand run with target `published` of a channel with no published version |
| `CHANNEL_TRIGGER_INVALID` | 422 | The graph does not have exactly one trigger node |
| `CHANNEL_RUN_NOT_FOUND` | 404 | No run with this Job id on the channel |
| `CHANNEL_DATASET_UNAVAILABLE` | 404 | The dataset row endpoint cannot read the dataset. `reason` is `not_found`, `expired`, `lost`, or `foreign_run`. `reason` is a domain extension on this code |
| `REQUEST_INVALID` | 422 | Unknown fields, malformed identifiers, out-of-range fields, a Template Preview `node_id` and `path` that name no template field, a Node Sample `node_id` that is not in `graph`, a Node Sample or Template Preview `scope` that is not that node's outer-to-inner container chain, a rounds `seq` that is not a container execution, or a body that contains `pinned` |
| `CHANNEL_RUN_NOT_RERUNNABLE` | 422 | Rerun of a run that is not `failed` or whose `target` is not `published` |

### 6.2 Validation Problem Codes

| Code | When |
| --- | --- |
| `CHANNEL_GRAPH_NO_TRIGGER` | The graph has no trigger node |
| `CHANNEL_GRAPH_MULTIPLE_TRIGGERS` | The graph has more than one trigger node |
| `CHANNEL_GRAPH_TRIGGER_INPUT` | A trigger node has an inbound edge |
| `CHANNEL_GRAPH_UNREACHABLE` | A node is not reachable from any trigger node |
| `CHANNEL_GRAPH_CYCLE` | The graph contains a cycle |
| `CHANNEL_LOOP_BODY_INVALID` | A node's `parent` names a missing node or a node that is not a **For**, a Batch Read, or an **Until**, a parent chain contains a cycle, or an edge crosses a container frame. A container is a For, a Batch Read, or an Until. An edge from S to T crosses when the two `parent` values differ and S is not T's parent. The only entry is that container's `each` connected to a node whose `parent` is that container, and `each` connects only to such a node. `done` connects only outside that frame |
| `CHANNEL_GRAPH_EDGE_INVALID` | An edge names an unknown node or port |
| `CHANNEL_NODE_TYPE_UNKNOWN` | A node names an unknown node type |
| `CHANNEL_NODE_CONFIG_INVALID` | A node configuration does not satisfy its `config_schema` |
| `CHANNEL_CODE_INVALID` | A Code node's source does not compile. `path` is `["code"]`. `detail` includes the line number in the author's code |
| `CHANNEL_NODE_NAME_DUP` | Two nodes share a name |
| `CHANNEL_NODE_REF_INVALID` | A `ref` is missing, not a Python identifier, reserved, or duplicated |
| `CHANNEL_REFERENCE_UNRESOLVED` | A configuration names an Entity, attribute, Catalog Object, Locator, Source, or Data Channel that does not resolve |
| `CHANNEL_MATCH_KEY_INVALID` | A write node's match key does not resolve |
| `CHANNEL_EXPRESSION_INVALID` | A template expression does not parse |
| `CHANNEL_TEMPLATE_TYPE_MISMATCH` | A template with no `{{ }}` does not match its declared value type |
| `CHANNEL_TEMPLATE_REF_INVALID` | A template names a node that does not exist or is not an ancestor. Ancestors skip an edge that crosses a For, Batch Read, or Until frame (`docs/business-data-channel.md` §4.1). An Until `until` template may also name that Until's direct children |
| `CHANNEL_TEMPLATE_TYPE_UNKNOWN` | Warning. A template result type cannot be known until run time |
| `CHANNEL_PORT_TYPE_MISMATCH` | An edge joins ports whose coarse types differ and both are known |
| `CHANNEL_PORT_TYPE_UNKNOWN` | Warning. An edge's upstream coarse type is `unknown` |
| `CHANNEL_NODE_TYPE_VERSION` | A node's `type_version` is not the node type's current version |
| `CHANNEL_NODE_POLICY_UNSUPPORTED` | `on_error` is `error_output` and the node type does not declare an `error` output |
| `CHANNEL_ERROR_TRIGGER_REQUIRED` | `error_channel_id` names a channel whose current published version does not use `trigger.error` as its only trigger |

### 6.3 Job Error Codes

| Code | When |
| --- | --- |
| `CHANNEL_RUN_TIMEOUT` | The graph run timeout elapsed; the run log names the node it stopped at |
| `CHANNEL_WRITE_INCOMPATIBLE` | A write node with policy `fail` met a head its mapping is incompatible with |
| `CHANNEL_ITEM_LIMIT_EXCEEDED` | One node execution held more than 100000 items. SQL uses the message `Use Dataset Query, then Batch Read.` Every other capped item list uses `Use Materialize or Dataset Query, then Batch Read.` |
| `CHANNEL_DATASET_UNAVAILABLE` | A node that reads a dataset cannot use it. `error_detail.reason` is `not_found`, `expired`, `lost`, or `foreign_run`. The same code is HTTP on the dataset row endpoint (§6.1) |
| `CHANNEL_DATASET_QUOTA_EXCEEDED` | Creating or loading a dataset would exceed `channel_dataset_max_total_gb`. The platform does not evict a dataset. Reading dataset rows does not raise this code |
| `CHANNEL_ITERATION_VOLUME_EXCEEDED` | The UTF-8 byte length of the compact JSON of `iterations` exceeded 16 MiB (16777216 bytes). For a **For** the error message is `For iteration output exceeds 16 MiB. Read the items in batches.` For an Until the error message is `Until iteration output exceeds 16 MiB.` |
| `CHANNEL_UNTIL_MAX_ITERATIONS` | An Until finished `max_iterations` rounds and `until` was still false. The error message is `Until reached max_iterations before its condition became true.` The failed execution stores the finished rounds as `{index, count, iterations}`. `done` does not run |
| `CHANNEL_SQL_NOT_ONE_STATEMENT` | The rendered SQL text is empty, unreadable, or more than one statement |
| `CHANNEL_NODE_FAILED` | A node failed with `on_error` `stop`; the run record names the node and its error. A Code node sets `error_detail.reason` to `network`, `import`, `timeout`, `memory`, or `error` (and, for `error`, `type`, `message`, and `line`). A live Source query keeps the Controlled Query code in `error_detail.code` |
| `CHANNEL_VALUE_TYPE_MISMATCH` | A template result does not match its declared value type |
| `CHANNEL_OUTPUT_SCHEMA_MISMATCH` | A successful node output does not match its refined schema |
| `CHANNEL_SANDBOX_FAILED` | The expression sandbox crashed or could not be restarted |

`JOB_WORKER_LOST` applies as for every Job. `JOB_RUNNING_TIMEOUT` does not occur, because channel schedule rows carry no **Running Time Limit**.

## 7. Non-Goals

1. Resume from the failed node.
2. A channel-scoped cancel route; cancel is the platform Job cancel.
3. Creating, editing, deleting, or running channel schedule rows through the schedule surface.
4. MCP tools for Data Channel.
5. Continuing a Batch Read from the failed batch. Batches already committed stay.
