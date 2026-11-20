# refraq Business Rules: Source Mirrors

## 1. Scope

This document defines Metadata-owned Source capture, shared full-column mirrors, transactional application, publication, authorized consumption, recovery and operational notification. The architecture is an approved design contract, not evidence that a runtime, engine version or deployment profile has passed qualification. Unknown mandatory evidence blocks admission, not implementation of these contracts.

Related boundaries:

- Source configuration and access: `docs/business-metadata.md`, `docs/api-contracts-sources.md`
- Mirror and integration interfaces: `docs/api-contracts-source-mirrors.md`
- Workflow runs and consumer checkpoints: `docs/business-data-channel.md`
- Package boundaries: `docs/backend-layout.md`, `docs/modules.md`
- Deployment configuration: `docs/env.md`

## 2. Ownership And Deployment

Metadata owns capture admission/control in `backend/metadata/capture/` and mirror registry, application, publication, reads, history and recovery in `backend/metadata/mirrors/`. Mirrors are not Business Entities. Metadata must not import Entity or Channel internals, even when both use the entity database. Composition binds external adapters and workflow-reference ports.

The deployer installs, upgrades and supervises the optional independent Connect/Kafka infrastructure and product-owned applier/control-agent process. API and Beat dispatch durable management intent; neither transports events nor spawns/supervises these processes. The PostgreSQL Connect + Kafka reference design uses one keyed topic and one partition per table, ordered per table, with no partition-count change within a capture generation. It makes no cross-table source-transaction atomicity promise. A standard sink is a bounded comparison candidate, not a second production backend.

The management database owns Source configuration, resource bindings, control commands, reference intents, recovery requests and history invalidation gates. Dedicated `source_mirror` and `source_mirror_state` schemas in the separate entity database own rows, fences, generations, delivery progress, log counters and reader pins. A Metadata bootstrap entry owns those schemas and guarded functions; it must not call unpublished Entity bootstrap helpers. A dedicated non-superuser owner owns the objects. Restricted applier and read-gateway logins have no unguarded DML or raw row-table grants; ordinary Entity/query roles have no mirror grants. Bootstrap administrative credentials are never used by serving processes.

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

Target `reader_pins` are unique by `(run_id, mirror_id)`. Lock pointer and generation, acquire/return the pin atomically, reject cleanup-pending generations, and reuse it for every page/node/restart-resume of that run. Channel stores pin references, not a second authority; recover by run id after response loss. A new rerun has a new run id and acquires its own pin. Release requires explicit terminal/non-resumable proof, not TTL or guessed liveness. Cleanup closes an unpinned retired generation to new pins under the same locks before recoverable drop. Uncertain readers retain pins.

Pins freeze generation identity, not mutable row contents or an MVCC snapshot. Use stable keyset paging; do not promise repeatable row values while live application continues. Reachable old complete generations may serve explicitly stale reads during replacement. Unreachable target or no complete generation fails retryably, never skips as success or advances a checkpoint. Continue/skip/fail freshness policy applies only to reachable complete data and annotates the run.

## 6. Data Authorization And Workflow Integration

`sources:data_read` grants every column of every admitted table in a Source only when the active User's Role contains it and Source Membership resolves to `viewer` or higher. Catalog visibility, query permissions, mirror management and publishing are not row grants. No per-table ACL is implied. Do not add new grants to existing custom Roles or `operator`; Super Admin follows the existing identity rule. `mirror:read` grants global Operations metadata; `mirror:write` grants lifecycle management, not data.

Manual run mint persists the current actor as mirror execution User. Unattended published settings require explicit `mirror_execution_user_id`, validated on publish/mint. Retry/resume retains that selected identity and revalidates current permissions. Never substitute System Identity, publisher, owner or capture credentials. Existing Entity/SQL execution identity rules remain unchanged.

Every row/log page and final checkpoint settlement rechecks active identity and current `sources:data_read` on the Source resolved from the immutable mirror binding. Disabled/deleted/missing identity or revoked grants returns no rows/images/progress. Caller-supplied Source ids are not authority.

Mirror-derived stored output, dataset, samples and retry caches carry Source provenance. Every response/reuse path requires current grants on all contributing Sources in addition to its ordinary Channel permission. Conservatively taint the entire mixed output with the union of input Sources; deny if provenance is unknown. Logs/errors contain no row values. Non-mirror output rules are unchanged. No mirror node may be exposed without this protection.

The minimum graph surface is `read.mirror` and `source.kind=mirror` on `read.changes`/`volume.changes_dataset`, with explicit stream kind. Publish confirmation returns actual `mirrors_to_open`. Commit published references and a deduplicated open outbox durably before asynchronous inclusion can succeed; reconcile the live published reference set. Draft preview/sample never starts capture. Refuse deletion with published references. Global Operations list/detail at `/console/mirrors` and `/console/mirrors/:id` presents Source/object first and runtime/profile/health/progress as evidence. Do not add mirror tabs to Source detail or a separate vendor configuration editor.

## 7. History Gates And Checkpoint Settlement

Mirror position is `(mirror_id, history_epoch, commit_seq, entry_seq)` with retained lower and committed upper bounds. Capture lineage and reader target generation are separate metadata. Channel extends its existing checkpoint/proposal records with stream kind, epoch and provenance; it does not create another CDC consumer cursor store. Entity positions remain backward compatible.

The management database owns a per-stream history gate containing epoch, retained lower bound and `available|invalidating` status. This is invalidation authority, not a cursor store. Every gap, destructive history break or purge locks the affected gates in sorted order and commits invalidating/new epoch/bounds before touching target history. A durable outbox idempotently completes target invalidation/cleanup; uncertainty leaves the gate closed. Multi-table loss closes every affected gate before replacements become eligible. Physical cleanup cannot bypass this protocol; retention can conservatively invalidate an epoch rather than silently accept a lost cursor.

For confirmed capture history loss, the target records the excluded capture lineages for each affected Mirror in the transaction that resets its history epoch. The fence covers the installed lineage and all generations allocated before the reset. Authority revision changes and later retention resets preserve the exclusion. Existing complete pointers and pins still serve stale rows. Unaffected Mirrors can continue writing, and a distinct capture lineage can write after normal admission and allocation.

Every page checks gate and target epoch/bounds; disagreement fails closed. Final successful Channel settlement locks all referenced management gates in the same management transaction as all checkpoint updates, rechecks epoch/bounds and authorization, and performs required bounded target validation while holding those locks. Invalidation uses the same locks: settlement linearizes before invalidation or rejects it, even after the last page. A check-then-call outside the checkpoint transaction is insufficient across two databases. Unavailable validation cannot commit. The validation linearization point is the successful bounded check under the gate locks; it cannot predict a later network outage.

Changes-arrived dispatch is explicit Channel opt-in and consumes only committed live entries. Baselines, recovery and publication do not dispatch. Reuse Channel's trigger mechanism, never a CDC-only trigger executor or an applier calling external actions. Gaps never reset cursors silently or replace history with a snapshot.

## 8. Conservative Recovery

Persist bounded transient attempts/next-attempt and jittered backoff within the approved capacity budget. Proven retained positions resume without identity reset; uncertain validity blocks/unknown, not an invented gap. Actual loss invalidates affected gates, allocates a new capture generation and builds an isolated empty replacement through the same writer/publication path. Empty replacement removes vanished rows on switch without visible mark-and-sweep or synthetic deletes. Preserve stale complete generations and pins.

Actual snapshot starts use the live Schedule Timezone/window, one table per Source and deduplicated operation ids. Persist postpone/manual mode. Audited run-now bypasses the window only, never ownership, readiness or resource gates. A timer does not promise to interrupt an uninterruptible scan.

Automatically resume verified unchanged schemas. Automatic add/widen requires explicitly qualified mapping, schema detection and backfill evidence. Unknown DDL, key changes, rename, drop/narrow and TRUNCATE block readiness pending authorization. No text fallback. PostgreSQL row events do not prove schema-only observation: require a DBA-approved fingerprint path with fresh evidence or block.

Automatic state-only workflow reconciliation requires a proven closed node allowlist limited to deterministic, authorized, idempotent key-based Entity state writes. Code, arbitrary SQL, opaque transforms, HTTP/email/Webhook and mixed graphs are excluded. Without a proven classifier there is no automatic post-gap workflow replay. Explicit reconciliation is an audited request bound to scope, epoch and Channel version, not historical events. The conservative default does not waive implementation/verification of classifier and reconciliation obligations. Mixed/external recovery needs an explicit authorized decision and is never replayed automatically.

## 9. Foundation Notifications

Foundation owns `backend/admin/notifications/`: one site Notification Channel with authenticated HTTPS primary and independently reachable fallback route, protected credential references, designated responder, tested delivery, outbox, bounded retries and visible delivery failure. Settings changes and test actions require `settings:write`; read requires `settings:read`. Redact endpoint URLs/credentials and enforce deployment-approved egress destinations, TLS verification and redirect restrictions. No provider ecosystem, user notification center or reuse of workflow Webhooks is implied. Foundation does not import Metadata or Channel.

Metadata emits typed redacted events after committed state transitions: `cdc.prerequisite_blocked`, `cdc.source_pressure`, `cdc.buffer_blocked`, `cdc.read_unavailable`, `cdc.disable_unconfirmed`, `cdc.history_gap`, `cdc.recovery_blocked`, `cdc.generation_published`. Include event id, scope/profile ids, owner/control/generation/epoch, observation Instant, expected/observed safe evidence, severity, pending/blocked state, responder and immediate action. Exclude rows, keys, source SQL, connection strings, secrets and raw connector exceptions. Publication means observed committed target pointer. Deduplicate by fault episode/type/scope and notify material transitions, not polling ticks.

Metadata owns `mirror_lag_alert_minutes`; it measures timestamped source/delivery/target progress with an approved observation-staleness cutoff. Unknown is not zero lag. Numeric capacity/lag configuration must be explicitly approved; this contract invents no seed or safe production threshold. Hidden locked undeletable `store_only` Scheduled Tasks evaluate evidence and deliver outboxes; they never supervise capture infrastructure. Failure escalates through the independent fallback, not recursively through the failed route. The management-independent safety alarm remains a separate deployment obligation.

## 10. MySQL Boundary

Metadata MySQL registration, Connector Spec/driver, introspection, type seeds, API/SpecTree expectations and guarded live queries are an explicit independent prerequisite for MySQL product integration. They are not incidental CDC fixtures. MySQL capture qualification separately proves binlog mode/row image/server identity/privileges, GTID-or-file lineage, retained positions, keys/types/schema, publication barriers, capacity and alarms on pinned versions/topology. PostgreSQL results do not qualify MySQL or block PostgreSQL implementation. Unsupported/unverified profiles remain unavailable.

## 11. Non-Goals

- Every intermediate source event, cross-table source transaction preservation, universal freshness/throughput/outage guarantees or automatic history sacrifice.
- Parallel production sink backends, per-table/row/column ACL machinery, mirror MCP tools or vendor configuration authoring.
- Automatic mixed/external-effect replay, Source-detail mirror tabs, notification provider ecosystems or runtime supervision by Beat.
