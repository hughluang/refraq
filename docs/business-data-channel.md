# refraq Business Rules: Data Channel

## 1. Scope

This document defines the **Data Channel** product domain: a user-orchestrated, versioned data workflow that reads from **Entity Table**s, **Source Mirror**s, **Change Log**s, and **Source**s, reshapes items, and writes rows into one or more Entity Tables. It defines the definition and its versions, the activation switch, the graph and its node families, write semantics and the match key, **Checkpoint**s, **Channel Run** semantics, triggers and the role of the **Scheduled Task**, **Global Variable**s, the unattended-first principle, authorization, and audit.

It states the boundary rules of **Source Mirror**s and **Change Log**s that workflows rely on (§9), the **Webhook** resource an `action.webhook` node calls (§4.3), and the **Email Account** an `action.email` node uses (§4.3). It does not define the HTTP shapes (`docs/api-contracts-data-channel.md`, `docs/api-contracts-webhooks.md`, `docs/api-contracts-email-accounts.md`), the CDC deployment, the mirror state machine and structure change policy in detail, or the Console canvas layout. Those are outside this document.

Related boundaries:

- HTTP contract: `docs/api-contracts-data-channel.md`. **Webhook** HTTP: `docs/api-contracts-webhooks.md`. **Email Account** HTTP: `docs/api-contracts-email-accounts.md`.
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
2. **The platform guarantees a few invariants instead.** Write nodes are safe to re-execute, and each checkpoint-owning business node declares its own read and advancement policy.
3. **Unattended triggers run only a published version.** An on-demand run may execute a frozen draft snapshot and still writes Entity Tables. Editing the draft never affects a run that has already been queued.
4. **When, not what.** A **Scheduled Task** decides when a run starts. Each checkpoint-owning business node decides what its cursor means.
5. **Unattended first.** Every state that would otherwise need a person to recover has an automatic policy. Manual action is an optional override (§10).
6. **Collaborate through published APIs.** Data Channel consumes Jobs, Scheduled Tasks, Metadata, Entity, and the Management Foundation through their published surfaces (`docs/backend-layout.md` §3) and does not reach into their internals.

## 3. Data Channel Definition

### 3.1 Identity

A Data Channel is a `platform`-scoped definition identified by an opaque server-issued id. It carries a required `name` and an optional `description`. `name` is a display label and is not unique. A Data Channel is not owned by a **Source** or by a **Business Entity**; one channel may read several Sources and write several Entities. `failure_streak` lives on the channel, outside versions (§6.8). It starts at 0.

### 3.2 Draft And Channel Versions

A Data Channel has exactly one draft graph and zero or more **Channel Version**s.

- The draft is freely editable. Saving a draft replaces the whole draft graph. The draft carries a `draft_revision` that increases on every save; a save based on a stale revision is refused so that one editor does not silently overwrite another.
- An on-demand run with target `draft` may execute the draft. It freezes the graph and `draft_revision` onto the run when the run is queued, and that snapshot is what executes. Later saves do not change it. Unattended triggers never execute a draft.
- Publish copies the current draft into a new Channel Version. Versions are numbered from 1 per channel, are immutable, and are never deleted while the channel exists.
- After publish the draft stays as it was and remains editable. Editing it does not change any version.
- The **current published version** is the highest-numbered version. An unattended run, and an on-demand run with target `published`, executes that version and records which one (§6.2).

### 3.3 Graph

A graph is a set of nodes, a set of directed edges, graph settings, and zero or more **Channel Note**s.

- **Node.** Each node has an id, a `ref`, a node type, a name, a configuration object, a canvas position, an optional `parent`, and per-node error settings (§6.8). The node type declares its configuration schema, its input ports, and its output ports (§4.2). Node ids are assigned when the node is created and stay stable across draft saves and versions; schedule sync, checkpoints, and run records key on them. Node names are unique within a graph. `ref` is a Python identifier, unique within the graph, generated when the node is created, and editable. Expressions name a node's output by `ref` (§4.1).
- **Edge.** An edge connects one output port of a node to one input port of another node. An edge orders execution and selects a branch. It does not carry items.
- **A trigger node starts a run.** A trigger node has no input port and no inbound edge. A run starts at exactly one trigger node: the one that minted it.
- **For is a container.** A node may set `parent` to the id of a **For**. That For's **Loop Body** is every node whose `parent` is that For, and only those direct children. A nested For's children belong to the inner For. Nesting has no depth limit. A parent chain that contains a cycle is illegal. The graph does not store a frame size. A body node's `position` is relative to its For's frame. The canvas derives the frame from the direct children's positions, with a margin and a minimum size.
- **Batch Read is a container.** A node may set `parent` to the id of a Batch Read. That Batch Read's direct children are the nodes whose `parent` is that Batch Read. A **For**, a Batch Read, and an **Until** may nest in any combination, with no depth limit and no further nesting constraint. A Batch Read's only ports are the input `main` and the outputs `each` and `done`. A body node's `position` is relative to that Batch Read's frame. The canvas derives the frame the same way as for a For.
- **Until is a container.** A node may set `parent` to the id of an **Until**. That Until's **Loop Body** is every node whose `parent` is that Until, and only those direct children. An Until's only ports are the input `main` and the outputs `each` and `done`. There is no `loop` port. A body node's `position` is relative to that Until's frame. The canvas derives the frame the same way as for a For.
- **The graph is acyclic.** Every cycle is illegal. A For's only ports are the input `main` and the outputs `each` and `done`. `each` is not a loop-back port.
- **An edge must not cross a frame.** A container is a **For**, a Batch Read, or an **Until**. An edge from S to T crosses a frame when the two nodes' `parent` values differ and S is not T's parent. Two omitted `parent` values are equal. A crossing is illegal in either direction. An edge from a body node to its container crosses. The only edge that may enter a frame is that container's `each` output connected to a node whose `parent` is that container, and `each` connects only to such a node. The `done` output connects only to a node outside that frame. An edge does not carry items.
- **Graph settings** carry the optional run timeout (§6.6), the optional run-retry limit, and the optional error workflow (§6.8). Graph settings are part of the version.
- A Channel Note is explanatory only. It is saved with the draft and published with the version. It has no effect on execution or validation.

### 3.4 Validation

Validation is a pure function over a graph and a reference resolver. It reports every problem it finds, each naming the offending node or edge. A graph is invalid when:

1. it has no trigger node;
2. a trigger node has an inbound edge;
3. a node is not reachable from any trigger node;
4. the graph contains a cycle;
5. an edge names an unknown node or port;
6. a node names an unknown node type;
7. a node configuration does not satisfy its node type's configuration schema;
8. a configuration names a **Business Entity**, attribute, **Catalog Object**, **Locator**, or **Source** that does not resolve;
9. a write node has no resolvable match key (§5.2);
10. node names are not unique;
11. node `ref` values are not unique, are not Python identifiers, start with `_`, are Python keywords, or are the reserved names `nodes`, `channel`, `run`, or `platform`;
12. a template field does not parse, names a node that does not exist or is not an ancestor (§4.1), or contains no `{{ }}` and does not match its declared value type;
13. a node's `on_error` is `error_output` while its node type does not declare an `error` output, or `error_channel_id` names a Data Channel whose current published version does not use `trigger.error` as its only trigger;
14. a Manual trigger's payload uses the reserved keys `triggered_by` or `triggered_at`;
15. an edge joins ports whose coarse types are both known and not the same;
16. a node's `type_version` is not the current version of its node type;
17. a node's `parent` names a missing node or a node that is not a **For**, a Batch Read, or an **Until**, a parent chain contains a cycle, or an edge crosses a container frame or violates the `each` or `done` frame rule (§3.3).

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

Deleting a Data Channel withdraws its Scheduled Task rows by `owner_ref` (`docs/business-scheduled-tasks.md`), which cancels unfinished Jobs those rows minted, and requests cancel of the channel's other unfinished Channel Runs. Historical Jobs remain. The channel's checkpoints and run records are removed with it, and the datasets of those runs are removed with the records. Deleting a channel does not delete rows it wrote into Entity Tables. A successful delete also removes that channel's **Tag** assignments. A refused delete leaves them.

### 3.8 Tags

**Tag**s belong to the Data Channel. They are not part of the draft and they are not copied onto a Channel Version. A new channel, and every channel that existed before assignments, has no Tags and `tag_revision` 1.

An operator with `channel:write` may replace the set from create, from edit, and from show, including while a draft run is in progress and whether the channel is active or inactive. The set holds at most ten Tag ids. Show and edit save that set with their own action. That action does not write the draft, does not change `draft_revision` or `draft_updated_at`, and does not change the channel `updated_at`. Create sends the set on the create body. `PATCH` does not accept Tags. While the editable field holds a name that write will submit, the section does not say there are no Tags.

The draft-run lock still blocks the canvas, the name, the description, activation, save, and publish. It does not block this Tag control.

Deactivation does not remove the assignments and does not change `tag_revision`. An inline name on create or replace requires `channel:write` and does not require `tag:write`. A name that folds onto an existing Tag attaches that Tag and does not change its stored display name.

The Channel list shows each channel's Tags. Repeatable `tag_id` keeps channels that carry any of those Tags. That condition combines with the name query and `active`. Omitting `tag_id` applies no Tag condition. An id that is not a live Tag matches no channel and does not fail the list; other ids in the same request still match. The conditions are applied together, before paging. `total` counts that set. Omitted `active` does not hide inactive channels.

## 4. Items, Node Types, And Node Families

### 4.1 Node Outputs, Expressions, And Dataset References

- Edges order nodes and select a branch. After a node finishes, an edge that leaves a live output port is live. Every other edge from that node is dead. When the node does not name live ports, every output except `error` is live. A node runs when every incoming edge in its scope has settled and at least one is live. When every incoming edge is dead, the node is dead: it does not execute, it records no execution, and its outgoing edges are dead. Among ready siblings, the smaller canvas `y` then the smaller `x` runs first, and that branch finishes before the next sibling.
- A node that is not a direct child of a **For**, a Batch Read, or an **Until** executes once. A **For** executes once and then runs its Loop Body once per element, with no edge back to the For. The body is the nodes whose `parent` is that For. On each element the body reads that For's output as `{current, index, count}` for the element. It does not read `iterations` or an earlier element. A body node may name the For and any ancestor, including nodes upstream of the For. The For records one execution. The stored output is `{current, index, count, iterations}`. `current` is the last element, and `index` is that element's zero-based position. Both are null when the list is empty, and `count` is then 0. `iterations` is an array of one object per element, in order, and is `[]` when the list is empty. Each object's keys are the **Node Ref** values of the body nodes that ran on that element, sorted by `ref`, and each value is that node's output. A node that did not run has no key and is not stored as null. A round in which no body node ran is `{}`. An If that ran is present, and its value is that node's output. A branch that did not run is absent. A nested For is one key whose value is that For's whole output. `done` runs after the body, including when the list is empty. A node reached from `done` reads the For output, including `iterations`, and does not name a body node. Cancel, supersede, and the run timeout are checked between body nodes.
- An **Until** executes once and then runs its Loop Body once per round, with no edge back to the Until. The body is the nodes whose `parent` is that Until. `index` starts at 0. During a round the body reads `{previous, index}`. `previous` is null on round 0. On a later round it is one object whose keys are the **Node Ref** values of the body nodes that ran in the previous round, sorted by `ref`, and whose values are those nodes' outputs. A node that did not run has no key and is not stored as null. The `until` template is a boolean template evaluated with the same rules as an If condition. `max_iterations` is required, an integer from 1 to 100000, with no default. The template may name ancestors of the Until and the Until's direct children. Naming a direct child is the exception to the ancestor-only rule. After the round, true ends the container successfully. False starts another round while the number of completed rounds is below `max_iterations`. An empty body is legal, and each empty round still evaluates `until`. The Until records one execution. The stored success output is `{index, count, iterations}` and has no `previous`. `count` is the number of rounds run, including the round that made `until` true. `index` is that last round's index. `iterations` is an array of one object per round, in order. Each object's keys follow the same rules as a For: the **Node Ref** values of the body nodes that ran in that round, sorted by `ref`, and each value is that node's output. A round in which no body node ran is `{}`. `done` runs after a successful end, outside the frame. A node reached from `done` reads the stored output and does not name a body node. When `max_iterations` rounds have finished and `until` is still false, the Until fails with `CHANNEL_UNTIL_MAX_ITERATIONS`. The error message is `Until reached max_iterations before its condition became true.` The failed execution stores the rounds that finished, in the same output shape, and `done` does not run. A body `on_error` of `stop` fails the run and does not run `done`. Writes committed by earlier rounds stay committed. Until adds no duration field. Cancel, supersede, and the run timeout are checked between body nodes.
- An ancestor of a node is any node reached by walking incoming edges backward, skipping an edge that crosses a container frame (§3.3). The `each` edge from a **For**, a Batch Read, or an **Until** to a node whose `parent` is that container is not a crossing, so the walk follows it. A body node's ancestors therefore include that container and every ancestor of that container. `stop_at_node_id` runs the named node and its ancestors. When a stop node is set, each round runs only the body nodes that belong to that closure. A template may name only an ancestor of the node that holds it, except an Until `until` template, which may also name that Until's direct children. The same walk is used for both.
- After each element, the For measures the UTF-8 byte length of the compact JSON of `iterations`. The text uses `,` and `:` with no extra whitespace, and characters outside ASCII are not written as `\u` escapes. Above 16 MiB (16777216 bytes) the For fails with `CHANNEL_ITERATION_VOLUME_EXCEEDED`. The error message is `For iteration output exceeds 16 MiB. Read the items in batches.` More than 100000 elements fails the For with `CHANNEL_ITEM_LIMIT_EXCEEDED`.
- After each round, an Until measures `iterations` the same way. Above 16 MiB (16777216 bytes) the Until fails with `CHANNEL_ITERATION_VOLUME_EXCEEDED`. The error message is `Until iteration output exceeds 16 MiB.`
- A node's **output** is the JSON value its execute function returns: an object, a list, or a scalar. Binary values are not supported. The node type declares the output's coarse type and, when the configuration allows it, a refined JSON Schema. The run record stores that output as §6.9 states. A successful output that does not match a schema that states a type fails the node. A schema that states no type, including `{}`, matches any JSON value (§4.2).
- A **template field** is one configuration string. The node type declares which fields are templates and the declared value type of each result. `{{ }}` marks one Python expression; `\{{` is a literal `{{`. After trimming, a field that is exactly one `{{ expression }}` yields that expression's Python value. Any other text, including text with no `{{ }}`, is concatenation: each expression is evaluated, converted to text, and joined. Concatenated `None` becomes an empty string. A bare `None` is not a string. Joined text is the result when the declared type is string; otherwise it is parsed once as JSON. The result must already match the declared type. The only conversion of a Python value is into a declared string. A mismatch fails the node. Expressions evaluate in one sandbox subprocess reused for the run: no network, an allow-listed import set, and time and memory limits. The only workflow name in scope is `self`. Objects in `self` are dicts: a key is also an attribute, and the key wins when it shares a name with a dict method. Arrays are lists. `dict(row)`, `{**row}`, `row.get("x")`, and a comprehension over `self.<ref>.output.rows` are usable, and the value that leaves the sandbox is JSON.
- `self.<ref>.output` is that node's output. `self.nodes["<node name>"].output` is the same value. `self.channel` carries `id`, `name`, `description`, `active`, and `settings` (`run_timeout_sec`, `run_retry_limit`, `error_channel_id`). `self.run` carries `id`, `target` (`draft` or `published`), `version`, `draft_revision`, `trigger_kind`, `started_at`, and `triggered_by` (`id`, `name`). `self.platform` carries `site_name`, `schedule_timezone`, `now`, and `parameters` (the current **System Parameter** values), all read-only. The validate response publishes the JSON Schema of these three objects (`docs/api-contracts-data-channel.md`). Global Variable values are not in `self`; a node reads and writes them. Credentials and other channels' run data are never in `self`.
- Naming a node that did not run, or a path that does not resolve, fails the node that holds the expression.
- A **Template Preview** evaluates one template field of a graph against one recorded **Channel Run** of the same channel, for one scope of container rounds. The run's recorded Expression Context and the upstream values selected by the **Node Sample** binding go into a fresh sandbox, and the result is converted to the declared value type as at run time. The graph may differ from the one the run executed; nodes match by id, and the template names them by their current `ref` and name. A template that validation rejects fails the preview with that problem. An expression or conversion failure is the error the node would record. A named node for which the binding has no value, or a context the run did not record, is reported missing rather than failed. A Template Preview executes no node, reads no Source, and writes nothing. An omitted scope uses the Node Sample default.
- A **Node Sample** is the one reading of a recorded Channel Run that states, for one node and one scope, the upstream values that node read and the output it produced. The node settings panel, a Template Preview, and completion all use it (§12). It executes no node, reads no Source, and writes nothing. It does not make a run safe and it does not suppress writes: a node's output is recorded only by a Channel Run that reached that node.
- The scope lists, from the outermost frame inward, each For, Batch Read, or Until that contains the node, and a zero-based `round` for each. Ancestors are the ancestor walk of the submitted graph. Executions match by node id. An omitted scope is filled in. When the node has an execution, the scope is the round chain of its latest execution. Otherwise each containing frame uses its last recorded round. The sample returns that scope. Each level names the container execution's `seq` and how many rounds that execution recorded. `seq` is absent and the round count is 0 when that frame has no recorded round.
- An ancestor that is one of those containers contributes that round's **Container Round**, not the container's stored output. A For contributes `{current, index, count}`, the step the body read. A Batch Read contributes `{rows, index, count, total}`, the step the body read. An Until contributes `{index}` and, after the condition is evaluated, `until`. `until` is `{value}` for the boolean or `{error: {code, message}}` when rendering fails. A round that stops before the condition is evaluated has no `until` key. The Until body reads `{previous, index}` at run time, and `previous` is assembled from the previous round's node executions. It is not on the round record. An ancestor whose parent is one of those containers contributes its latest `succeeded` or `skipped` execution with that container execution's `seq` and that `round`. Any other ancestor contributes its latest `succeeded` or `skipped` execution in the run. When that slot has no `succeeded` or `skipped` execution and has a `failed` execution, the sample contributes the failed execution's stored output and its error. When the slot has no execution, the ancestor has no value. The node itself contributes its latest execution inside the scope, of any status, including `running`. A `failed` or `skipped` execution contributes its stored output together with its error. Ancestors the node's templates name statically come first. The rest follow the graph's topological order.
- The sample compares the submitted node's `config` with that node in the graph the run executed. It reports that the configuration differs when the two differ, or when the snapshot has no node with that id. Each list in a sample value keeps its first 100 elements (§6.9). The value is truncated when any list was shortened, in the stored record or in the sample, and the sample records each shortened list's original length by dot path.
- A **Dataset Reference** is a claim check. The value is `{dataset_id, columns, count}` and has no `relation`. `columns` is a list of `{name, type}`, and `type` is a **Normalized Type**. The registry row is the only fact source: a read or a write loads it by `dataset_id` and does not trust `columns` or `count` on the value. The physical relation is stored only on that row. Only Dataset Query and Materialize produce a dataset. Either producer may be a direct child of a container. One execution creates one dataset. SQL, Read, and every other node return their own output and do not produce one. Batch Read reads one. Write Entity accepts a list of objects or one reference. Retention, the capacity ceiling, and paging are §6.9 and §11.
- One node execution may hold at most 100000 list elements in memory. SQL that passes that limit fails with `CHANNEL_ITEM_LIMIT_EXCEEDED` and the message `Use Dataset Query, then Batch Read.` Every other capped item list — a **For** input, a template that renders a list, and a Write Entity source that is a list — fails with `CHANNEL_ITEM_LIMIT_EXCEEDED` and the message `Use Materialize or Dataset Query, then Batch Read.`

### 4.2 Node Types

Each node type declares a configuration schema, its input ports, its output ports, an **Output View**, a `type_version`, and an execute function. Ports order execution and select a branch; they do not carry values. Each port declares a coarse type: `object`, `items`, or `unknown`. The node type may refine a JSON Schema for an output from its configuration and from upstream refined schemas. `unknown` means the refined schema is not known yet; a missing schema is not written as an empty schema. The node type catalog is served by the backend; the Console palette and configuration panels are generated from it. A node type that needs an extra **Permission** to author declares it (§11).

An Output View describes the stored success output. `kind` is `record` (one object), `rows` (a list of records plus measures), `dataset` (a **Dataset Reference** plus measures), `counts` (measures only), `container` (a For, Batch Read, or Until final output; rounds are **Container Round**s), or `value` (any JSON). `rows`, when `kind` is `rows`, is the key of the list. `dataset`, when `kind` is `dataset`, is the key of the Dataset Reference. `item`, when `kind` is `container`, is the key of the round step that holds that round's data: `current` for a For, `rows` for a Batch Read, and `index` for an Until. `metrics` lists the top-level measure keys, in display order. When the type declares a `main` output and that port's refined schema is known, every key named by `rows`, `dataset`, and `metrics` is a property of that schema. If, For, Batch Read, and Until have no `main` output. Their views describe the stored success output, and the same key rule applies to that schema: `{value}` for If, and the `done` output for For, Batch Read, and Until. The `error` output is `{code, message, detail}` and has no Output View. Each type's view is §4.3.

A template that is exactly one `{{ }}`, and whose expression is only attributes and constant indexes, is typed by walking that path on an ancestor's refined schema. `self.<ref>.output.a.b`, `self.nodes["<name>"].output.a`, and `self.<ref>.output.rows[0]` are such paths. A path that does not resolve does not supply a schema.

- Set Fields types each field on its own. A static JSON value has the schema of that value. A path that resolves has the schema at the end of the path. Any other field has property schema `{}`: the key is known and the value is unconstrained. The output schema is an object schema with `properties`.
- Filter and Deduplicate take `rows.items` from the element schema of the `items` template when that template resolves to a list.
- Merge takes an element schema from every `inputs` template. When every resolved element schema is an object, the output element schema is the union of those properties. A property whose schemas differ is `{}`. An input that does not resolve contributes no properties.
- For uses the element schema of the `items` template as `current` on `each` and on `done`, when that schema is known.
- Batch Read uses the columns of the upstream Dataset Reference as `rows.items` of the round step, when that schema is known. Otherwise each row stays an object with no properties.
- Until's `each` output is `{previous, index}`. `previous` is an object or null. `index` is an integer. The `done` output is `{index, count, iterations}`.
- SQL and a live Source query keep each row an object with no properties. The statement does not declare columns. Completion may offer keys observed on a **Node Sample** (§12). Those keys are not part of the refined schema.

The output check applies a schema that states a type. A schema that states no type, including `{}`, matches any JSON value. A property schema produced by this walk does not fail an output that the rest of the schema accepts.

Each node type states its function and its place in a workflow: a `label`, a one-sentence `summary`, and a longer `description`. The catalog serves that text in English.

Port names are lower snake case. `main` is the primary input or output port. It orders execution and does not deliver items or a dataset reference from the previous node; an expression reads an upstream output by name. `error` is an output only, and only on a type that can send failed items there when `on_error` is `error_output`. Further port names are declared by the type that needs them.

### 4.3 Node Families

| Family | Node types | Role |
| --- | --- | --- |
| Trigger | Manual, Scheduled, Error, Platform event, Changes arrived | Starts a run (§7) |
| Read | SQL, live Source query, Read Mirror, Read Changes | Run a SQL statement, read a guarded Source query, or read mirror and change rows |
| Transform | Set fields, If, Filter, Merge, Deduplicate, Code | Reshape, route, or drop items |
| Volume | For, Until, Dataset Query, Materialize, Batch Read | Iterate a list, repeat a body until a condition, and move a large result by a **Dataset Reference** |
| State | Global Variable get, set, delete, set-if-absent, compare-and-set | Cross-workflow shared state (§8) |
| Write | Write Entity | Upsert, create, update, or delete Entity Table rows (§5) |
| Action | Webhook, Email | POST one JSON body to a saved **Webhook**, or send one plain-text message through a saved **Email Account** (§4.3) |

Each type whose success output this section defines declares an **Output View**. `rows` and `dataset` are omitted unless the kind uses them. Metrics are in display order. An empty metrics list is `[]`.

| Type | kind | rows | dataset | metrics |
| --- | --- | --- | --- | --- |
| `trigger.manual` | `record` | — | — | `[]` |
| `trigger.scheduled` | `record` | — | — | `[]` |
| `trigger.error` | `record` | — | — | `[]` |
| `read.sql` | `rows` | `rows` | — | `count`, `rowcount` |
| `read.source_query` | `rows` | `rows` | — | `count`, `truncated` |
| `transform.set_fields` | `record` | — | — | `[]` |
| `transform.if` | `record` | — | — | `[]` |
| `transform.filter` | `rows` | `rows` | — | `count`, `dropped` |
| `transform.merge` | `rows` | `rows` | — | `count` |
| `transform.deduplicate` | `rows` | `rows` | — | `count`, `removed` |
| `transform.code` | `value` | — | — | `[]` |
| `volume.for` | `container` (`item` `current`) | — | — | `count` |
| `volume.until` | `container` (`item` `index`) | — | — | `count` |
| `volume.batch_read` | `container` (`item` `rows`) | — | — | `count`, `total`, `batch_size` |
| `volume.dataset_query` | `dataset` | — | `dataset` | `count` |
| `volume.materialize` | `dataset` | — | `dataset` | `count` |
| `state.variable` | `record` | — | — | `[]` |
| `write.entity` | `counts` | — | — | `inserted`, `updated`, `unchanged`, `deleted`, `unmatched` |
| `action.email` | `record` | — | — | `[]` |
| `action.webhook` | `record` | — | — | `[]` |

If stores `{value}`. For stores `{current, index, count, iterations}`; `current`, `index`, and `iterations` are the payload. Until stores `{index, count, iterations}`; `index` and `iterations` are the payload, and `previous` is not stored. Batch Read stores `{count, total, batch_size}`. A container's per-round step is a **Container Round** (§6.9), not this view. Read Mirror, Read Changes, and the platform-event and change-arrival triggers are outside the output shapes defined here.

Family rules:

- **Read Mirror** reads a **Source Mirror** of any **Catalog Object**. **Read Changes** reads a **Change Log** of a mirror or of a Business Entity and returns before and after values and a sequence number; it is the only node that owns a **Checkpoint** (§6.1).
- **SQL** runs one statement on a required source: the entity database, or one registered **Source**. After rendering, the platform parses that text for the source engine and does not send it when it is empty, unreadable, or more than one statement (`CHANNEL_SQL_NOT_ONE_STATEMENT`). Save accepts a draft without it; validate and publish report `CHANNEL_NODE_CONFIG_INVALID` and do not fill in the entity database. The statement text is a template: each `{{ }}` result is spliced as text, and the author quotes values. On the entity database the session `search_path` is `entity_data` only, so an unqualified name resolves to a physical table or stem view in that schema, and the statement runs as `refraq_entity_owner` on `ENTITY_DATABASE_URL`. The platform does not wrap the statement in a read-only transaction and does not reject it for naming another schema; the database returns that result. A registered **Source** uses that Source's connection and engine. The platform does not set `search_path` and does not apply **Controlled Query** guards. A live Source query is the guarded alternative for a registered Source. `channel:write` is enough to author the node. A node may set `statement_timeout_sec` from 1 to 3600; the default is 30. A successful execution returns `{rows, count, rowcount}`. When the statement returns a result set, `rows` holds the objects and `count` is the number of rows. When it returns none, `rows` is empty and `count` is 0. `rowcount` is the driver's affected-row count when the driver reports one, otherwise `null`. More than 100000 rows fails the node with `CHANNEL_ITEM_LIMIT_EXCEEDED` and the message `Use Dataset Query, then Batch Read.` A database error fails the node and carries the database message. SQL does not produce a **Dataset Reference**. A lookup is SQL followed by Merge; there is no Read Entity node.
- Each read node chooses what happens when an input mirror is not in sync: continue (default), skip this run (§6.4), or fail.
- Read, SQL, Dataset Query, and write nodes carry a statement timeout. SQL and other read nodes use an in-code default that a node may raise. Dataset Query and Write Entity use `statement_timeout_sec` as the wall-clock limit of the whole import or write (§4.3, §5.1).
- **Set fields** builds one object. Each entry names a key and a JSON template (`{{ self.read_suppliers.output.rows }}`). Keys are written in list order.
- **If** evaluates one boolean template and makes either the `true` or the `false` output live. The other branch, and every node reached only through it, does not run. A node with a live incoming edge still runs.
- **Filter** keeps objects from a list. Comparison operators are `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `contains`, `starts_with`, `ends_with`, `is_null`, and `is_not_null`. Equality is JSON equality: a boolean is never equal to a number. A missing field is null. `gt` and the other orderings fail the node, naming the row index, when the two values cannot be ordered. The comparison value is evaluated once. An empty condition list keeps every row. `all` keeps a row only when every condition matches; `any` keeps it when one matches.
- **Merge** folds two or more lists. `append` concatenates them. `by_key` matches one field from left to right; a null key never matches; one row may match many; the merged object is the left object updated by the right. `left` keeps unmatched left rows. `full` also appends unmatched right rows. `by_position` pairs by index: `inner` stops at the shortest list, `left` uses the first list's length, and `full` uses the longest. Later inputs overwrite earlier keys. `append` ignores `join`. An input that names a node this run did not execute fails the node.
- **Deduplicate** keeps the first object for each key combination. A missing key is null. Keys are compared as canonical JSON.
- **For** is a container whose **Loop Body** is the nodes whose `parent` is that For (§3.3). It runs that body once per element of a JSON array of at most 100000 elements, and fails with `CHANNEL_ITEM_LIMIT_EXCEEDED` past that limit. The error message is `Use Materialize or Dataset Query, then Batch Read.` Its only ports are the input `main` and the outputs `each` and `done`. `each` enters a direct child once per element. `done` runs after the body, outside the frame, including when the array is empty. The stored output is `{current, index, count, iterations}` (§4.1). Above 16 MiB of `iterations`, the node fails with `CHANNEL_ITERATION_VOLUME_EXCEEDED`.
- **Until** (`volume.until`) is a container whose **Loop Body** is the nodes whose `parent` is that Until (§3.3). Configuration is the boolean template `until` and `max_iterations`, a required integer from 1 to 100000 with no default. Its only ports are the input `main` and the outputs `each` and `done`. There is no `loop` port. It runs the body once per round until `until` is true (§4.1). During a round the body reads `{previous, index}`. The stored output is `{index, count, iterations}` and has no `previous`. A **Container Round** records `{index}` when the round starts and, after the condition is evaluated, `until` as `{value}` or `{error: {code, message}}` (§6.9). Above 16 MiB of `iterations`, the node fails with `CHANNEL_ITERATION_VOLUME_EXCEEDED` and the message `Until iteration output exceeds 16 MiB.` When `max_iterations` rounds finish with `until` still false, the node fails with `CHANNEL_UNTIL_MAX_ITERATIONS` and the message `Until reached max_iterations before its condition became true.` The failed execution stores those rounds in the same output shape, and `done` does not run.
- **Dataset Query** (`volume.dataset_query`) produces a **Dataset Reference**. Its ports are the input `main` and the outputs `main` and `error`. Configuration is `source` (the same shape as SQL), `sql` (one statement, a template, parsed for the source engine), and `statement_timeout_sec` from 1 to 3600, default 300. That timeout is the wall-clock limit of the whole import. On the entity database the session uses the owner connection and `search_path` `entity_data`, and the platform runs the author's query as the body of one statement that creates the dataset table. `_ord` is arrival order. A query that contains `ORDER BY` keeps that order when the database keeps it, and the platform does not guarantee it. On a registered **Source** (PostgreSQL, Oracle, or MSSQL) the platform streams the result into the dataset. Each call to the source uses the remaining wall-clock time as its timeout. PostgreSQL and Oracle run that read in a read-only transaction so the statement cannot write; that transaction is not an extra snapshot promise. MSSQL does not change isolation level, and a long read is not snapshot-consistent. A database error, including snapshot-too-old or a lock wait, fails the node with the database message and is not retried. Between chunks of that stream the run checks the wall-clock deadline, cancel, supersede, and the capacity ceiling (§6.9). The entity-database create is one statement and is not chunked. The output is `{dataset, count}`. `dataset` is the reference. A Dataset Query may be a direct child of a container. One execution creates one dataset. Inside a container, each round is its own execution and therefore its own dataset. Quota and retention are unchanged (§6.9).
- **Materialize** (`volume.materialize`) produces a **Dataset Reference** from one in-memory list. Configuration is `items`, a template whose value is a list of objects and is subject to the item limit in §4.1. The node infers each column from the whole list: boolean, integer, float, and string stay themselves; mixed integer and float is float; an integer that does not fit in a 64-bit integer is decimal; an object, an array, or mixed types is json; an all-null column is string. The physical column follows that **Normalized Type**. The list is copied in chunks, and the capacity ceiling is checked between chunks (§6.9). The output matches Dataset Query. A Materialize may be a direct child of a container. One execution creates one dataset, as for Dataset Query.
- **Batch Read** (`volume.batch_read`) is a container (§3.3). Configuration is `dataset`, a template whose value is a **Dataset Reference**, and `batch_size`, an integer from 1 to 100000, default 1000. Its only ports are the input `main` and the outputs `each` and `done`. It runs its direct children once per batch. Round `index`, from 0, reads every row whose `_ord` is in `(index × batch_size, (index + 1) × batch_size]`, in `_ord` order. That round's input is the full page, not a preview. The value the body reads is `{rows, index, count, total}`. `rows` omits `_ord`. `count` is the number of batches. `total` is the number of rows. The stored output is `{count, total, batch_size}` and has no `iterations`, so the 16 MiB iteration cap does not apply. An empty dataset runs no child, and `done` still runs. The path is not atomic: each round's Write Entity execution is its own transaction, and a failure leaves batches already committed. `stop` fails the run, does not run `done`, and the error names the failed batch `index`. A For, a Batch Read, and an Until may nest in any combination (§3.3). A node that reads the dataset and finds it unusable fails with `CHANNEL_DATASET_UNAVAILABLE`.
- **Live Source query** reads a small result from one registered **Source** through **Controlled Query**: one read-only statement, the platform `query_timeout_sec`, a per-node row cap, and a `query.run` **Management Audit Event** whose actor is the System Identity. It is the guarded alternative to the SQL node on a Source, which applies no Controlled Query guards. `source_id` must resolve to a Source. `sql` is a string template. `row_cap` is an integer of at least 1 and defaults to 100; a cap above the platform `query_max_rows` fails the node. A successful execution returns `{rows, count, truncated}`. Each row is an object keyed by column name. `truncated` is true when the Source had more rows than the cap. A guard, timeout, or row-limit failure fails the node with `CHANNEL_NODE_FAILED`, the Controlled Query message, and that code in `error_detail.code`. Authoring it requires `channel:source_query` (§11). It does not require `query:run`.
- **Error** (`trigger.error`) is the only trigger of a Data Channel used as another channel's error workflow (§6.8). It has no configuration. It has no schedule row. Its output is the failed run's identity when the platform starts it, or a test object when an operator starts it by hand (§7.1).
- **Webhook** (`action.webhook`) POSTs the JSON value of a body template to one saved **Webhook**. The call uses HTTPS only, refuses a loopback, link-local, private, or cloud-metadata address, and waits at most 30 seconds. A stored bearer secret is sent as `Authorization: Bearer`. A refused address, a timeout, a connection failure, or an HTTP status of 400 or higher fails the node execution. The node's `on_error` then applies. The platform does not call a Webhook except from this node or from the catalog's test action. Authoring the node requires `channel:write` and a Webhook id that exists. Network access stays inside this node; the Code sandbox never gains it.
- **Email** (`action.email`) sends one plain-text message through one saved **Email Account**. `to`, `subject`, and `body` are templates rendered once. `to` splits on comma and semicolon. `from` is the account's mailbox. The call waits at most 30 seconds. It sends nothing and fails the node when any address is not one mailbox, there are more than 50 recipients, `subject` is longer than 998 characters, `body` is larger than 256 KiB, the connection fails, TLS does not complete as configured, or the server refuses any recipient. A refused recipient aborts before the message data is sent. The node's `on_error` then applies. A success output is `{ok: true}`. The platform does not classify the SMTP host, require TLS, or require authentication. Certificate verification runs unless the account sets `tls_skip_verify`. The platform does not send mail except from this node or from the catalog's test action. Authoring the node requires `channel:write` and an Email Account id that exists. Retrying the node sends another message. Network access stays inside this node.
- **Code** runs Python in the same sandbox as template expressions. The source is the body of `def main(self)`, and the returned value is the node output and must be JSON. One sandbox subprocess is reused per run. There is no network, and imports are limited to an allow-listed module set. Each call has its own wall-clock limit (`timeout_sec`, default 30, at most 300). The process CPU limit is only a safety net so a long run is not killed by accumulated CPU time. A syntax error found at validation is `CHANNEL_CODE_INVALID`. A run failure is `CHANNEL_NODE_FAILED` with `error_detail.reason` of `network`, `import`, `timeout`, `memory`, or `error`. Authoring or editing a Code node requires `channel:code_write`. Network access is never a sandbox relaxation; if needed it is a dedicated node type.

## 5. Writing Entities

### 5.1 Write Entity Node

A Write Entity node targets one **Business Entity**. One graph may hold several write nodes and write several Entities. Its configuration is:

| Field | Rule |
| --- | --- |
| Target | One Business Entity by id |
| Mode | `upsert`, `create`, `update`, or `delete` |
| Match key | §5.2 |
| Source | One template whose value is a list of objects or a **Dataset Reference**. Static JSON is written as text, without `{{ }}`. Shaping a calculated list is an upstream node's job. A reference is read by `dataset_id` from the registry (§4.1). Mapping renames columns by name the same way it renames object keys |
| Mapping | Optional renames: each entry names a target attribute and the source-object key that becomes it. The renamed key is consumed. Source keys without an entry are written under their own name, the match key included. An empty mapping writes source objects as they are. Every mode applies it |
| On incompatible head | `fail` (default) or `skip` (§5.4) |
| `statement_timeout_sec` | Integer seconds from 1 to 3600. Absent means 300. This is the wall-clock limit of the whole write. Before each statement the remaining time is that statement's server timeout |

Mode rules, for each source object, by the match key value:

- `upsert` inserts a row when no row has the key and updates the mapped attributes of the matching row otherwise. A row whose mapped values already equal the source object is counted as unchanged and is not written.
- `create` inserts a row. An object whose key already exists fails the node execution. The node's on-error setting applies when more than stop is supported (§6.8); until then the run fails.
- `update` updates the mapped attributes of the matching row. An object with no matching row changes nothing and is counted as unmatched.
- `delete` deletes the matching row. An object with no matching row changes nothing and is counted as unmatched. `delete` uses only the match key attribute of the projected object.

One write-node execution is one database transaction. A dataset source is staged in full, validated in full, and written in that same transaction. Any failure rolls the whole execution back and leaves the target unchanged. A list source is the same one transaction. A Write Entity that runs inside a Batch Read round is still one transaction for that round; the rounds are not one transaction (§4.3). A source list longer than 100000 objects fails with `CHANNEL_ITEM_LIMIT_EXCEEDED` and the message `Use Materialize or Dataset Query, then Batch Read.` A dataset the node cannot read fails with `CHANNEL_DATASET_UNAVAILABLE`.

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

- `fail` (default): the node execution fails and the run ends `failed` with a channel Problem Code. The node's `on_error` applies (§6.8).
- `skip`: the node is skipped for this execution and the run record marks it.

Entity publish does not block on incompatible write nodes. Its confirmation lists the write nodes (channel and node) that the new head would make incompatible.

## 6. Channel Run

### 6.1 Checkpoints

A **Checkpoint** is a durable cursor owned by a concrete business node that reads an incremental stream. The node's configuration defines when it reads a stored cursor, what upper bound it fixes, when it advances, how it handles an invalid cursor, and whether an on-demand `ignore_checkpoints` request changes that behaviour.

The Channel Run framework stores and exposes the run option but does not infer checkpoint effects from `target` or a stop node. A draft run and a published run therefore have no framework-level difference in checkpoint policy. The configuration shape and exact rules for a Read Changes node belong to the CDC node contract and are outside this document.

Schedule instants (`last_run_at`, `scheduled_for`) are never checkpoints.

### 6.2 A Run Is One Job

Each run is one **Job** of kind `channel_run`, executed in one worker child process. Its `input` names the channel, the target (`draft` or `published`), and run options (`docs/api-contracts-data-channel.md` §4.2). A rerun and a `retry` Job also pin a published version. Every other `published` run carries no version. The runner enters the graph's single trigger node. An on-demand run may set `stop_at_node_id`. The run still enters that trigger and executes only the node's ancestor closure, including the node (§4.1). When the stop field is omitted, the run executes every node reachable from the trigger. A closure that finishes ends `succeeded` with outcome `completed`.

- Target `published`, without a pin: at start the runner resolves the current published version, records it and the graph on the run, and enters at the trigger node.
- Target `published`, with a pin: the runner loads that version and does not replace it with a newer one. A missing version ends the Job `cancelled`. A pinned run does not end because a newer version exists (§6.5).
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
| `succeeded`, outcome `completed` | Every reached node finished; each checkpoint-owning node applies its configured advancement policy |
| `succeeded`, outcome `skipped` | A read node chose to skip this run; checkpoint effects follow the owning node's configured policy; not a failure |
| `failed` | A node failed with `on_error` `stop` after its tries were used, the run timeout elapsed, or the worker was lost; a node failure records `failed_node_id` |
| `cancelled` | Cancel was requested, a newer version superseded the run, or §6.2 cancelled it |

A run that read a mirror while it was not in sync is marked "input mirror not in sync".

### 6.5 Version Supersede

A published run that is not pinned to a version stops between node executions when a newer published version exists, and ends `cancelled`. A pinned run keeps its version. Publish does not write Job rows; the confirmation list names the running published runs that will stop. It does not include a run with target `draft` or a pinned run. Queued Jobs with target `published` and no pin are not cancelled; they resolve the new version when they start. A queued pinned Job keeps its version. A queued Job minted by a schedule that publish withdrew is cancelled by that withdraw (§7.2). Two published versions of one channel therefore never write at the same time, except for the window between node executions while a published run notices a newer version. A `draft` run may write while a published run of the same channel writes; serializing them is the author's choice (§6.3).

### 6.6 Cancel And Layered Timeouts

Cancel is the platform Job cancel: `POST /jobs/{id}/cancel`. The worker kills the child process executing a running Job and does not wait for the current node to return. Run timeout is still checked between node executions.

Timeouts are layered:

| Layer | Owner | Effect |
| --- | --- | --- |
| Statement timeout | Read and SQL nodes (in-code default; a node may raise it). Dataset Query and Write Entity: `statement_timeout_sec` is the wall-clock limit of the whole import or write | Fails that node execution |
| Run timeout | Graph settings (default none) | Checked between node executions; ends the run `failed` with `CHANNEL_RUN_TIMEOUT` and records the node it stopped at |
| **Running Time Limit** | Scheduled Task | Always null on channel schedule rows, so it never applies to `channel_run` |

Publish warns when the graph has no run timeout.

### 6.7 Reruns

A rerun of a failed published run is a new Job on the same published version as the original. The runner executes that pinned version. Checkpoints are whatever each node reads when it runs; the rerun does not store or restore a cursor. A Job is one attempt and is never retried in place. Resuming from the failed node is outside this document. Requires `channel:write`. A run that is not both `failed` and `target` `published` is refused.

### 6.8 Node Errors, Run Retry, And Persistent Failure

- Each node has `on_error` of `stop`, `continue`, or `error_output`. A failing expression or a failing source row fails that node execution. The engine does not split one execution into successful and failed rows.
- `stop` fails the run and records `failed_node_id`.
- `continue` records the node execution as failed with a null output, keeps every output except `error` live, and does not fail the run or set `failed_node_id`.
- `error_output` is valid only when the node type declares an `error` output. The execution is recorded as failed, only the `error` port is live, and the output is an object `{code, message, detail}`. The run does not fail because of that node.
- `retry` is null or `{max_tries, wait_sec}`. `max_tries` is 1 to 10 and counts the first execution. `wait_sec` is 0 to 3600. Null executes once. The engine repeats the node until it succeeds or the tries are used. Each try is its own node execution. Cancel and the run timeout end the run before the next try, including during `wait_sec`. `on_error` applies only after the tries are used.
- `run_retry_limit` is null or an integer 0 to 10. Null and 0 mint no further Job. When a published run ends `failed`, and this chain has minted fewer additional Jobs than the limit on the graph that ran, the platform mints one new `channel_run` pinned to that version. Its trigger kind is `retry`, its actor is the System Identity, and its input carries `retry_of_job_id`. Draft runs do not mint these Jobs. A run whose trigger kind is `error` does not mint one.
- `error_channel_id` names another Data Channel. When a run ends `failed` and no further retry Job will be minted, the platform starts that channel once, including after a draft run fails. The target must be active, and its current published version's only trigger must be `trigger.error`. Otherwise the source Job records a log line and no error run is minted. The error run's trigger kind is `error`, its actor is the System Identity, and `trigger_ref` is the source Job id. Its trigger output carries the failed run's identity and error. A run with trigger kind `error` does not start another error workflow. An error run's failure does not change the source run. Cancel does not start an error workflow.
- Publish refuses `error_channel_id` unless the target exists, is not this channel, and its current published version uses `trigger.error`.
- `failure_streak` lives on the channel, outside versions. It counts a published run whose failure mints no further retry Job, and increases by one for that episode. A published run that succeeds sets it to zero. At 3 the Console shows the channel as persistently failing. The platform does not change `active` because of the streak and does not call a **Webhook** or send mail because of it.

### 6.9 Run Records

Every run records the graph it executed, the Expression Context it evaluated with (`self.channel`, `self.run`, and `self.platform` as fixed at run start), and, for each node execution, its output, duration, status, and error, plus `failed_node_id` when a node failed the run with `on_error` `stop`. A node execution inside a **For**, a Batch Read, or an **Until** also records `container_seq` and `round`. `container_seq` is the `seq` of the direct container's execution, and is null when the node is not inside a container. `round` is the zero-based round index, and is null in the same case. Walking `container_seq` reaches the outer containers. A recorded output is the value later expressions and a **Template Preview** read, including the output of a skipped node.

Each node execution records its **Execution Input**: the template fields that execution evaluated. The record maps a configuration path to `{value}` or to `{error: {code, message}}`. A path is dot-separated, and a list index is a numeric segment, as in `sql`, `fields.0.value`, or `mapping.0.key`. Each list in a stored value keeps its first 100 elements, and the original length of each list is recorded by that list's dot path, including a list that was not shortened. An execution that recorded no input leaves the input absent.

A **Container Round** is recorded when a For, a Batch Read, or an Until starts a round. A For records `{current, index, count}`, the step that round's body reads. A Batch Read records `{rows, index, count, total}`. `rows` keeps its first 100 elements, and the original length is recorded with the round. The body of that round still reads the full `_ord` page (§4.3). An Until records `{index}` when the round starts. After the condition is evaluated, the same round gains `until`: `{value}` for the boolean, or `{error: {code, message}}` when rendering fails. A round that stops before the condition is evaluated has no `until` key. The Until body reads `{previous, index}` at run time, and `previous` is not on the round. The round is addressed by the run, the container execution's `seq`, and the zero-based round. Later rounds do not remove earlier rounds. The container's stored output stays the final output (§4.1, §4.3). A **Node Sample** reads these records (§4.1). The Until execution's **Execution Input** may stay absent; the condition is on the round, and a Node Sample of that Until copies the selected round's `until` entry into the presented input without writing the execution.

A node execution stores its full output, including a successful execution whose container ancestors include a Batch Read. The execution is not marked preview-only. A **For** nested inside a Batch Read stores full `iterations`, still subject to the 16 MiB cap (§4.1). A failed execution stores its full output. Run detail summarizes executions per node and does not embed them. The execution list pages the stored records. `output_preview` cuts each list to 100 elements for that response. The separate output read pages the stored value. A stored output that carries the preview envelope reads as preview-only, and the output read pages that stored preview. Each **Execution Input** list keeps its first 100 elements and the original length. A Batch Read round's own input is the full `_ord` page (§4.3). The Batch Read path is not atomic (§4.3).

A **Dataset Reference** in a record is pageable for as long as the dataset can be read (§11). The dataset registry is the only fact source (§4.1). A row is registered `loading` before its table is created, becomes `ready` when the load finishes, and becomes `dropped` only after the table is deleted. A failed load, a retry, or a quota abort deletes that attempt's table and marks the row `dropped`. A ready dataset whose registry row count is greater than 0 and whose table has no row is `lost`. That check does not count the table. A consumer that cannot use the dataset fails with `CHANNEL_DATASET_UNAVAILABLE` and a cause of `not_found`, `expired`, `lost`, or `foreign_run`.

There is no separate trial column. A manual trial is a run whose `target` is `draft`. A published run a user starts is not a trial. `expires_at` is written when the run first becomes terminal, including a terminal state reached by lost detection. It is the Job's `finished_at` plus the parameter value at that moment. A later edit of the parameter does not change an `expires_at` already written. A run that is not terminal keeps `expires_at` null and is not purged.

| Run | Clock | Parameter |
| --- | --- | --- |
| `succeeded`, and `target` is not `draft` | Hours from `finished_at` | `channel_dataset_success_retention_hours`. 0 means the next purge deletes those datasets |
| `failed`, `cancelled`, or `target` `draft` (including a succeeded draft) | Days from `finished_at` | `channel_dataset_retention_days` |

The two retention parameters do not constrain each other. Channel run records are kept for `channel_run_record_retention_days`. The hourly task in §7.4 deletes a record, its node executions, its container rounds, and its datasets, when the Job is terminal and `created_at` is older than that many days. A dataset is removed at whichever comes first: its `expires_at`, or the deletion of its run record. Jobs stay.

Used capacity is the sum of `size_bytes` on registry rows in `loading` or `ready`. A `loading` row's `size_bytes` grows as chunks land. The ceiling is `channel_dataset_max_total_gb`. The platform does not evict a dataset to make room. The check runs before a dataset table is created. A streaming load (Materialize, or an external Source) checks again after each chunk, and on failure drops that attempt's table and fails with `CHANNEL_DATASET_QUOTA_EXCEEDED`. An entity-database Dataset Query creates the table in one statement, checks only before that statement, and may exceed the ceiling by one dataset.

There is no editor-execution resource and no dry-run. The framework does not suppress writes, roll back node effects, limit rows during execution, or create a synthetic run identity. Every Channel Run shares the Job, worker, run record, cancellation, audit, and node semantics.

## 7. Triggers And The Schedule's Role

### 7.1 Trigger Nodes

| Trigger | Mints a Channel Run when |
| --- | --- |
| Manual | An operator with `channel:write` asks for an on-demand run of the graph's only trigger, optionally stopping at one node or requesting that checkpoint-aware nodes ignore stored cursors. The run's target is `draft` or `published`. Allowed while inactive. The node's payload is a static JSON object; the node's output is that object plus `triggered_by` and `triggered_at` |
| Error | The platform starts this channel as another channel's error workflow (§6.8). The trigger output is `channel_id`, `channel_name`, `job_id`, `version`, `attempt`, `error` (`code`, `message`, `node_id`), `triggered_by`, and `triggered_at` for the failed run. `attempt` counts the failed run and the retry Jobs already minted for that chain. An on-demand run of this trigger is a test: `channel_id`, `job_id`, and `version` are null, `attempt` is 0, and `error.code` is `CHANNEL_ERROR_TRIGGER_TEST` |
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

The Scheduled Task decides when a run starts. Each checkpoint-owning business node decides what its cursor means (§6.1). Schedule instants are never data watermarks.

### 7.4 Platform Clock Duties

Data Channel's background duties run as hidden, `locked`, `undeletable`, `store_only` system Scheduled Tasks with in-code intervals, not System Parameters: event and change-arrival dispatch, Change Log cleanup, run data retention, mirror lag alert evaluation, CDC precondition re-check, Connect task restart with backoff, and resnapshot dispatch. The per-Source snapshot window is a gate on resnapshot dispatch, not a Scheduled Task.

Run data retention is seeded. Its key is `channel_run_record_retention`, its name is `Purge channel run records`, its interval is one hour, and its task is `backend.channel.tasks.purge_run_records`. Each pass deletes a channel run record whose Job is terminal (`succeeded`, `failed`, or `cancelled`) and whose `created_at` is older than `channel_run_record_retention_days`, and with that record its node executions, its container rounds, and its datasets. The same pass deletes a dataset whose `expires_at` is set and due, and drops a dataset table that has no registry row. It does not purge a dataset whose `expires_at` is null. Jobs stay.

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
| A run fails | Each checkpoint-owning node applies its configured recovery and advancement policy |
| A cursor becomes invalid | One full read of the mirror as the new start (§6.1) |
| An input mirror is not in sync | The read node's configured choice; continue by default |
| A run hangs | The run timeout, when set (§6.6) |
| Runs keep failing | Persistently failing flag in the Console; the channel stays active (§6.8). No Webhook is called and no mail is sent |
| A mirror has a gap, a breaking structure change, or a pause beyond retention | Automatic resnapshot |
| A Connect task fails | Restart with backoff |

Manual action is an optional override. Two situations require a person, and both fail the run:

1. A source-side CDC precondition is broken (for example capture disabled or retention below the required minimum).
2. A write node's mapping is incompatible with a newly published Entity head and the node's policy is `fail` (§5.4).

Neither situation calls a **Webhook** or sends mail. An author who wants a call or a message places an `action.webhook` or `action.email` node where the graph still runs, or in the error workflow.

## 11. Authorization

All keys are `platform`-scoped.

| Permission | Grants |
| --- | --- |
| `channel:read` | Read channels, drafts, versions, run lists, and run records, including the execution list, container rounds of a container execution, and paging dataset rows of a run record; read **Source Mirror** data through read nodes and records |
| `channel:write` | Create, edit, save drafts, validate, publish, and delete channels; replace the channel's **Tag**s, including an inline Tag name; Template Preview and **Node Sample** against a run record; Global Variable writes; on-demand runs (target `draft` or `published`, with an optional stop node) and rerun; cancel a `channel_run` Job; reference an existing **Webhook** from an `action.webhook` node; reference an existing **Email Account** from an `action.email` node. Inline Tag creation does not require `tag:write` |
| `channel:code_write` | Author a Code node. Required in addition to `channel:write` |
| `channel:source_query` | Author a live Source query node. Required in addition to `channel:write`. Does not grant `query:run` |
| `webhook:read` | List and read **Webhook**s. Controls the Console Module |
| `webhook:write` | Create, update, test, and delete **Webhook**s. Not implied by `channel:write` |
| `email_account:read` | List and read **Email Account**s. Controls the Console Module |
| `email_account:write` | Create, update, test, and delete **Email Account**s. Not implied by `channel:write` |
| `mirror:write` | Operate Source Mirrors (disable, delete data, resnapshot overrides) |

Draft save compares the submitted graph with the stored draft. For a node whose type declares a permission: adding it (no stored node with that id, or the stored node had another type), or changing its `type`, `type_version`, or `config`, requires that permission. Otherwise the save is `403 AUTH_FORBIDDEN` and the detail names the node. An unchanged guarded node does not require the permission. Deleting one does not. Publish requires the caller to hold every permission declared by node types present in the draft, including nodes that did not change. Missing one is `403 AUTH_FORBIDDEN` and the detail names the node.

Source Mirrors are not under **Entity Access Control**. A holder of `channel:read` can see all mirror data. Grant it knowingly.

Channel schedule rows are locked, so `jobs:run` only observes them.

## 12. Management Console

The Data Channel editor is a record authoring surface (`docs/ui-console-record-form.md`): create, show, and edit share one layout, and node configuration panels follow the record-form conventions. The canvas edits the draft. The channel page shows the activation switch, the version list, and the run list. The Console names a problem by the node's display name, and by the two endpoint names when the problem names an edge. It validates the graph on screen and has no separate validate action. Where the module mounts in Console Navigation is outside this document.

The channel list shows each row's Tags and filters by Tag and by activation. The Tag control searches the Tag vocabulary as the operator types and does not create a Tag. Each selected id is sent as `tag_id`. Choosing no Tag omits that parameter. The activation control opens unset, so the opening request does not send `active` and inactive channels stay visible. The operator can choose active only or inactive only, and can clear that choice so the request omits `active` again. An operator who can read Channels can search and select Tags without `tag:read`.

An on-demand run starts only from the edit page. The header Run executes every node reachable from the trigger. A node's Run names that node as the stop node and executes only it and its ancestors (§4.1), and only errors in those nodes refuse the start. Both open the write confirmation, may perform every normal node effect, create a run record, and are observed and cancelled through the run and Job surfaces. There is no non-writing editor execution or execution row limit. The show page lists runs and can cancel an unfinished run; it does not start one.

The node settings panel has three columns: upstream, configuration, and result. For a User with `channel:write`, a sample bar above the columns is shared by all three. The bar reads a **Node Sample** of the channel's latest draft **Channel Run**. It names that run's target (`draft` or `published`), its start time, and whether the run's stop node is this node. When the node is a For, a Batch Read, or an Until, or sits inside one, the bar includes a round control: previous, next, go to a round, and go to the first failed round. The control counts rounds from 1. The scope's `round` stays zero-based. The three columns, every field preview, and completion use that one scope. When the sample reports that this node's configuration differs from the run's snapshot, the bar says the configuration was edited after that run. With no draft run, the panel says that running the upstream nodes provides the values. A Node Sample does not start a run.

The upstream column lists the sample's upstream nodes. A node the configuration names starts expanded. The others stay collapsed as the other available upstream nodes. Each value is shown with that node's **Output View**. A container the node sits in is an ordinary upstream entry whose value is the selected **Container Round**: the step key named by the view's `item` is rendered as a record for a For's `current`, as a rows table for a Batch Read's `rows`, and as the round index for an Until's `index`, and the remaining step keys are measures. Its title carries the round number, which leads to the container's round table. A node with no recorded value is shown as not recorded.

The result column shows this node's output with its Output View. A failed or skipped execution shows the error and the stored output together. The round control changes which execution is shown. The panel does not list execution sequence numbers.

The result column of a For, a Batch Read, or an Until is its round table, rendered like any rows output: one row per **Container Round**, numbered from 1, with that round's data and the status counts of its direct children. A For row spreads the fields of `current` into columns. A Batch Read row shows its `_ord` range and row count and expands into that batch's rows. An Until row shows `index` and, when that round has evaluated its condition, the condition. Round selection for an Until is that zero-based `index`, and the body outputs shown are those nodes' execution records. Rounds with a failed child are highlighted. Selecting a row selects that round for the round control and for every node inside the container. A node reached from a For's or an Until's `done` sees `iterations` as a rows table with one row per round and one column per body node `ref`.

The same Output View rendering is used on the run detail page.

- `record`: a key-value tree. A nested object collapses.
- `rows`: a table. The columns are the properties of the row schema and the keys observed in the sample, in the order each key is first seen. The table states that it shows 100 of N rows. A further page is the execution output read at `path` `rows`, which pages the stored output. An execution marked preview-only does not page.
- `dataset`: the column list, the row count, and a table of rows. `dataset_id` is secondary and can be copied.
- `counts`: the metrics, each with its label.
- `container`: the number of rounds, the metrics, and a way to open the rounds.
- `value`: the JSON value.

A metric is a labeled badge. The label is the locale key `channels.view.metric.<key>`.

A key, a cell, or a column header in the upstream column inserts its path at the caret of the template field that last had focus. The path begins at `self.<ref>.output`. An identifier segment is `.name`. Any other key is `["key"]`. A list index is `[i]`. A column header inserts the path of the list. When the caret is inside `{{ }}`, the insertion is the path. Otherwise the insertion is `{{ path }}`. When no template field has focus, the control is disabled and the panel says that a template field must have focus.

Under every template field, including a nested mapping value, a filter value, and a list item, the panel shows the value that field took in this sample, from the node's **Execution Input**. After the field is edited, the panel shows a **Template Preview** of that field for the same scope.

Completion uses the Node Sample of the same scope. At an element of an array, such as `rows[0].`, the candidates are the properties of the element schema and the keys observed on that element.

While the channel's latest draft **Channel Run** has not ended `succeeded`, `failed`, or `cancelled`, the edit page keeps its editing chrome and refuses draft edits: the canvas, node configuration, name, activation switch, description, save, and publish. Refreshing the edit page applies the same lock, because the page loads that latest draft run. The lock follows the channel, not the user who started the run. Delete stays available and still requests cancel of the channel's unfinished runs. The **Tag** control stays available on create, show, and edit during that lock. Saving Tags uses its own action, does not save the draft, and does not change `draft_revision`. Show, and any mode without `channel:write`, renders that control in display mode.

## 13. Management Audit

Persist a **Management Audit Event** for: channel create, identity edit, draft save, publish, activation change, delete, manual run enqueue, rerun enqueue, Global Variable manual delete, Webhook create, update, delete, and test, Email Account create, update, delete, and test, and every Source Mirror operation. A committed **Tag**-set change writes one event with resource type `channel`, action `tags.replace`, and the resulting Tag ids. An inline Tag create also writes the Tag create event. A replacement that does not change the set writes neither. A Tag change does not write a draft-save event. Each event records actor, **Instant**, resource, action, and result.

## 14. Non-Goals

1. Platform-derived incremental computation: automatic dirty-key derivation, grain checking, and fan-out thresholds.
2. An execution lock or platform serialization of runs.
3. Data Product catalog and non-Entity delivery targets.
4. Per-object authorization on Source Mirrors.
5. A platform event that calls a **Webhook** without an `action.webhook` node, or that sends mail without an `action.email` node.
6. Binary items, and network access other than the Webhook and Email nodes.
7. MCP tools for Data Channel or Source Mirrors.
8. Restoring source transaction boundaries at the target. A direct dataset write is one transaction for the whole set (§5.1). A Batch Read path commits each round on its own (§4.3).
9. Source-side triggers installed by the platform, and source writes other than a Data Channel SQL statement or the documented CDC signal and flush objects.
10. In-place retry of a Job, and Job retention.

## 15. References

- `docs/api-contracts-data-channel.md`
- `docs/api-contracts-webhooks.md`
- `docs/api-contracts-email-accounts.md`
- `docs/business-entity.md`
- `docs/business-entity-access.md`
- `docs/business-metadata.md`
- `docs/business-jobs.md`
- `docs/business-scheduled-tasks.md`
- `docs/business-system-parameters.md`
- `docs/business-login-auth.md`
- `docs/ui-console-record-form.md`
- `docs/glossary.md`
