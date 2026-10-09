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
3. **Only published versions run.** Editing a draft never affects a run.
4. **When, not what.** A **Scheduled Task** decides when a run starts. Checkpoints decide what it reads.
5. **Unattended first.** Every state that would otherwise need a person to recover has an automatic policy. Manual action is an optional override (§10).
6. **Collaborate through published APIs.** Data Channel consumes Jobs, Scheduled Tasks, Metadata, Entity, and the Management Foundation through their published surfaces (`docs/backend-layout.md` §3) and does not reach into their internals.

## 3. Data Channel Definition

### 3.1 Identity

A Data Channel is a `platform`-scoped definition identified by an opaque server-issued id. It carries a required `name` and an optional `description`. `name` is a display label and is not unique. A Data Channel is not owned by a **Source** or by a **Business Entity**; one channel may read several Sources and write several Entities.

### 3.2 Draft And Channel Versions

A Data Channel has exactly one draft graph and zero or more **Channel Version**s.

- The draft is freely editable and is never executed. Saving a draft replaces the whole draft graph. The draft carries a `draft_revision` that increases on every save; a save based on a stale revision is refused so that one editor does not silently overwrite another.
- Publish copies the current draft into a new Channel Version. Versions are numbered from 1 per channel, are immutable, and are never deleted while the channel exists.
- After publish the draft stays as it was and remains editable. Editing it does not change any version.
- The **current published version** is the highest-numbered version. A run always executes a published version and records which one (§6.2).

### 3.3 Graph

A graph is a set of nodes, a set of directed edges, and graph settings.

- **Node.** Each node has an id, a node type, a name, a configuration object, a canvas position, and per-node error settings (§6.8). The node type declares its configuration schema, its input ports, and its output ports (§4.2). Node ids are assigned when the node is created and stay stable across draft saves and versions; schedule sync, checkpoints, and run records key on them. Node names are unique within a graph.
- **Edge.** An edge connects one output port of a node to one input port of another node.
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
10. node names are not unique.

Validate may be called on the draft at any time and does not change anything. Publish runs the same validation and refuses an invalid graph.

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
- Changing the switch requires `channel:run` (§11).

### 3.7 Delete

Deleting a Data Channel withdraws its Scheduled Task rows by `owner_ref` (`docs/business-scheduled-tasks.md`), which cancels unfinished Jobs those rows minted, and requests cancel of the channel's other unfinished Channel Runs. Historical Jobs remain. The channel's checkpoints and run records are removed with it. Deleting a channel does not delete rows it wrote into Entity Tables.

## 4. Items, Node Types, And Node Families

### 4.1 Items And Dataset References

- An **item** is one flat JSON object. Its values may be nested JSON. Binary items are not supported.
- Edges carry lists of items between node executions, following n8n v1 execution semantics: a node executes once per input list it receives, and a node inside a Loop or downstream of a Batch Read may execute several times in one run.
- A **Dataset Reference** is a value that names a run-scoped table in the entity database. Read and SQL nodes may return one instead of items when the result is large; Materialize turns items into one; Batch Read turns one into batches of items; write nodes accept one and write in bulk inside the database. Dataset References expire with run data retention (§6.9).
- One node execution may hold at most a product-constant number of items in memory. Exceeding it fails that node execution with a message pointing to Batch Read.

### 4.2 Node Types

Each node type declares a configuration schema, its input ports, its output ports, and an execute function that receives items or Dataset References. The node type catalog is served by the backend; the Console palette and configuration panels are generated from it. A node type that needs an extra **Permission** to author declares it (§11).

### 4.3 Node Families

| Family | Node types | Role |
| --- | --- | --- |
| Trigger | Manual, Scheduled, Platform event, Changes arrived | Entry point of a run (§7) |
| Read | Read Entity, Read Mirror, Read Changes, SQL, Live Source query | Bring rows into the run |
| Transform | Set fields, If, Filter, Merge, Deduplicate, Code | Reshape, route, or drop items |
| Volume | Loop, Materialize, Batch Read | Iterate, and move large data by reference |
| State | Global Variable get, set, delete, set-if-absent, compare-and-set | Cross-workflow shared state (§8) |
| Write | Write Entity | Upsert, create, update, or delete Entity Table rows (§5) |

Family rules:

- **Read Entity** reads the head of a **Business Entity**, with filters that may reference upstream item values. A lookup is Read Entity followed by Merge; there is no separate lookup node.
- **Read Mirror** reads a **Source Mirror** of any **Catalog Object**. **Read Changes** reads a **Change Log** of a mirror or of a Business Entity and returns before and after values and a sequence number; it is the only node that owns a **Checkpoint** (§6.1).
- **SQL** addresses mirrors and entity tables with `{{obj/...}}` **Locator** references; the platform resolves physical names.
- **Live Source query** reads a **Source** directly under **Controlled Query** guards (read-only single statement, timeout, row cap, audit). The node may raise the row cap. It requires its own Permission (§11).
- Each read node chooses what happens when an input mirror is not in sync: continue (default), skip this run (§6.4), or fail.
- Read, SQL, and write nodes carry a statement timeout: an in-code default that a node may raise.
- **Set fields** computes values with restricted Python expressions (`{{ item["code"].strip() }}`). **Code** runs Python in a sandbox with no network, an allow-listed module set, and time and memory limits; one sandbox subprocess is reused per run. Authoring or editing a Code node requires `channel:code_write`. Network access is never a sandbox relaxation; if needed it is a dedicated node type.

## 5. Writing Entities

### 5.1 Write Entity Node

A Write Entity node targets one **Business Entity**. One graph may hold several write nodes and write several Entities. Its configuration is:

| Field | Rule |
| --- | --- |
| Target | One Business Entity by id |
| Mode | `upsert`, `create`, `update`, or `delete` |
| Match key | §5.2 |
| Mapping | Target attribute names, each with a value expression over the item |
| On incompatible head | `fail` (default) or `skip` (§5.4) |

Mode rules, for each input item, by the match key value:

- `upsert` inserts a row when no row has the key and updates the mapped attributes of the matching row otherwise.
- `create` inserts a row. An item whose key already exists is an item error handled by the node's on-error setting (§6.8).
- `update` updates the mapped attributes of the matching row. An item with no matching row changes nothing and is counted as unmatched.
- `delete` deletes the matching row. An item with no matching row changes nothing and is counted as unmatched. `delete` uses only the match key and ignores the mapping.

Write rules:

- Only mapped attributes are written. Unmapped attributes keep their values, so several workflows, or a workflow and the **Entity Data API**, may own different attributes of the same rows.
- Executing a write node again on the same input leaves the same table state. Under `create`, a re-execution reports already-present keys as item errors.
- A write node appends to the target Entity's **Change Log** in the same transaction as the row write (§6.1). Self-writes are not filtered.
- Write nodes write the target's head physical table only, never a superseded version (`docs/business-entity.md` §4.2).

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
2. a mapped attribute's **Attribute Type** differs from the one the mapping was validated against;
3. the match key is no longer `unique`, or the default match key is used and the head has no Business Key;
4. under `upsert` or `create`, a `required` head attribute is unmapped.

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
- A manual run may ignore checkpoints and read everything. It still advances cursors on success.
- A cursor is **invalid** when the Change Log was cleaned past it or the mirror was resnapshotted. By default a Read Changes node with an invalid cursor reads the whole mirror once and takes the current Change Log position as its new start.
- The minimum consumed position across published Read Changes nodes is what allows a Change Log to be cleaned. A System Parameter for Change Log maximum retention bounds that; past it, a lagging cursor becomes invalid.

Schedule instants (`last_run_at`, `scheduled_for`) are never checkpoints. A skipped cron slot loses no data because the next run reads from its checkpoint.

### 6.2 A Run Is One Job

Each run is one **Job** of kind `channel_run`, executed in one worker process. Its `input` names the channel, the trigger node that minted it, and run options (`docs/api-contracts-data-channel.md` §4.2). It carries no version: at start the runner resolves the current published version, records it on the run, and enters at the trigger node.

- A Job whose trigger node no longer exists in that version ends `cancelled`.
- A schedule-minted Job of an inactive channel ends `cancelled`.
- A channel with no published version cannot be run.

### 6.3 No Execution Lock

The platform holds no execution lock for Data Channels. Runs of one workflow, and of different workflows, may overlap. **Kind execution lock** does not apply to `channel_run`.

Overlapping runs may write out of order: an older run can overwrite a newer value. Serializing runs is the author's choice, built from **Global Variable** set-if-absent with expiry and delete (§8).

### 6.4 Outcomes

| Terminal | Meaning |
| --- | --- |
| `succeeded`, outcome `completed` | Every reached node finished; checkpoints advance |
| `succeeded`, outcome `skipped` | A read node chose to skip this run; no checkpoint advances; not a failure |
| `failed` | A node failed with stop semantics, the run timeout elapsed, or the worker was lost; the run records the last failed node and edge |
| `cancelled` | Cancel was requested, a newer version superseded the run, or §6.2 cancelled it |

A run that read a mirror while it was not in sync is marked "input mirror not in sync".

### 6.5 Version Supersede

Publishing a new version requests cancel of every running Channel Run of that channel that executes an older version, whatever its trigger. Queued Jobs are not cancelled; they resolve the new version when they start. A queued Job whose Scheduled node was removed by the new version is cancelled by schedule withdraw (§7.2). Two versions of one channel therefore never write at the same time, except for the cooperative-stop window of §6.6.

### 6.6 Cancel And Layered Timeouts

Cancel is the platform Job cancel: a cooperative stop request. The runner checks cancel between node executions.

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

- Each node has an on-error setting: stop (default; the run fails), continue (the failing items are dropped and the run continues), or error output (failing items go to the node's error port).
- Each node may retry on failure a bounded number of times with a wait between tries.
- A channel may name an error workflow, another Data Channel that runs when this channel's run fails.
- A channel whose runs keep failing stays active, is flagged persistently failing in the Console, and is announced through the Notification Channel. The platform never deactivates a workflow.

### 6.9 Run Records

Every run records the executed graph state: for each node execution its input and output, duration, and error; item counts on edges; and the last failed node and edge. Each node execution stores at most the first N items plus the total count, marked truncated when N is exceeded; N is a product constant. Dataset References in a record are pageable in full during the retention window. Run data retention is a System Parameter in days.

Editor actions (execute up to a node, pinned data, write dry run) use real data with a row limit, never write Entity Tables, and never advance checkpoints. Their contract is outside this document.

## 7. Triggers And The Schedule's Role

### 7.1 Trigger Nodes

| Trigger | Mints a Channel Run when |
| --- | --- |
| Manual | An operator with `channel:run` asks for a run; optionally ignoring checkpoints. Allowed while inactive |
| Scheduled | Its synced Scheduled Task row is due (§7.2) |
| Platform event | A platform event matches: workflow failed, entity head switched, mirror resnapshot completed, mirror status changed |
| Changes arrived | New entries appear in a chosen mirror or entity Change Log |

Event and change-arrival dispatch is not coalesced: each dispatch scan mints one Job per trigger node with new input. Because Jobs have no retention, minute-level schedules and uncoalesced dispatch grow the Job table without bound.

### 7.2 Scheduled Node And Schedule Sync

A Scheduled node carries one cadence (cron or interval, plus an optional **Schedule Start**). Cron is interpreted in the site **Schedule Timezone**. The node has no timeout. A workflow may hold several Scheduled nodes; each is its own entry point. A run entered at a Scheduled node starts with one item carrying the schedule id, the schedule name, and `scheduled_for`.

The Scheduled node in the current published version is the only place its cadence is edited. Publish reconciles the version's Scheduled nodes with Scheduled Task rows, keyed by node id:

- a new Scheduled node inserts a row;
- a changed cadence or start rewrites that row's `next_run_at`;
- a removed Scheduled node withdraws its row, which cancels its unfinished Jobs;
- editing the draft changes no row.

Synced rows use:

| Field | Value |
| --- | --- |
| Work kind | `channel_run` (the Job kind it mints) |
| `key` | `channel_run:{channel_id}:{node_id}` |
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

- Operations: get, set, delete, set-if-absent with optional expiry, and compare-and-set. Set-if-absent and compare-and-set are atomic.
- A write takes effect immediately, not at run success, and is not rolled back when the run fails.
- An expired value disappears; an expired lease therefore releases itself if the run that took it dies.
- Values have a size cap (product constant). An oversize write fails the node execution.
- Writing through a node requires the channel author to hold `channel:write`. The Console lists values and allows a manual delete, recorded as a **Management Audit Event**.

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
| `channel:write` | Create, edit, save drafts, validate, publish, and delete channels; Global Variable writes |
| `channel:run` | Manual runs, rerun, and the activation switch |
| `channel:code_write` | Create or edit a Code node; required in addition to `channel:write` |
| `mirror:write` | Operate Source Mirrors (disable, delete data, resnapshot overrides) |
| Live Source query key | Create or edit a Live Source query node; required in addition to `channel:write` |

Source Mirrors are not under **Entity Access Control**. A holder of `channel:read` can see all mirror data. Grant it knowingly.

Channel schedule rows are locked, so `jobs:run` only observes them.

## 12. Management Console

The Data Channel editor is a record authoring surface (`docs/ui-console-record-form.md`): create, show, and edit share one layout, and node configuration panels follow the record-form conventions. The canvas edits the draft. The channel page shows the activation switch, the version list, and the run list. Where the module mounts in Console Navigation is outside this document.

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
9. Source-side triggers, and any source writes beyond the documented CDC signal and flush objects.
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
