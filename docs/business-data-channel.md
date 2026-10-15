# refraq Business Rules: Data Channel

## 1. Scope

This document defines the **Data Channel** product domain: a user-orchestrated, versioned data workflow that reads from **Entity Table**s, **Source Mirror**s, **Change Log**s, and **Source**s, reshapes items, and writes rows into one or more Entity Tables. It defines the definition and its versions, the activation switch, the graph and its node families, write semantics and the match key, **Checkpoint**s, **Channel Run** semantics, triggers and the role of the **Scheduled Task**, **Global Variable**s, the unattended-first principle, authorization, and audit.

It states the boundary rules of **Source Mirror**s and **Change Log**s that workflows rely on (§9). It does not define the HTTP shapes (`docs/api-contracts-data-channel.md`), the CDC deployment, the mirror state machine and structure change policy in detail, the **Notification Channel** resource contract, or the Console canvas layout. Those are outside this document.

Related boundaries:

- HTTP contract: `docs/api-contracts-data-channel.md`.
- **Business Entity**, **Entity Version**, **Entity Table**, **Business Key**, and publish: `docs/business-entity.md`.
- **Entity Data API**: `docs/api-contracts-entity-data.md`. **Entity Access Control**: `docs/business-entity-access.md`.
- **Source**, **Catalog Object**, **Locator**, **Normalized Type**, and **Controlled Query**: `docs/business-metadata.md`.
- Platform **Job**: `docs/business-jobs.md`. Platform **Scheduled Task**: `docs/business-scheduled-tasks.md`.
- **System Parameter**s: `docs/business-system-parameters.md`.
- **Permission** and **Grant**: `docs/business-login-auth.md`.
- Console record forms: `docs/ui-console-record-form.md`.
- Problem Codes: `docs/conventions-errors.md`. Lists: `docs/conventions-pagination.md`. **Instant**s and **Schedule Timezone**: `docs/conventions-time.md`.
- Terminology: `docs/glossary.md`.

## 2. Principles

1. **The user orchestrates; the platform supplies primitives.** Incremental reads, delete handling, checkpoints, concurrency, and error handling are expressed with nodes. The platform does not derive dirty keys, check grain, or switch strategy by fan-out. Large inputs are handled by explicit volume nodes, not by a platform threshold.
2. **The platform guarantees a few invariants instead.** A **Checkpoint** advances only when the whole run succeeds and never moves backwards; a run reads change streams up to an upper bound fixed when it starts; write nodes are safe to re-execute.
3. **Unattended triggers run only a published version.** An on-demand run may execute a frozen draft snapshot and still writes Entity Tables (ADR 0055). Editing the draft never affects a run that has already been queued.
4. **When, not what.** A **Scheduled Task** decides when a run starts. Checkpoints decide what it reads.
5. **Unattended first.** Every state that would otherwise need a person to recover has an automatic policy. Manual action is an optional override (§10).
6. **Collaborate through published APIs.** Data Channel consumes Jobs, Scheduled Tasks, Metadata, Entity, and the Management Foundation through their published surfaces (`docs/backend-layout.md` §3) and does not reach into their internals.

## 3. Data Channel Definition

### 3.1 Identity

A Data Channel is a `platform`-scoped definition identified by an opaque server-issued id. It carries a required `name` and an optional `description`. `name` is a display label and is not unique. A Data Channel is not owned by a **Source** or by a **Business Entity**; one channel may read several Sources and write several Entities.

### 3.2 Draft And Channel Versions

A Data Channel has exactly one draft graph and zero or more **Channel Version**s.

- The draft is freely editable. Saving a draft replaces the whole draft graph. The draft carries a `draft_revision` that increases on every save; a save based on a stale revision is refused so that one editor does not silently overwrite another.
- An on-demand run with target `draft` may execute the draft. It freezes the graph and `draft_revision` onto the run when the run is queued, and that snapshot is what executes. Later saves do not change it. Unattended triggers never execute a draft (ADR 0055).
- Publish copies the current draft into a new Channel Version. Versions are numbered from 1 per channel, are immutable, and are never deleted while the channel exists.
- After publish the draft stays as it was and remains editable. Editing it does not change any version.
- The **current published version** is the highest-numbered version. An unattended run, and an on-demand run with target `published`, executes that version and records which one (§6.2).

### 3.3 Graph

A graph is a set of nodes, a set of directed edges, and graph settings.

- **Node.** Each node has an id, a `ref`, a node type, a name, a configuration object, a canvas position, and per-node error settings (§6.8). The node type declares its configuration schema, its input ports, and its output ports (§4.2). Node ids are assigned when the node is created and stay stable across draft saves and versions; schedule sync, checkpoints, and run records key on them. Node names are unique within a graph. `ref` is a Python identifier, unique within the graph, generated when the node is created, and editable. Expressions name a node's output by `ref` (§4.1).
- **Edge.** An edge connects one output port of a node to one input port of another node. An edge orders execution and selects a branch. It does not carry items (ADR 0056).
- **Trigger nodes are entry points.** A trigger node has no input port and no inbound edge. A run starts at exactly one trigger node: the one that minted it.
- **Loop is the only legal back edge.** A cycle is legal only when it passes through a Loop node's loop-back port.
- **Graph settings** carry the optional run timeout (§6.6) and the optional error workflow (§6.8). Graph settings are part of the version.

### 3.4 Validation

Validation is a pure function over a graph and a reference resolver. It reports every problem it finds, each naming the offending node or edge. A graph is invalid when:

1. it has no trigger node;
2. a trigger node has an inbound edge;
3. a node is not reachable from any trigger node;
4. a cycle does not pass through a Loop node;
5. an edge names an unknown node or port;
6. a node names an unknown node type;
7. a node configuration does not satisfy its node type's configuration schema;
8. a configuration names a **Business Entity**, attribute, **Catalog Object**, **Locator**, or **Source** that does not resolve;
9. a write node has no resolvable match key (§5.2);
10. node names are not unique;
11. node `ref` values are not unique, are not Python identifiers, start with `_`, are Python keywords, or are the reserved names `nodes`, `channel`, `run`, or `platform`;
12. a template field does not parse, names a node that does not exist or is not upstream, or contains no `{{ }}` and does not match its declared value type;
13. a node's `on_error` is not `stop`, or its `retry` is not null, while only stop-without-retry is supported;
14. a Manual trigger's payload uses the reserved keys `triggered_by` or `triggered_at`;
15. an edge joins ports whose coarse types are both known and not the same;
16. a node's `type_version` is not the current version of its node type.

Validate checks a graph and writes nothing. Save does not require the graph to be valid. The Console validates the graph on screen. Publish runs the same validation on the stored draft and refuses a graph that has an error. Validate also reports warnings: a template whose result type cannot be known until run time, and an edge whose upstream coarse type is `unknown`. Warnings do not make the graph invalid. A warning alone does not refuse publish.

### 3.5 Publish

Publish validates the current draft, then creates the next Channel Version from it. Before publishing, the Console presents a **confirmation list** computed from the draft:

| Section | Content |
| --- | --- |
| Mirrors to open | **Source Mirror**s that the version reads and that are not open yet; publish opens them |
| Runs to cancel | Running **Channel Run**s of this channel that execute an older version (§6.5) |
| Missing run timeout | Present when the graph settings carry no run timeout |

The confirmation list is advisory; publish does not require any section to be empty. Publish then, in order of effect:

1. stores the new immutable version;
2. reconciles the version's Scheduled nodes with **Scheduled Task** rows (§7.2);
3. requests cancel of this channel's running Channel Runs that execute an older version (§6.5);
4. requests opening of the mirrors listed in the confirmation list.

Publish does not change the activation switch (§3.6).

### 3.6 Activation Switch

A Data Channel carries an `active` switch that lives outside versions.

- A new channel starts inactive. The first publish does not activate it. The platform never changes the switch on its own, including after repeated failures (§6.8).
- **Active:** every Scheduled Task row synced from the current version is `enabled`; platform-event and change-arrival triggers dispatch.
- **Inactive:** those rows are disabled; event and change-arrival triggers do not dispatch; a schedule-minted Job of an inactive channel ends `cancelled` (§6.2). Manual runs still work.
- Deactivating does not cancel Channel Runs already queued or running.
- Changing the switch requires `channel:write` (§11).

### 3.7 Delete

Deleting a Data Channel withdraws its Scheduled Task rows by `owner_ref` (`docs/business-scheduled-tasks.md`), which cancels unfinished Jobs those rows minted, and requests cancel of the channel's other unfinished Channel Runs. Historical Jobs remain. The channel's checkpoints and run records are removed with it. Deleting a channel does not delete rows it wrote into Entity Tables.

## 4. Items, Node Types, And Node Families

### 4.1 Node Outputs, Expressions, And Dataset References

- A node executes once in a run, after every ancestor this run reached has finished. Among ready nodes, the smaller canvas `y` then the smaller `x` runs first. Execution order follows the edges. A node inside a Loop or For, or downstream of a Batch Read, may execute several times in one run; Loop, For, and Batch Read are volume nodes and are not part of the linear runner.
- A node's **output** is the JSON value its execute function returns: an object, a list, or a scalar. Binary values are not supported. The node type declares the output's coarse type and, when the configuration allows it, a refined JSON Schema. The run record stores the output in full (§6.9). A successful output that does not match that schema fails the node.
- A **template field** is one configuration string. The node type declares which fields are templates and the declared value type of each result. `{{ }}` marks one Python expression; `\{{` is a literal `{{`. After trimming, a field that is exactly one `{{ expression }}` yields that expression's Python value. Any other text, including text with no `{{ }}`, is concatenation: each expression is evaluated, converted to text, and joined. Concatenated `None` becomes an empty string. A bare `None` is not a string. Joined text is the result when the declared type is string; otherwise it is parsed once as JSON. The result must already match the declared type. The only conversion of a Python value is into a declared string. A mismatch fails the node. Expressions evaluate in one sandbox subprocess reused for the run: no network, an allow-listed import set, and time and memory limits (ADR 0056). The only workflow name in scope is `self`.
- `self.<ref>.output` is that node's output. `self.nodes["<node name>"].output` is the same value. `self.channel` carries `id`, `name`, `description`, `active`, and `settings` (`run_timeout_sec`, `error_channel_id`). `self.run` carries `id`, `target` (`draft` or `published`), `version`, `draft_revision`, `trigger_kind`, `started_at`, and `triggered_by` (`id`, `name`). `self.platform` carries `site_name`, `schedule_timezone`, `now`, and `parameters` (the current **System Parameter** values), all read-only. The validate response publishes the JSON Schema of these three objects (`docs/api-contracts-data-channel.md`). Global Variable values are not in `self`; a node reads and writes them. Credentials and other channels' run data are never in `self`.
- Naming a node that did not run, or a path that does not resolve, fails the node that holds the expression.
- A **Template Preview** evaluates one template field of a graph against one recorded **Channel Run** of the same channel. The run's recorded Expression Context and the recorded outputs of the upstream nodes the template names go into a fresh sandbox, and the result is converted to the declared value type as at run time. The graph may differ from the one the run executed; nodes match by id, and the template names them by their current `ref` and name. A template that validation rejects fails the preview with that problem. An expression or conversion failure is the error the node would record. A named node with no recorded output in that run, or a context the run did not record, is reported missing rather than failed. A Template Preview executes no node, reads no Source, and writes nothing.
- A **Dataset Reference** is a value that names a run-scoped table in the entity database. Read and SQL nodes may return one instead of a list when the result is large; Materialize turns a list into one; Batch Read turns one into batches; write nodes accept one and write in bulk inside the database. Dataset References expire with run data retention (§6.9).
- One node execution may hold at most a product-constant number of list elements in memory. Exceeding it fails that node execution with a message pointing to Batch Read.

### 4.2 Node Types

Each node type declares a configuration schema, its input ports, its output ports, a `type_version`, and an execute function. Ports order execution and select a branch; they do not carry values (ADR 0056). Each port declares a coarse type: `object`, `items`, or `unknown`. The node type may refine a JSON Schema for an output from its configuration and from upstream refined schemas. `unknown` means the refined schema is not known yet; an empty schema is not used for that. The node type catalog is served by the backend; the Console palette and configuration panels are generated from it. A node type that needs an extra **Permission** to author declares it (§11).

Each node type states its function and its place in a workflow: a `label`, a one-sentence `summary`, and a longer `description`. The catalog serves that text in English.

Port names are lower snake case. `main` carries the node's primary items or dataset reference. `error` is an output only, and only on a type that can send failed items there when `on_error` is `error_output`. Further port names are declared by the type that needs them.

### 4.3 Node Families

| Family | Node types | Role |
| --- | --- | --- |
| Trigger | Manual, Scheduled, Platform event, Changes arrived | Entry point of a run (§7) |
| Read | SQL, Read Mirror, Read Changes | Run a SQL statement, or read mirror and change rows |
| Transform | Set fields, If, Filter, Merge, Deduplicate, Code | Reshape, route, or drop items |
| Volume | Loop, Materialize, Batch Read | Iterate, and move large data by reference |
| State | Global Variable get, set, delete, set-if-absent, compare-and-set | Cross-workflow shared state (§8) |
| Write | Write Entity | Upsert, create, update, or delete Entity Table rows (§5) |

Family rules:

- **Read Mirror** reads a **Source Mirror** of any **Catalog Object**. **Read Changes** reads a **Change Log** of a mirror or of a Business Entity and returns before and after values and a sequence number; it is the only node that owns a **Checkpoint** (§6.1).
- **SQL** runs one statement on a required source: the entity database, or one registered **Source**. After rendering, the platform parses that text for the source engine and does not send it when it is empty, unreadable, or more than one statement (`CHANNEL_SQL_NOT_ONE_STATEMENT`). Save accepts a draft without it; validate and publish report `CHANNEL_NODE_CONFIG_INVALID` and do not fill in the entity database. The statement text is a template: each `{{ }}` result is spliced as text, and the author quotes values. On the entity database the session `search_path` is `entity_data` only, so an unqualified name resolves to a physical table or stem view in that schema, and the statement runs as `refraq_entity_owner` on `ENTITY_DATABASE_URL`. The platform does not wrap the statement in a read-only transaction and does not reject it for naming another schema; the database returns that result. A registered **Source** uses that Source's connection and engine. The platform does not set `search_path` and does not apply **Controlled Query** guards. `channel:write` is enough to author the node. A node may set `statement_timeout_sec` from 1 to 3600; the default is 30. A successful execution returns `{rows, count, rowcount}`. When the statement returns a result set, `rows` holds the objects and `count` is the number of rows. When it returns none, `rows` is empty and `count` is 0. `rowcount` is the driver's affected-row count when the driver reports one, otherwise `null`. More than 100000 rows fails the node. A database error fails the node and carries the database message. A lookup is SQL followed by Merge; there is no Read Entity node.
- Each read node chooses what happens when an input mirror is not in sync: continue (default), skip this run (§6.4), or fail.
- Read, SQL, and write nodes carry a statement timeout: an in-code default that a node may raise.
- **Set fields** computes values with templates (`{{ self.read_suppliers.output.rows }}`). **Code** runs Python in the same sandbox as template expressions: no network, an allow-listed module set, and time and memory limits; one sandbox subprocess is reused per run. Authoring or editing a Code node requires `channel:code_write`. Network access is never a sandbox relaxation; if needed it is a dedicated node type.

## 5. Writing Entities

### 5.1 Write Entity Node

A Write Entity node targets one **Business Entity**. One graph may hold several write nodes and write several Entities. Its configuration is:

| Field | Rule |
| --- | --- |
| Target | One Business Entity by id |
| Mode | `upsert`, `create`, `update`, or `delete` |
| Match key | §5.2 |
| Source | One template whose value is a list of objects. Static JSON is written as text, without `{{ }}`. Shaping a calculated list is an upstream node's job |
| Mapping | Optional renames: each entry names a target attribute and the source-object key that becomes it. The renamed key is consumed. Source keys without an entry are written under their own name, the match key included. An empty mapping writes source objects as they are. Every mode applies it |
| On incompatible head | `fail` (default) or `skip` (§5.4) |

Mode rules, for each source object, by the match key value:

- `upsert` inserts a row when no row has the key and updates the mapped attributes of the matching row otherwise. A row whose mapped values already equal the source object is counted as unchanged and is not written.
- `create` inserts a row. An object whose key already exists fails the node execution. The node's on-error setting applies when more than stop is supported (§6.8); until then the run fails.
- `update` updates the mapped attributes of the matching row. An object with no matching row changes nothing and is counted as unmatched.
- `delete` deletes the matching row. An object with no matching row changes nothing and is counted as unmatched. `delete` uses only the match key attribute of the projected object.

One write-node execution is one database transaction. A failure rolls the whole execution back.

Write rules:

- Only attributes present in the projected object are written. Other attributes keep their values, so several workflows, or a workflow and the **Entity Data API**, may own different attributes of the same rows. Nothing about the source objects is checked before the node runs. At run time a failure names the source object index: a mapped key that is absent, a missing match key, a key that is not a head attribute (including `row_id`), or a missing `required` attribute under `upsert` or `create`.
- Executing a write node again on the same input leaves the same table state. Under `create`, a re-execution fails on already-present keys.
- The **Business Key** is not rewritten by `update` or `upsert`. An attempt fails the execution.
- A write node appends to the target Entity's **Change Log** in the same transaction as the row write (§6.1). Self-writes are not filtered. The Change Log table is owned by Entity; a writer that cannot append yet still writes the row in that same transaction boundary.
- Write nodes write the target's head physical table only, never a superseded version (`docs/business-entity.md` §4.2).
- Writes run as the platform **System Identity**, which holds a locked grant on every Entity (`docs/business-entity-access.md`). They do not run as the triggering user.

### 5.2 Match Key

The match key is one attribute of the target head whose value identifies the row an item addresses.

- The default is the target version's **Business Key** (`docs/business-entity.md` §2.6), resolved on the head at execution.
- The author may instead name any other attribute that is `unique` on the head.
- `row_id` is never a match key.
- A write node whose match key does not resolve is invalid: the default with no Business Key on the target's current version, or a named attribute that is missing or not `unique`.

### 5.3 Following The Head

A write node addresses the target by Entity id, not by version. Each execution resolves the current head, so publishing a successor **Entity Version** does not require editing the workflow when the mapping still fits.

A mapping is **incompatible** with a head when:

1. a mapped attribute or the match key is absent from the head;
2. the match key is no longer `unique`, or the default match key is used and the head has no Business Key.

A value that cannot be encoded as the attribute's **Attribute Type** is not an incompatibility. It fails that write execution when the row is written, naming the attribute, the source index, and the value. A template with no `{{ }}` is checked against its declared value type at publish. A template that calculates is checked when the node runs, because the result is not known before then.

### 5.4 Incompatible Head Policy

- `fail` (default): the node execution fails, the run ends `failed` with a channel Problem Code, and a Notification Channel event is sent (§10).
- `skip`: the node is skipped for this execution and the run record marks it.

Entity publish does not block on incompatible write nodes. Its confirmation lists the write nodes (channel and node) that the new head would make incompatible.

## 6. Channel Run

### 6.1 Checkpoints

A **Checkpoint** is one cursor per (Data Channel, Read Changes node, stream). A stream is one Change Log.

- At run start the run fixes an upper bound for every stream it will read. Rows arriving during the run are left for the next run.
- When the whole run ends `succeeded` with outcome `completed`, every cursor the run read advances to the greater of its stored position and this run's upper bound. Overlapping runs that finish out of order never move a cursor backwards.
- A run that fails, is cancelled, or ends with outcome `skipped` advances no cursor. The next run reads from the unchanged position.
- An on-demand run may ignore checkpoints and read everything. A run with target `published` still advances cursors on success. A run with target `draft` never advances a cursor (ADR 0055).
- A cursor is **invalid** when the Change Log was cleaned past it or the mirror was resnapshotted. By default a Read Changes node with an invalid cursor reads the whole mirror once and takes the current Change Log position as its new start.
- The minimum consumed position across published Read Changes nodes is what allows a Change Log to be cleaned. A System Parameter for Change Log maximum retention bounds that; past it, a lagging cursor becomes invalid.

Schedule instants (`last_run_at`, `scheduled_for`) are never checkpoints. A skipped cron slot loses no data because the next run reads from its checkpoint.

### 6.2 A Run Is One Job

Each run is one **Job** of kind `channel_run`, executed in one worker child process. Its `input` names the channel, the target (`draft` or `published`), and run options (`docs/api-contracts-data-channel.md` §4.2). It carries no version. The runner enters the graph's single trigger node. An on-demand run may set `stop_at_node_id`. The run still enters that trigger and executes only the node's ancestor closure, including the node. When the field is omitted, the run executes every node reachable from the trigger. A closure that finishes ends `succeeded` with outcome `completed`.

- Target `published`: at start the runner resolves the current published version, records it and the graph on the run, and enters at the trigger node.
- Target `draft`: the runner executes the graph and `draft_revision` frozen when the run was queued.
- A Job whose trigger node no longer exists in the graph it executes ends `cancelled`.
- A schedule-minted Job of an inactive channel ends `cancelled`. An on-demand run is allowed while inactive.
- An on-demand run with target `published` of a channel with no published version is refused. Unattended triggers do not mint a Job for a channel with no published version.

### 6.3 No Execution Lock

The platform holds no execution lock for Data Channels. Runs of one workflow, and of different workflows, may overlap. **Kind execution lock** does not apply to `channel_run`.

Overlapping runs may write out of order: an older run can overwrite a newer value. Serializing runs is the author's choice, built from **Global Variable** set-if-absent with expiry and delete (§8).

### 6.4 Outcomes

| Terminal | Meaning |
| --- | --- |
| `succeeded`, outcome `completed` | Every reached node finished; checkpoints advance, except a run with target `draft`, which never advances a cursor |
| `succeeded`, outcome `skipped` | A read node chose to skip this run; no checkpoint advances; not a failure |
| `failed` | A node failed with stop semantics, the run timeout elapsed, or the worker was lost; the run records the last failed node and edge |
| `cancelled` | Cancel was requested, a newer version superseded the run, or §6.2 cancelled it |

A run that read a mirror while it was not in sync is marked "input mirror not in sync".

### 6.5 Version Supersede

A published run stops between node executions when a newer published version exists, and ends `cancelled`. Publish does not write Job rows; the confirmation list names the running published runs that will stop. It does not include a run with target `draft`. Queued Jobs with target `published` are not cancelled; they resolve the new version when they start. A queued Job minted by a schedule that publish withdrew is cancelled by that withdraw (§7.2). Two published versions of one channel therefore never write at the same time, except for the window between node executions while a published run notices a newer version. A `draft` run may write while a published run of the same channel writes; serializing them is the author's choice (§6.3).

### 6.6 Cancel And Layered Timeouts

Cancel is the platform Job cancel: `POST /jobs/{id}/cancel`. The worker kills the child process executing a running Job and does not wait for the current node to return. Run timeout is still checked between node executions.

Timeouts are layered:

| Layer | Owner | Effect |
| --- | --- | --- |
| Statement timeout | Read, SQL, and write nodes (in-code default; a node may raise it) | Fails that node execution |
| Run timeout | Graph settings (default none) | Checked between node executions; ends the run `failed` with `CHANNEL_RUN_TIMEOUT` and records the node it stopped at |
| **Running Time Limit** | Scheduled Task | Always null on channel schedule rows, so it never applies to `channel_run` |

Publish warns when the graph has no run timeout.

### 6.7 Reruns

A rerun of a run is a new Job on the same published version as the original, reading from the checkpoints as they stand. A Job is one attempt and is never retried in place. Resuming from the failed node is outside this document.

### 6.8 Node Errors And Persistent Failure

- Each node has an on-error setting. `stop` fails the run. `continue` and `error_output` are reserved; a graph that sets them, or that sets a retry, does not validate. A failing expression or a failing source row fails the node execution.
- Retry on failure is reserved the same way: a graph with `retry` set does not validate.
- A channel may name an error workflow, another Data Channel that runs when this channel's run fails.
- A channel whose runs keep failing stays active, is flagged persistently failing in the Console, and is announced through the Notification Channel. The platform never deactivates a workflow.

### 6.9 Run Records

Every run records the graph it executed, the Expression Context it evaluated with (`self.channel`, `self.run`, and `self.platform` as fixed at run start), and, for each node execution, its output, duration, status, and error, plus the last failed node. The output is stored in full. A recorded output is the value later expressions read, including the output of a skipped node. A list inside an output is paged when read. Dataset References in a record are pageable in full during the retention window. Run data retention is a System Parameter in days.

Editor actions (execute up to a node, pinned data, write dry run) use real data with a row limit, never write Entity Tables, and never advance checkpoints. Their contract is outside this document.

## 7. Triggers And The Schedule's Role

### 7.1 Trigger Nodes

| Trigger | Mints a Channel Run when |
| --- | --- |
| Manual | An operator with `channel:write` asks for an on-demand run of the graph's only trigger; optionally ignoring checkpoints. The run's target is `draft` or `published`. Allowed while inactive. The node's payload is a static JSON object; the node's output is that object plus `triggered_by` and `triggered_at` |
| Scheduled | Its synced Scheduled Task row is due (§7.2) |
| Platform event | A platform event matches: workflow failed, entity head switched, mirror resnapshot completed, mirror status changed |
| Changes arrived | New entries appear in a chosen mirror or entity Change Log |

Event and change-arrival dispatch is not coalesced: each dispatch scan mints one Job per trigger node with new input. Because Jobs have no retention, minute-level schedules and uncoalesced dispatch grow the Job table without bound.

### 7.2 Scheduled Node And Schedule Sync

A graph has exactly one trigger node. A Scheduled node carries one cadence (cron or interval, plus an optional **Schedule Start** stored as an Instant). Cron is interpreted in the site **Schedule Timezone**. The node has no timeout. A run entered at a Scheduled node sets that node's output to an object carrying the schedule id, the schedule name, and `scheduled_for`. An on-demand run uses the enqueue Instant as `scheduled_for` and a null schedule id when no row is synced.

The Scheduled node in the current published version is the only place its cadence is edited. Publish reconciles that node with one Scheduled Task row for the channel:

- a Scheduled trigger inserts or updates the row; a changed cadence or start rewrites `next_run_at`;
- any other trigger withdraws the row, which cancels its unfinished Jobs;
- editing the draft changes no row;
- renaming the channel rewrites the row name without a publish.

Synced rows use:

| Field | Value |
| --- | --- |
| Work kind | `channel_run` (the Job kind it mints) |
| `key` | `channel_run:{channel_id}` |
| `owner_ref` | `channel:{channel_id}` |
| Default name | `channel_run · {channel name} · {node name}` |
| Traits | `locked` + `undeletable` |
| `running_timeout_sec` | null |
| `enabled` | the channel's activation switch (§3.6) |

There is no schedule create facade for Data Channels. Operations shows these rows read-only. Run-now on them is refused because they are locked; the manual trigger is the way to run now.

### 7.3 When Versus What

The Scheduled Task decides when a run starts. Checkpoints decide what it reads (§6.1). Schedule instants are never data watermarks.

### 7.4 Platform Clock Duties

Data Channel's background duties run as hidden, `locked`, `undeletable`, `store_only` system Scheduled Tasks with in-code intervals, not System Parameters: event and change-arrival dispatch, Change Log cleanup, run data retention, mirror lag alert evaluation, CDC precondition re-check, Connect task restart with backoff, and resnapshot dispatch. The per-Source snapshot window is a gate on resnapshot dispatch, not a Scheduled Task.

## 8. Global Variables

A **Global Variable** is a named JSON value in one site-wide namespace shared by every Data Channel.

- Operations: get, set, delete, set-if-absent, and compare-and-set. Set, set-if-absent, and compare-and-set accept an optional expiry. Set-if-absent and compare-and-set are atomic.
- A name matches `^[A-Za-z0-9_.:-]{1,128}$`. A value is at most 64 KiB of JSON. An oversize write fails the node execution.
- A write takes effect immediately, not at run success, and is not rolled back when the run fails.
- An expired value is absent on the next read or conditional write. Nothing sweeps expired rows.
- Saving a node that writes a variable requires `channel:write`. The Console lists live values and allows a manual delete, recorded as a **Management Audit Event**. The contract is `docs/api-contracts-global-variables.md`.

## 9. Source Mirrors And Change Logs

Source Mirrors and their capture stack are an optional deployment. When it is absent, mirror features show as not enabled and Read Mirror and mirror Read Changes nodes cannot be published.

- **Capture.** A DBA enables change data capture on the source offline; refraq only consumes it. A database **Source** may carry an encrypted capture credential, separate from its `access` document, and a snapshot window (a daily range in the **Schedule Timezone**, default any time). A precondition check per Source reports whether capture is enabled, retention is at least 7 days, and the required signal and flush objects exist. refraq manages one connector per Source.
- **Mirror.** One shared, full-column **Source Mirror** per **Catalog Object**, in a dedicated schema of the entity database, physically named by mirror id. Columns keep source names when they are legal identifiers of at most 63 bytes and otherwise get ordinal names; types follow the **Normalized Type** plus native precision. A table without a primary key is mirrored only after key columns are declared for it.
- **Opening.** Publish opens every mirror a version reads that is not open yet (§3.5). Mirrors are managed from one global list under Operations, not from Source pages. Disabling a mirror keeps its data and Change Log; deleting mirror data is refused while a published version reads it.
- **Change Log.** The mirror applier writes the mirror row, its **Change Log** entry, and the consumer offset in one transaction. An entry is written only when values changed. Entity writes from the **Entity Data API** and from write nodes append to the entity Change Log the same way.
- **Self-healing.** A gap, a breaking structure change (the mirror can no longer upsert or delete correctly by its original key), or a pause beyond retention triggers an automatic resnapshot. Resnapshots honour the Source's snapshot window, run one table at a time per Source, retry with backoff, and delete rows that vanished at the source by mark-and-sweep generations, logging those deletes. Non-breaking structure changes are applied by policy without manual DDL.

## 10. Unattended First

Operation assumes no person is watching. Every state that would otherwise need a person to recover has an automatic policy:

| State | Automatic policy |
| --- | --- |
| A run fails | The next run retries from the unchanged checkpoint |
| A cursor becomes invalid | One full read of the mirror as the new start (§6.1) |
| An input mirror is not in sync | The read node's configured choice; continue by default |
| A run hangs | The run timeout, when set (§6.6) |
| Runs keep failing | Persistently failing flag and notification; the channel stays active (§6.8) |
| A mirror has a gap, a breaking structure change, or a pause beyond retention | Automatic resnapshot |
| A Connect task fails | Restart with backoff |

Manual action is an optional override. Only two situations require a person, and both fail the run and alert through the site-wide **Notification Channel**:

1. A source-side CDC precondition is broken (for example capture disabled or retention below the required minimum).
2. A write node's mapping is incompatible with a newly published Entity head and the node's policy is `fail` (§5.4).

A Notification Channel delivery failure never fails the operation that raised the event.

## 11. Authorization

All keys are `platform`-scoped.

| Permission | Grants |
| --- | --- |
| `channel:read` | Read channels, drafts, versions, run lists, and run records; read **Source Mirror** data through read nodes and records |
| `channel:write` | Create, edit, save drafts, validate, publish, and delete channels; Template Preview against a run record; Global Variable writes; on-demand runs (target `draft` or `published`) and rerun; cancel a `channel_run` Job |
| `channel:code_write` | Create or edit a Code node; required in addition to `channel:write` |
| `mirror:write` | Operate Source Mirrors (disable, delete data, resnapshot overrides) |

Source Mirrors are not under **Entity Access Control**. A holder of `channel:read` can see all mirror data. Grant it knowingly.

Channel schedule rows are locked, so `jobs:run` only observes them.

## 12. Management Console

The Data Channel editor is a record authoring surface (`docs/ui-console-record-form.md`): create, show, and edit share one layout, and node configuration panels follow the record-form conventions. The canvas edits the draft. The channel page shows the activation switch, the version list, and the run list. The Console names a problem by the node's display name, and by the two endpoint names when the problem names an edge. It validates the graph on screen and has no separate validate action. Where the module mounts in Console Navigation is outside this document.

An on-demand run starts only from the edit page. The header Run executes every node reachable from the trigger. A node's Run names that node as the stop node and executes only it and its ancestors, and only errors in those nodes refuse the start. Both open the same write confirmation, which names the node when there is a stop node. The show page lists runs and can cancel an unfinished run; it does not start one.

Under a template field that holds a calculation, the node configuration panel shows its **Template Preview** against the channel's latest draft **Channel Run**, for a User with `channel:write`. It evaluates again after an edit pauses and when that run records more node executions. With no draft run, the panel says that running the upstream nodes provides the values. A missing result names the nodes that have no output in that run.

While the channel's latest draft **Channel Run** has not ended `succeeded`, `failed`, or `cancelled`, the edit page keeps its editing chrome and refuses draft edits: the canvas, node configuration, name, activation switch, description, save, and publish. Refreshing the edit page applies the same lock, because the page loads that latest draft run. The lock follows the channel, not the user who started the run. Delete stays available and still requests cancel of the channel's unfinished runs.

## 13. Management Audit

Persist a **Management Audit Event** for: channel create, identity edit, draft save, publish, activation change, delete, manual run enqueue, Global Variable manual delete, and every Source Mirror operation. Each event records actor, **Instant**, resource, action, and result.

## 14. Non-Goals

1. Platform-derived incremental computation: automatic dirty-key derivation, grain checking, and fan-out thresholds.
2. An execution lock or platform serialization of runs.
3. Data Product catalog and non-Entity delivery targets.
4. Per-object authorization on Source Mirrors.
5. Notification channels other than one site-wide webhook.
6. Binary items, and node types with network access.
7. MCP tools for Data Channel or Source Mirrors.
8. Restoring source transaction boundaries at the target. Targets are atomic per batch and eventually consistent.
9. Source-side triggers installed by the platform, and source writes other than a Data Channel SQL statement or the documented CDC signal and flush objects.
10. In-place retry of a Job, and Job retention.

## 15. References

- `docs/api-contracts-data-channel.md`
- `docs/business-entity.md`
- `docs/business-entity-access.md`
- `docs/business-metadata.md`
- `docs/business-jobs.md`
- `docs/business-scheduled-tasks.md`
- `docs/business-system-parameters.md`
- `docs/business-login-auth.md`
- `docs/ui-console-record-form.md`
- `docs/glossary.md`
