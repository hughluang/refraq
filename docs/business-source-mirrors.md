# refraq Business Rules: Source Mirrors

## 1. Scope

This document defines Metadata-owned Source capture, shared full-column mirrors, transactional application, publication, authorized deployment verification, recovery and operational notification. The architecture is an approved design contract, not evidence that a runtime, engine version or deployment profile has passed qualification. Unknown mandatory evidence blocks admission, not implementation of these contracts.

Related boundaries:

- Source configuration and access: `docs/business-metadata.md`, `docs/api-contracts-sources.md`
- Mirror management and target interfaces: `docs/api-contracts-source-mirrors.md`
- Package boundaries: `docs/backend-layout.md`, `docs/modules.md`
- Deployment configuration: `docs/env.md`

## 2. Ownership And Deployment

Metadata owns capture admission/control in `backend/metadata/capture/` and mirror registry, application, publication, reads, history and recovery in `backend/metadata/mirrors/`. Mirrors are not Business Entities. Metadata must not import Entity or Channel internals, even when both use the entity database. Composition binds external adapters.

The deployer installs, upgrades and supervises the optional independent Connect/Kafka infrastructure and product-owned applier/control-agent process. API and Beat dispatch durable management intent; neither transports events nor spawns/supervises these processes. The Connect + Kafka reference design, identical for every registered Source engine, uses one keyed topic and one partition per table, ordered per table, with no partition-count change within a capture generation. It makes no cross-table source-transaction atomicity promise. A standard sink is a bounded comparison candidate, not a second production backend.

The management database owns Source configuration, resource bindings, control commands, Mirror operations, recovery requests and history invalidation gates. Dedicated `source_mirror` and `source_mirror_state` schemas in the separate entity database own rows, fences, generations, delivery progress, log counters and reader pins. A Metadata bootstrap entry owns those schemas and guarded functions; it must not call unpublished Entity bootstrap helpers. A dedicated non-superuser owner owns the objects. Restricted applier and read-gateway logins have no unguarded DML or raw row-table grants; ordinary Entity/query roles have no mirror grants. Bootstrap administrative credentials are never used by serving processes.

## 3. Durable Control And Source Safety

| Record | Rule |
| --- | --- |
| `source_id`, immutable resource binding id | Reserve on first capture credential configuration under the Source row lock, before external allocation even when no external resource exists; preserve after uncertain allocation, rotation, clear, disable and last close |
| `capture_revision` | Credential revision only; preserve Source retain/replace/clear semantics |
| `control_revision` | Monotonic executable desired-state revision, independent of credential revision; covers scope, status, credential reference and snapshot configuration |
| `owner_epoch`, runtime instance id | Explicit fenced owner term; not a timed lease |
| `capture_generation` | Capture lineage; changes on actual discontinuity/rebaseline, not ordinary retry/rotation |
| `operation_id` | Durable control/snapshot identity, reused after uncertainty, restart and takeover |
| `applied_revision`, `observed_at`, `stop_ack` | Independently observed evidence stamped with owner, generation, control and credential revisions; HTTP acceptance is not evidence |

Source PATCH, resource allocation and deletion use the same Source lock ordering. Delete checks retained bindings before catalog or schedule destruction and returns `SOURCE_CAPTURE_RESOURCES_RETAINED` while bound, even if disabled. Disabled unbound Sources remain deletable. Retargeting bound resources returns `SOURCE_CAPTURE_SCOPE_LOCKED`. Ordinary lifecycle commands never drop a slot, offsets or delivery history. Explicit safe DBA/deployer release is outside ordinary Source deletion; no automatic release API is implied.

Management commits desired intent, a redacted audit and command outbox together. A private mutually authenticated TLS channel delivers generated allowlisted commands and protected credential references to an agent with a durable command journal and local per-Source execution lock. Repeated operation ids return the prior outcome; lower epochs/revisions are rejected. Connect REST handles lifecycle only; snapshots use a supported signal channel and separately correlated terminal evidence. Raw user connector settings are forbidden.

Takeover records pending intent, proves exclusion of the old task/agent (termination or demonstrated source/broker/network authority exclusion), installs the target fence, starts the authorized owner, then acknowledges applied state. Incrementing an integer alone does not exclude an old producer. Missing exclusion proof remains blocked/unknown. Every target application and publication transaction locks and verifies the installed fence. Credential authority applies to the running command/applier; accepted durable pre-rotation events remain replayable by a new authorized owner.

Credentials are encrypted at rest, delivered only privately to the agent, installed as revision-scoped protected local files/references, and excluded from projections, audit, argv and errors. Rotation acknowledgment requires installation and revocation checks, not REST success. A matching stop acknowledgment proves rejection of retired commands, stopped task/source session, no retired in-flight application, and the installed target fence. No timeout, reconnect or accepted disable substitutes for proof. Unreachable clear/disable stays pending with urgent deployer guidance.

Existing capture may continue through management loss only while credential/revocation validity, exclusive ownership, source pressure measurements and safe bounded delivery remain independently enforceable. Missing/stale mandatory measurements block locally. Pausing capture does not halt WAL/binlog growth; clearing a buffer does not reclaim source history.

The DBA and deployer approve a redacted profile sheet containing exact engine/connector/transport/target versions and artifacts, topology, scope, privileges, key/type mappings, ordering and barrier capabilities, workload, source-log/disk/scan/buffer warning and stop limits, observation freshness, intervention budgets and responsible primary/fallback alarm routes. There are no universal numeric defaults or outage-duration guarantees. Missing inspection rights mean `unknown`, not pass or failed prerequisites. Each readiness item records `pass|fail|unknown|not_applicable`, expected/observed values, observation Instant and remediation owner/action. Mandatory unknowns block admission. An independent actionable alarm must reach on-call during management outage before production capture; management notifications cannot replace that drill.

## 4. One Transactional Target Writer

Transport identity is `(runtime_cluster_id, topic_incarnation_id, partition, offset)` plus decoded Source/table/capture lineage. Topic recreation or repartitioning is an explicit discontinuity, never an offset reset in place. Keys, LSNs, timestamps and transaction ids are evidence, not unique delivery ids. Target delivery progress is authoritative; Kafka group offsets are restart hints, not consumer checkpoints.

One ordered microbatch transaction must:

1. Lock owner/control fence, generation state, per-partition progress and stream state in a stable order; reject unauthorized owners and generations.
2. Reject committed offsets before effects and require contiguous coverage, including explicitly classified control/tombstone records. Never skip a failed record.
3. Apply parameterized absolute upserts/deletes with quoted generated identifiers, supported typed/composite keys and qualified table identity. Preserve unchanged large-value placeholders; never write them as literal values.
4. Compare actual old/new values. Append one before/after record per effective live mutation. No-op upserts, absent-row deletes, baseline/recovery materialization and publication markers are non-dispatchable.
5. Commit rows, log entries, locked per-stream commit counter and delivery coverage atomically, then acknowledge transport.

A crash after commit before acknowledgment must replay without effects. Replayed source events at new transport offsets must also be harmless under qualified ordering, absolute application and effective-value comparison, including supported key changes. Unsupported envelopes block admission. A sequence allocation alone is not a committed visible prefix; the stream-state lock remains held through commit. Issue-independent writers, polling reconstruction and separate log transactions are forbidden.

## 5. Generations, Publication And Pins

There is one logical mirror per `(source_id, stable table identity)` with immutable mirror id. Generated table names encode mirror/generation ids. Preserve legal source column names within PostgreSQL's 63-byte limit, otherwise persist stable ordinal mappings. Persist schema fingerprint, native precision/Normalized Type mapping and admitted key specification. Declared keys need proven non-null uniqueness and usable update/delete identity; declarations alone do not admit a table.

Generation states are `requested -> building -> catching_up -> complete -> published -> retired`. Persist capture lineage separately from target generation, baseline operation id, source terminal evidence, expected partition set and target-applied boundary vector. Build first and replacement generations from empty isolated rows. Faults never move the published pointer.

Publication requires a quiesced, fenced handoff certificate: correlated successful table snapshot completion; connector-supported source/delivery checkpoint proof covering snapshot and preceding live records; controlled producer quiescence and durable source-checkpoint reconciliation; sealed end-offset vector for every expected partition; target commit through that vector; compatible schema/key, empty-table completion and current owner proof. Atomically switch the pointer under the target state locks, then resume capture with preserved positions. Quiescence consumes the approved source-history budget.

Paused REST status, a Kafka high-water mark, an out-of-band notification, a saved source offset or zero lag alone is insufficient. The profile must prove their ordering relation, including late data after a notification. Missing certificate capability keeps publication blocked; no timer or zero-lag fallback is allowed. Persist the certificate so takeover finishes or abandons the same operation idempotently.

Target `reader_pins` bind a reader id to a Mirror's published generation under the pointer and generation locks. An exact retry reuses the pin and cleanup closes an unpinned retired generation to new pins before dropping it. Release requires explicit terminal proof. Pins freeze generation identity. Live application can still change row contents between keyset pages. A reachable complete generation can serve stale rows during replacement.

## 6. Enablement And Operations

From a supported table in Catalog, a User with `metadata:read` on the table's Source and global `mirror:write` can set **Mirror synchronization** on or off. Metadata resolves the Source and stable table identity, then commits one logical Mirror, a durable Open operation and redacted audit in the management transaction. Repeat or concurrent requests for the same enabled table return the same Mirror and accepted Open operation. Re-enabling a disabled Mirror retains its identity and requests a new Open.

In Catalog, select **Choose table** to browse tables across authorized Sources. Filter by Source or search for a substring of the qualified table name. Operations offers the same picker. Each page contains up to ten visible tables. The synchronization action in a Catalog Object's Overview opens the same table drawer. Review the storage destination, last collected source size and estimated rows, then enable synchronization. The drawer identifies the accepted Open request immediately, including for a writer whose role grants lifecycle changes only. A reader can follow the Mirror from this drawer, including after synchronization has stopped.

Mirror detail shows the first-copy phase beside copy availability. Check the reported prerequisite, Source snapshot window or occupied slot when a table is waiting. The link on an occupied slot opens the holder. If the preceding scan has finished and its publication still holds up dispatch, the Console identifies that table separately. Returning restores the waiting table, and returning to the picker restores its filters, page and position. While the runtime scans, byte and percentage observations appear when measured. A completed scan can show 100% while the isolated generation is catching up and Open still awaits publication. The verified publication receipt establishes the first History epoch and makes the generation readable.

The Source owns capture credentials and the snapshot window. Explicitly enabled Mirrors define the desired table scope independently of Data Channels. Source enablement, credentials, profile readiness and proof of runtime authority still gate capture. Admission for a particular Open requires an allocation for that table revision under the applied Source authority. Catalog refresh records discovery. A supported table can be eligible to request enablement while capture is still blocked. The operator can enable a newly qualified table while another table continues delivery from its published copy.

Global `mirror:read` authorizes Operations metadata and a Catalog link for callers who can see the table. Operations shows desired state, the durable operation journal, a published generation when available and correlated snapshot progress when observed. Freshness stays unknown without an end-to-end measurement. The Mirror fault field remains null until there is durable evidence bound to the Mirror. Deployment verification uses restricted target access to check rows in the published generation and the corresponding committed live entry in `source_mirror_state.live_log`. User-authorized internal row and History reads check the active User's `sources:data_read` Role capability and viewer-or-higher Source Membership against the immutable Mirror binding.

Disable excludes the Mirror from desired scope and records a pending disable operation. A published copy can remain visible. Operations confirms stop after a signed Source stop or a table-specific exclusion under the current owner. The evidence identifies the exact excluded Mirror revision. Reconciliation that keeps capture running for other Mirrors leaves this stop pending when it lacks exclusion evidence for the disabled table. Superseding Source authority retires the confirmation. A later enable can supersede a pending disable. Missing upstream tables remain eligible for disable. Reopening requires a present table of a Source engine with a registered capture path.

Reopening restores the current source rows. Verified continuous table coverage permits a retained resume. A proven interval of missed capture starts a new History epoch and an empty replacement at the qualified partition boundary. The previous published copy remains available while the replacement builds. Snapshot rows carry baseline origin. Unknown coverage requires more evidence. Switching one table preserves other tables' identities and history.

Open the Mirror journal to follow a request across runtime checks. It groups entries by UTC day with the latest three visible. **Requests and receipts** shows the latest observation, continuity check, slot or window wait and available generation identifiers. A superseding enable or disable identifies the preceding request it replaced. If a reopened table still owns the slot through its abandoned scan, wait for the runtime to verify release before starting another copy.

An operator with `mirror:write` can retry a blocked check once a published History epoch exists. Each Retry records the result of its own check at the current control revision. An inconclusive result permits another Retry. Later proof for the same interrupted interval can resolve that check and a subsequent outstanding Retry. The Open completes when the retained copy is verified for resume or the replacement is published. An unpublished table can receive prerequisite rechecks directly. Its first Open awaits verified publication throughout.

To remove an incorrect or obsolete Mirror, turn off synchronization and select **Delete Mirror** in Catalog or Mirror detail. Review the Source and table before confirming. A Mirror proven never dispatched or allocated can be removed immediately. For a dispatched Mirror, wait for the matching stop receipt and release of its snapshot reservation and reader pins. A reader pin can refer to a retired generation. Deletion removes the Mirror's copies, change history and registration and records a deletion audit event. The upstream table and shared Source capture remain available. A new enrollment of the same table receives a new Mirror identity and first-copy Open.

### 6.1 Source Diagnostics

Operations readers with global `mirror:read` can navigate from a Mirror to an addressable Source Diagnostics scope. Replication, Connect production to Kafka, runtime consumption and target storage access are four independent shared checks. Each reports `healthy|failed|stale|unobserved`, observation time, validity and last success when known. Failures expose only a link-specific allowlisted code and recovery guidance. Expired failures become stale while retaining failure evidence. Neither table idleness nor a blocked table determines connection health.

Persist the last sixteen actual Source-check rounds with empty slots for missing observations. Preserve each round's four-link result as observed; current validity ages independently. For one to eight visible Sources, show each path with text health labels, hover/focus emphasis, and a four-check drawer. Narrow screens use vertical paths. Runtime disclosure previews three matching runtimes and eight sequential Source assignments with paging. Its round always covers the full assignment. Heartbeat and round completion are independent observations; a fresh heartbeat cannot refresh a stalled round. Navigation back restores the originating control and scroll position.

A measured event is a distinct accepted incremental Kafka row record (insert/update/delete), including effective no-ops. Exclude baseline/recovery snapshots, controls, tombstones and replay of the same transport identity. Committed batches contain at least one such accepted event. Target coverage, event counters and row effects commit in one transaction. Counters start at the instrumentation baseline; they are not historical Source totals.

Capture and write totals cover completed measured intervals. Sum available samples with N/M coverage, missing counts, oldest/newest observation times and per-table intervals; do not imply aligned windows or fill missing values with zero. Observed idle intervals can be zero. Kafka's default backlog metric is explicitly readable-position distance between authoritative committed target coverage and the read-committed stable boundary of the same Kafka partition incarnation. Offset gaps and control records prevent treating it as an event count. Exact pending events and bytes remain unavailable without a qualified observation. Bytes mean uncompressed serialized key and value plus UTF-8 header names and header value bytes for eligible incremental records. Do not substitute producer/network/storage counters or estimates, and do not require a second full-stream reader.

Mirror detail compares captured and committed events for one sample interval on a shared zero-based scale, and pending events separately. Preserve the catalog Source row estimate. Compare it only with a row-count sample identified by the currently published generation and timestamp; exclude superseded publications. Counts run asynchronously through a separate restricted target connection pool in short read-only transactions with statement and shorter lock timeouts. They never scan the Source, acquire lifecycle row locks, or pin generations. Ordinary target DML remains available; a publication/drop race or timeout yields an unavailable sample. The relation read lock can delay DDL only until this bounded transaction ends.

The last observed committed target transaction and measured end-to-end freshness are distinct. Freshness requires verified Source-to-Kafka-to-target checkpoint correlation for the published copy; heartbeat or successful connections cannot prove catch-up. Optional diagnostics ingestion is independent of capture safety and control: unavailable telemetry neither starts capture nor blocks its reconciliation. Deployment must approve validity and query budgets. Simulated receipts and prototype validity periods do not establish production observations.

### 6.2 Fleet Overview And Triage

Operations opens on Overview, with addressable Inventory, Diagnostics, and Deploy and connect views. Overview, Inventory, and Diagnostics share the entire fleet, one runtime group's assigned fleet Sources, or one Source as scope. Deploy and connect does not use that fleet scope; it selects one Source on the page. Inventory search, state, publication and cause filters refine Inventory only. The chart window refines throughput only. Catalog opened from a Source Overview starts with that Source. Management reads require global `mirror:read` and do not require Source data grants.

The fleet contains Sources with at least one registered Mirror, including stopped Mirrors. Additional runtime assignments remain visible as contextual assignments without entering fleet totals, Source health or rankings. Sources without a runtime remain discoverable in an Unassigned group. Source-table bytes and estimated rows describe registered Mirror tables using the latest collected catalog statistics, not every table in the Source. Sum measured values with sampled and missing counts; unknown values are not zero.

Overview shows Mirror and Source totals, source-table bytes in decimal units, estimated rows, published count and percentage, attention count, and four mutually exclusive lifecycle groups. A retained published copy still counts as published. Use the same classification and scope predicates for group totals and Inventory links. Confirmed disabled Mirrors are Stopped; pending stop confirmation and actionable table, Source prerequisite or snapshot-evidence blockers are Needs attention. Normal admission, snapshot-window, snapshot-slot and resume-check waits remain Copying or recovering. Established synchronization without a lifecycle blocker is Synchronizing. Connection health alone does not reclassify a table.

Initial and replacement copy progress sums measured scanned bytes over the source sizes of those same scanning or catching-up tables. Report sampled, missing and queued tables separately. A completed scan without byte evidence cannot contribute inferred bytes. No scan samples is an explicit evidence state.

Throughput compares CDC received and Mirror committed eligible incremental payload bytes per measured second, expressed in decimal MB/s. Both use the incremental byte definition in section 6.1 and exclude snapshots, controls, tombstones and replay. These are logical transport measurements, not physical Source reads or target storage writes. Received bytes require an independent qualified capture observation; committed bytes come from committed target counters. Preserve actual sampling intervals, observation times, sampled/missing coverage, measured idle zero and gaps. Keep at least 24 hours of bounded durable history across runtime restarts and authority changes. The 1-, 6- and 24-hour chart windows default to 6 hours and support inspection of both series at a UTC sample by pointer, touch and keyboard.

Rank up to eight Sources by source-table size or attention count, with search and paging for the remainder. Source selection scopes Overview. Selection from the attention ranking also sets the attention Inventory filter. Inventory uses pages of twelve and case-insensitive qualified-table or Mirror-ID search. Filter and sort the entire result set before paging. Default order is attention, copying or recovering, synchronizing, then stopped. Size and estimated-row sorts descend; table-name sort ascends. Unknown numeric values sort last, with stable identity ties.

Attention Inventory replaces estimated rows with the reason. Count cause facets after scope, state, publication and search, before the selected cause. Causes are schema, read permission, continuity, pending stop, Source prerequisite and snapshot evidence. Triage places blocked tables without a published copy first, then blocked tables with a copy, then pending stops; within blocked groups, the longest wait comes first. Clearing Inventory filters preserves scope.

Count each fleet Source once by its worst link in severity order failed, stale, unobserved, healthy. Above eight Sources, Diagnostics shows the health proportions of each of the four segments. Health totals find runtime groups and Sources by worst-link health; segment selection uses that segment's health. Sort runtime groups by affected Source count, then runtime identity; sort Sources by relevant health severity, then Source ID. Search groups and Sources and page each search in sets of twelve. A scoped Source search can expand to the full fleet while retaining its search and health criteria. Selecting a Source opens its four checks.

Direct links and browser Back and Forward preserve scope, filters, search, page, scroll and focused control. The Overview breadcrumb opens Overview directly. Narrow Inventory groups a table's phase, publication and reason together; topology becomes vertical. Health uses text or symbols as well as color, controls support keyboard use, and custom motion respects reduced motion.

### 6.3 Deployment Guide

Deploy and connect requires `mirror:read`. It reads the deployment projection, the selected Source's redacted access, and that Source's registered Mirror tables. It does not read or write connector configuration, credentials, or target SQL.

The administrator supplies the gateway origin, Connect origin, receipt observer origin, notification observer origin, Kafka bootstrap servers, runtime instance id, connector name, topic prefix, and configuration directory. None has a default. The values stay in the browser and are not sent to the API. The gateway origin is one of these values; the runtime reads it only from `signals_tls.origin` in its private file.

The page produces one instruction, shell commands for the Mirror target bootstrap and the Capture Runtime self-check and start, and a runtime configuration skeleton. Same-named access fields (`host`, `port`, `database`, `service_name`) and registered Mirror tables fill the skeleton. Unfilled values remain placeholders. The delivery manifest, the signed owner assignment, and the gateway stay deployment-owned. The page does not generate connector properties or source-database DDL.

A blocked readiness item links to the matching step: capture admission to the runtime self-check, an unqualified table to runtime configuration, a mirror permission or schema block to source prerequisites, and a continuity or incremental-snapshot block to the gateway. Other waits have no deployment link. The projection is a redacted reading of the contracts in `docs/env.md` §1.4 and this document. It is not qualification evidence.

## 7. History Gates

Mirror position is `(mirror_id, history_epoch, commit_seq, entry_seq)` with retained lower and committed upper bounds. Capture lineage and reader target generation are separate metadata.

The management database owns a per-stream history gate containing epoch, retained lower bound and `available|invalidating` status. This is invalidation authority, not a cursor store. Every gap, destructive history break or purge locks the affected gates in sorted order and commits invalidating/new epoch/bounds before touching target history. A durable outbox idempotently completes target invalidation/cleanup; uncertainty leaves the gate closed. Multi-table loss closes every affected gate before replacements become eligible. Physical cleanup cannot bypass this protocol; retention can conservatively invalidate an epoch rather than silently accept a lost cursor.

For confirmed capture history loss, the target records the excluded capture lineages for each affected Mirror in the transaction that resets its history epoch. The fence covers the installed lineage and all generations allocated before the reset. Authority revision changes and later retention resets preserve the exclusion. Existing complete pointers and pins still serve stale rows. Unaffected Mirrors can continue writing, and a distinct capture lineage can write after normal admission and allocation.

Every incremental page checks the management gate and target epoch and bounds. Disagreement denies the read. Only effective live changes are returned. A gap requires explicit recovery.

## 8. Conservative Recovery

Persist bounded transient attempts/next-attempt and jittered backoff within the approved capacity budget. Proven retained positions resume without identity reset; uncertain validity blocks/unknown, not an invented gap. Actual loss invalidates affected gates, allocates a new capture generation and builds an isolated empty replacement through the same writer/publication path. Empty replacement removes vanished rows on switch without visible mark-and-sweep or synthetic deletes. Preserve stale complete generations and pins.

Actual snapshot starts use the live Schedule Timezone/window, one table per Source and deduplicated operation ids. Persist postpone/manual mode. Audited run-now bypasses the window only, never ownership, readiness or resource gates. A timer does not promise to interrupt an uninterruptible scan.

Automatically resume verified unchanged schemas. Automatic add/widen requires explicitly qualified mapping, schema detection and backfill evidence. Unknown DDL, key changes, rename, drop/narrow and TRUNCATE block readiness pending authorization. No text fallback. Row events of any engine do not prove schema-only observation: require a DBA-approved fingerprint path with fresh evidence or block.

Recovery requests are audited against the current Mirror History epoch. The supported actions are retry, run now, postpone and manual.

## 9. Foundation Notifications

Foundation owns `backend/admin/notifications/`: one site Notification Channel with authenticated HTTPS primary and independently reachable fallback route, protected credential references, designated responder, tested delivery, outbox, bounded retries and visible delivery failure. Settings changes and test actions require `settings:write`; read requires `settings:read`. Redact endpoint URLs/credentials and enforce deployment-approved egress destinations, TLS verification and redirect restrictions. No provider ecosystem, user notification center or reuse of workflow Webhooks is implied. Foundation does not import Metadata or Channel.

Metadata emits typed redacted events after committed state transitions: `cdc.prerequisite_blocked`, `cdc.source_pressure`, `cdc.buffer_blocked`, `cdc.read_unavailable`, `cdc.disable_unconfirmed`, `cdc.history_gap`, `cdc.recovery_blocked`, `cdc.generation_published`. Include event id, scope/profile ids, owner/control/generation/epoch, observation Instant, expected/observed safe evidence, severity, pending/blocked state, responder and immediate action. Exclude rows, keys, source SQL, connection strings, secrets and raw connector exceptions. Publication means observed committed target pointer. Deduplicate by fault episode/type/scope and notify material transitions, not polling ticks.

A freshness measurement requires timestamped Source, delivery and target observations within the approved staleness limit. The management-independent safety alarm remains a separate deployment obligation.

## 10. Engine Capture Contracts

A Source engine can be mirrored when `backend/metadata/capture/engines.py` registers it. Registration needs a pinned capture profile, a Debezium envelope decoder, topic naming, a publication hand-off checkpoint confirmer and replacement baseline keys, all passing the shared conformance suite. Management code asks only whether a table is mirror-eligible and whether a Source holds the capture credential under consideration. It never names an engine. Registration is a contract of this repository, not qualification of any database version or topology. The registered engines are PostgreSQL, MySQL, SQL Server and Oracle.

Everything downstream of the decoder is engine-neutral: the `Record` contract, the single transactional target writer, generations, publication and History. A profile pins one explicit, DBA-approved scope, observes prerequisites through the capture identity and never creates publications, CDC instances, supplemental logging, signal tables or grants. A prerequisite that cannot be observed is unknown and blocks. An observed failure for one table blocks only that table's Open.

The Console **Capture Precheck** uses these observation queries and does not construct a pinned profile. Comparisons that need a pinned value, including the exact server version and `minimum_retention_seconds`, stay unjudged and return the observed value. An unreadable fact is unknown. The precheck does not admit capture.

| Engine | Source log position | Prerequisites a profile observes | Data collection id |
| --- | --- | --- | --- |
| PostgreSQL | WAL position and replication slot | Logical replication, slot, publication, replica identity and table read rights | `schema.table` |
| MySQL | Binlog file and position, plus the GTID set in GTID lineage mode, bound to the pinned server UUID | Row binlog with full row image, retention, replication privileges and keys | `database.table` |
| SQL Server | Commit and change LSN of the CDC log | Database CDC enabled, one capture instance per table covering every live column, agent running, cleanup retention and read rights | `database.schema.table` |
| Oracle | SCN and commit SCN of the mined redo, bounded by the flushed SCN | ARCHIVELOG mode, supplemental logging, archived redo retention, mining privileges and read rights | `pdb.schema.table` |

Every engine proves publication hand-off with a durable source checkpoint in a dedicated Kafka partition separate from data and notification partitions, bound to the connector name and topic prefix. The checkpoint carries the engine's log position and a witness that orders it after the previous checkpoint. The producer exclusion proves a source position at or beyond the witness. The signed evidence gateway (`/v1/capture/*`) is deployed outside this repository. This repository defines and validates the evidence. Missing or contradictory evidence keeps capture blocked, and no timer or lag estimate substitutes for it.

The delivery manifest `native_types` use the mirror target type vocabulary (`bigint`, `integer`, `smallint`, `boolean`, `text`, `uuid`, `date`, `bytea`, `jsonb`, `timestamp`, `timestamptz`). The deployer maps each engine's native column types into that vocabulary when generating the manifest. Temporal values of nanosecond precision are admitted only when exactly representable in microseconds. Any unmapped or lossy type blocks the table. MySQL and Oracle names are carried verbatim; Oracle identifiers are upper case.

Metadata registration, Connector Spec, introspection and type seeds for each engine remain prerequisites owned by `docs/business-metadata.md`; they are not created by capture.

## 11. Non-Goals

- Every intermediate source event, cross-table source transaction preservation, universal freshness/throughput/outage guarantees or automatic history sacrifice.
- Parallel production sink backends, per-table/row/column ACL machinery, mirror MCP tools or vendor configuration authoring.
- Data Channel consumption and workflow replay, Source-detail mirror tabs, notification provider ecosystems or runtime supervision by Beat.
