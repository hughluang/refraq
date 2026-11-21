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

The deployer installs, upgrades and supervises the optional independent Connect/Kafka infrastructure and product-owned applier/control-agent process. API and Beat dispatch durable management intent; neither transports events nor spawns/supervises these processes. The PostgreSQL Connect + Kafka reference design uses one keyed topic and one partition per table, ordered per table, with no partition-count change within a capture generation. It makes no cross-table source-transaction atomicity promise. A standard sink is a bounded comparison candidate, not a second production backend.

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

From a supported table in Catalog, a User with `metadata:read` on the table's Source and global `mirror:write` can choose **Enable mirror**. Metadata resolves the Source and stable table identity, then commits one logical Mirror, a durable Open operation and redacted audit in the management transaction. Repeat or concurrent requests for the same enabled table return the same Mirror and accepted Open operation. Re-enabling a disabled Mirror retains its identity and requests a new Open.

The Source owns capture credentials and the snapshot window. Explicitly enabled Mirrors define the desired table scope independently of Data Channels. Source enablement, credentials, profile readiness and proof of runtime authority still gate capture. Catalog refresh records discovery. A supported table can be eligible to request enablement while capture is still blocked.

Global `mirror:read` authorizes Operations metadata and a Catalog link for callers who can see the table. Operations shows desired state, the durable operation journal, a published generation when available and correlated snapshot progress when observed. Freshness stays unknown without an end-to-end measurement. The Mirror fault field remains null until there is durable evidence bound to the Mirror. Deployment verification uses restricted target access to check rows in the published generation and the corresponding committed live entry in `source_mirror_state.live_log`. User-authorized internal row and History reads check the active User's `sources:data_read` Role capability and viewer-or-higher Source Membership against the immutable Mirror binding.

Disable excludes the Mirror from desired scope and records a pending disable operation. A published copy can remain visible. The current Source stop must acknowledge the exact excluded Mirror revision under its assigned owner before Operations confirms stop. Reconciliation that keeps capture running for other Mirrors leaves this stop pending when it lacks exclusion evidence for the disabled table. Superseding Source authority retires the confirmation.

## 7. History Gates

Mirror position is `(mirror_id, history_epoch, commit_seq, entry_seq)` with retained lower and committed upper bounds. Capture lineage and reader target generation are separate metadata.

The management database owns a per-stream history gate containing epoch, retained lower bound and `available|invalidating` status. This is invalidation authority, not a cursor store. Every gap, destructive history break or purge locks the affected gates in sorted order and commits invalidating/new epoch/bounds before touching target history. A durable outbox idempotently completes target invalidation/cleanup; uncertainty leaves the gate closed. Multi-table loss closes every affected gate before replacements become eligible. Physical cleanup cannot bypass this protocol; retention can conservatively invalidate an epoch rather than silently accept a lost cursor.

For confirmed capture history loss, the target records the excluded capture lineages for each affected Mirror in the transaction that resets its history epoch. The fence covers the installed lineage and all generations allocated before the reset. Authority revision changes and later retention resets preserve the exclusion. Existing complete pointers and pins still serve stale rows. Unaffected Mirrors can continue writing, and a distinct capture lineage can write after normal admission and allocation.

Every incremental page checks the management gate and target epoch and bounds. Disagreement denies the read. Only effective live changes are returned. A gap requires explicit recovery.

## 8. Conservative Recovery

Persist bounded transient attempts/next-attempt and jittered backoff within the approved capacity budget. Proven retained positions resume without identity reset; uncertain validity blocks/unknown, not an invented gap. Actual loss invalidates affected gates, allocates a new capture generation and builds an isolated empty replacement through the same writer/publication path. Empty replacement removes vanished rows on switch without visible mark-and-sweep or synthetic deletes. Preserve stale complete generations and pins.

Actual snapshot starts use the live Schedule Timezone/window, one table per Source and deduplicated operation ids. Persist postpone/manual mode. Audited run-now bypasses the window only, never ownership, readiness or resource gates. A timer does not promise to interrupt an uninterruptible scan.

Automatically resume verified unchanged schemas. Automatic add/widen requires explicitly qualified mapping, schema detection and backfill evidence. Unknown DDL, key changes, rename, drop/narrow and TRUNCATE block readiness pending authorization. No text fallback. PostgreSQL row events do not prove schema-only observation: require a DBA-approved fingerprint path with fresh evidence or block.

Recovery requests are audited against the current Mirror History epoch. The supported actions are retry, run now, postpone and manual.

## 9. Foundation Notifications

Foundation owns `backend/admin/notifications/`: one site Notification Channel with authenticated HTTPS primary and independently reachable fallback route, protected credential references, designated responder, tested delivery, outbox, bounded retries and visible delivery failure. Settings changes and test actions require `settings:write`; read requires `settings:read`. Redact endpoint URLs/credentials and enforce deployment-approved egress destinations, TLS verification and redirect restrictions. No provider ecosystem, user notification center or reuse of workflow Webhooks is implied. Foundation does not import Metadata or Channel.

Metadata emits typed redacted events after committed state transitions: `cdc.prerequisite_blocked`, `cdc.source_pressure`, `cdc.buffer_blocked`, `cdc.read_unavailable`, `cdc.disable_unconfirmed`, `cdc.history_gap`, `cdc.recovery_blocked`, `cdc.generation_published`. Include event id, scope/profile ids, owner/control/generation/epoch, observation Instant, expected/observed safe evidence, severity, pending/blocked state, responder and immediate action. Exclude rows, keys, source SQL, connection strings, secrets and raw connector exceptions. Publication means observed committed target pointer. Deduplicate by fault episode/type/scope and notify material transitions, not polling ticks.

A freshness measurement requires timestamped Source, delivery and target observations within the approved staleness limit. The management-independent safety alarm remains a separate deployment obligation.

## 10. MySQL Boundary

Metadata MySQL registration, Connector Spec/driver, introspection, type seeds, API/SpecTree expectations and guarded live queries are an explicit independent prerequisite for MySQL product integration. They are not incidental CDC fixtures. MySQL capture qualification separately proves binlog mode/row image/server identity/privileges, GTID-or-file lineage, retained positions, keys/types/schema, publication barriers, capacity and alarms on pinned versions/topology. PostgreSQL results do not qualify MySQL or block PostgreSQL implementation. Unsupported/unverified profiles remain unavailable.

## 11. Non-Goals

- Every intermediate source event, cross-table source transaction preservation, universal freshness/throughput/outage guarantees or automatic history sacrifice.
- Parallel production sink backends, per-table/row/column ACL machinery, mirror MCP tools or vendor configuration authoring.
- Data Channel consumption and workflow replay, Source-detail mirror tabs, notification provider ecosystems or runtime supervision by Beat.
