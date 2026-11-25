# refraq API Contracts: Source Mirrors

## 1. Purpose

This document specifies Metadata Mirror management, deployment verification and runtime interfaces, and the Foundation Notification Channel interface. Mandatory unknown evidence keeps capture admission blocked.

Related boundaries:

- Invariants and qualification: `docs/business-source-mirrors.md`
- Sources: `docs/api-contracts-sources.md`
- Errors, pagination and time: `docs/conventions-errors.md`, `docs/conventions-pagination.md`, `docs/conventions-time.md`
- Published modules: `docs/backend-layout.md`

## 2. Management HTTP

All paths are API-relative, authenticated by Session or User PAT. Failures use Problem Details with request ids, and timestamps use UTC Instants. For endpoints with a request schema, unknown fields return `422 REQUEST_INVALID`. There is no public connector configuration, secret read, target SQL, source offset mutation or snapshot REST endpoint.

| Method And Path | Permission | Contract |
| --- | --- | --- |
| `PUT /objects/{object_id}/mirror` | `metadata:read` on Source and global `mirror:write` | Set `{enabled: boolean}` by Catalog id or locator. Returns 200 `{mirror: {enabled, can_enable, can_disable, mirror_id}, operation_id}`. Setting an eligible, unregistered table to off returns a null operation id. |
| `POST /objects/{object_id}/mirror` | `metadata:read` on Source and global `mirror:write` | Resolve the table by Catalog id or locator. Send no body. Returns 202 after durable acceptance. A reader receives `{mirror: Mirror, operation_id}`. A write-only caller receives `{enabled, operation_id}` |
| `GET /mirrors` | `mirror:read` | Offset Page, `limit` default 100/max 500, `offset` default 0; optional `source_id`, `status`, `q` literal Source/object-name substring; order Source key, qualified table, mirror id |
| `GET /mirrors/{id}` | `mirror:read` | `{mirror: Mirror}` including redacted evidence, and a top-level `can_enable` flag reflecting current table eligibility |
| `PATCH /mirrors/{id}` | `mirror:write` | `{enabled: boolean}` durable intent. Returns `{mirror: Mirror, operation_id}` to a reader or `{enabled, operation_id}` to a write-only caller |
| `GET /mirror-diagnostics` | `mirror:read` | Operational observations for optional `source_id`/`runtime_id`; nonnegative `source_offset`, `runtime_offset`, `assignment_offset` default 0. Preview sizes 8/3/8; assignments describe the entire runtime, including Sources outside the selected scope. |
| `GET /mirror-setup` | `mirror:read` | Deployment guide projection. No Source id, no secrets, and no generated connector properties. |
| `GET /mirrors/{id}/measurements` | `mirror:read` | Current scoped interval sample, catalog estimate, current-publication row sample, and runtime/check context. |
| `GET /mirrors/{id}/journal` | `mirror:read` | Newest first. Pass `before` from `next_cursor` and an optional `limit` (1 to 100, default 20). Returns `{items, next_cursor}`. |
| `DELETE /mirrors/{id}` | `mirror:write` | Delete a disabled Mirror. An optional `expected_control_revision` guards an earlier confirmation. Returns 204 after cleanup or 202 with the pending operation. |
| `DELETE /objects/{object_id}/mirror` | `metadata:read` on Source and global `mirror:write` | Supply the disabled Catalog setting's opaque `delete_token` as a query parameter. It binds confirmation to the selected enrollment and revision. Returns the same deletion outcome as Mirror detail. |
| `POST /mirrors/{id}/recovery-requests` | `mirror:write` | `{action: retry\|run_now\|postpone\|manual, expected_history_epoch, reason?}` scoped to the path Mirror. Run now, postpone and manual require a nonblank reason. Returns 202 `{operation_id, state: pending}` |
| `GET /sources/{id}/capture-status` | `sources:read` on Source | `{source_id, profile_id, availability, control, readiness, operations}`; no secrets; availability `disabled\|available\|degraded\|unknown` distinct from Source configuration `capture_state` |

`Mirror` includes `id`, immutable `source_id`/table binding, qualified table name, `enabled`, `status`, `published_generation_id` (nullable), `capture_generation`, `history_epoch`, `retained_lower_bound`, `committed_upper_bound`, `control`, `progress`, `profile`, `readiness`, `fault` (currently null), and `operations`. Status is `waiting|snapshotting|catching_up|ready|stale|rebuilding|paused|needs_attention|disable_pending|unknown|disabled|source_fault`. A correlated snapshot notification projects `progress` with `stage` (scan or catching_up), `generation_id`, `notification_offset` and nullable `observed_at`. Until the current allocation has a verified notification, progress is null. `profile.qualification` reports `qualified` or `unverified`. Readiness items have `key`, `result` (`pass|fail|unknown|not_applicable`), `expected`, `observed`, `observed_at`, `owner`, `action`. Unknown required items block admission.

Mirror detail includes the storage schema, latest source size and row estimate, and nullable `snapshot_slot_holder` with the holder's Mirror ID and qualified table. A nullable `publication_wait` identifies the preceding table when its scan has released the slot and its verified publication is still required before dispatch. Readiness reports this dependency as `publication_pending`. The `progress` fields `scanned_bytes` and `scan_percent` are nullable. Nullable `bytes_observed_at` and `byte_notification_offset` identify the last accepted byte measurement independently of the lifecycle notification. Missing or regressing counters preserve the prior byte observation. Historical counters without recorded provenance keep these two fields null. A correlated table scan completion receipt sets `scan_complete` and establishes 100% even when the runtime has no byte counter. The Open can remain pending through catch-up. Verified publication establishes the first publicly readable generation and History epoch.

Detail, list items and the list's status filter use the same current lifecycle evidence. The SQL store updates an indexed effective status in the transaction that records its evidence. It uses the same filter for the count and the ordered page. A passing admission for a pending Open requires the current table allocation under the applied Source command, matching the Mirror revision and capture generation. A blocked snapshot correlated to the current Open reports `needs_attention` and failed `incremental_snapshot_blocked` readiness while retaining its snapshot reservation. Capture admission can remain passed alongside that failure.

The Catalog PUT and the compatible enable-only POST each accept one table. The global `mirror:write` check runs before Catalog object lookup. A missing permission returns `403 AUTH_FORBIDDEN`. An unknown or inaccessible Catalog object returns `404 CATALOG_OBJECT_NOT_FOUND`. A visible object that fails Mirror table eligibility returns `404 MIRROR_NOT_FOUND`. Concurrent or repeated enables of the same table converge on the same Mirror and accepted Open operation. Reopening a disabled Mirror retains its identity. A 202 records desired state. Snapshot progress and the published pointer depend on subsequent runtime evidence.

`control` exposes `control_revision`, `credential_revision`, `owner_epoch`, `runtime_instance_id`, `applied_revision`, `observed_at` and nullable `stop_ack`. The redacted acknowledgment contains `operation_id` for the Mirror disable, `source_operation_id` for the observed Source stop, and `observed_at`. Confirmation requires a disabled Mirror, matching current and applied revisions and the matching applied disable journal entry. Until current stop evidence is accepted, a requested disable reports `disable_pending`. A qualified runtime may acknowledge the exclusion of an individual table while other tables are active. It binds independent connector exclusion, drained delivery and target fence evidence to the exact table revision. The published generation is retained.

Detail embeds the latest three journal events. Each records its category (request or observation), operation, revision, UTC time and applicable epoch and generation. Request outcomes can refer to a superseding request or the operation that supplied conclusive evidence. Detail exposes `latest_request`, `latest_observation`, `continuity_check`, `blocker`, `can_retry`, `allocated_generation_id` and `published_at`. Unmeasured timestamps are null. A Console Retry supplies both the expected control revision and History epoch. An inconclusive recheck completes that Retry and leaves its Open awaiting evidence.

A never-dispatched Mirror can be removed using durable Management evidence alone. Once a command or allocation may have reached the runtime, deletion requires the matching stop, released snapshot reservation and an available restricted target that can exclude all reader pins. Reapply the administrative Mirror target bootstrap to install the cleanup functions on existing targets. An accepted deletion exposes `deletion_operation_id` until cleanup is complete. Repeating the request resumes the same operation.

Operations include durable id, kind, revision, state (`pending|applied|superseded`), request time, evidence references and safe fault code. Recovery admission compares the expected History epoch and audits accepted intent transactionally. A retry cannot authorize destructive change. Reopening a published generation requires current target pointer, owner, fence, certificate and history observations before its open is applied.

Global `mirror:read` authorizes management reads. Global `mirror:write` authorizes lifecycle actions. User-authorized target reads require `sources:data_read` and viewer-or-higher Source Membership. Hidden data bindings return `MIRROR_NOT_FOUND`. A held Source level without the data permission returns `AUTH_FORBIDDEN`. The HTTP surface exposes management metadata. Deployment verification reads the target rows and committed History through restricted paths.

### 2.1 Diagnostic Read Shapes

`GET /mirror-diagnostics` returns `observed_at`, `mirror_count`, `source_count`, `sources`, `matching_sources`, `source_offset`, `runtimes`, `runtime_offset`, `assignment_offset`, `total_runtimes`, `summary`, `states`, `intervals` and `link_counts`. A Source has `id`, `name`, `runtime_instance_id`, `health`, four `checks`, sixteen nullable `history` slots, `last_checked_at` and `end_of_cycle_wait_seconds`. Checks carry `link`, `health`, nullable `observed_at`, `valid_until`, `last_success_at`, `failure_at` and `error_code`. History rounds have `id`, `at`, `checks` and a fixed historical `health`. An unknown Source returns `404 MIRROR_NOT_FOUND`; an assigned Source can have zero Mirrors.

Each runtime has `id`, nullable heartbeat and cycle observations, independent `heartbeat_health`/`cycle_health`, `end_of_cycle_wait_seconds`, `assignment_stale`, a page of sequential `source_ids`, its `assignment_offset` and full `total_sources`. An offset beyond a shorter runtime assignment returns that runtime's first page. Cycle includes `started_at`, nullable `completed_at`/`duration_seconds`, and retained `last_completed_at`/`last_duration_seconds` while a new round is in progress. Observations carry `observed_at` and `valid_until`.

Summary keys are `captured_events`, `committed_events`, `committed_batches`, `pending_events`, `pending_bytes` and `position_lag`. Each has nullable `value`, `sampled`, `missing`, nullable `interval_start`/`interval_end` and `oldest_observation`/`newest_observation`. Only current, valid samples contribute. `states` counts `active|idle|blocked|unobserved` separately for capture/write; expired samples are unobserved for these counts. `intervals` retains each Mirror's own window, time and stale flag. `link_counts` counts each of the four health states across the scope. The optional `q` literal Source-name/id filter affects the Source preview only, not scope totals.

`GET /mirrors/{id}/measurements` returns `mirror_id`, `source_id`, nullable `sample`/`row_sample`, `row_sample_stale`, `estimated_rows`, `published_generation_id`, `runtime_instance_id`, `last_source_check_at` and `end_of_cycle_wait_seconds`. An interval sample carries Mirror/capture/target generation identity, interval start/end, observation/validity, `stale`, the six nullable metrics, `capture_state`/`write_state`, nullable `last_target_commit_at`, `freshness_ms` and `checkpoint_ref`. A row sample has `generation_id`, `row_count`, observation and validity; publication mismatch returns null. Samples require the current binding, owner, control/credential revisions and capture lineage. The target generation must be published or currently allocated. Freshness for an unpublished allocation is null. Raw authorities, connector responses, payloads and secrets are excluded from the read projection.

These reads require global Operations permission only; Source data grants are not required. Read failure must retain an earlier UI snapshot as stale, while authorization failure clears it. No public write endpoint accepts observations.

### 2.2 Fleet Reads

All fleet endpoints require global `mirror:read`. Fleet Sources own at least one registered Mirror, including stopped Mirrors. Contextual runtime assignments with zero Mirrors do not expand that universe. `source_id` selects one Source; `runtime_id` selects the group's fleet Sources, with `unassigned` identifying Sources without a runtime. Scope applies to counts before Inventory refinements or chart windows.

| Method And Path | Query And Response |
| --- | --- |
| `GET /mirror-fleet` | Optional `source_id`, `runtime_id`, `rank=size|attention` (default `size`). Returns `observed_at`, `mirror_count`, `source_count`, `source_size`, `estimated_rows`, `published_count`, nullable `published_percent`, `attention_count`, `states`, `snapshot`, `health`, `segments`, up to eight `ranking` Sources and `ranking_total` |
| `GET /mirror-fleet/sources` | Scope plus optional literal Source-name/id `q`, `health=failed|stale|unobserved|healthy`, `segment=replication|production|consumption|storage`, and Offset Page `limit`/`offset` (default 12, max 100). Returns Source fleet projections ordered by relevant health severity, then Source ID |
| `GET /mirror-fleet/runtimes` | Scope plus optional literal runtime-ID `q`, health/segment filters, and Offset Page `limit`/`offset` (default 12, max 100). Returns runtime groups ordered by affected Source count descending, then runtime identity. Includes an Unassigned group when applicable |
| `GET /mirrors` | Existing Source/status/search parameters plus `runtime_id`, `grouped_state=synchronizing|copying|attention|stopped`, `published_only`, `cause=schema|permission|continuity|pending_stop|source_prerequisite|snapshot_evidence`, `sort=priority|size|rows|table`. Returns the Offset Page envelope and `cause_counts`. Console pages contain 12 items. Literal case-insensitive `q` includes qualified table and Mirror ID |

`source_size` and `estimated_rows` have nullable `value`, `sampled` and `missing`; values sum latest collected statistics for registered Mirror tables only. Unknown statistics do not contribute zero. Percentages are null when their denominator is zero. `states` maps each of the four groups to `count` and nullable `percent`. Classification is shared with Inventory predicates. `snapshot` has nullable `scanned_bytes`/`source_size_bytes`, `sampled`, `missing` and `queued`; byte totals include only observed scans/catch-ups and the source sizes of those same tables.

`health` counts each Source once by its worst link in failed, stale, unobserved, healthy order. `segments` contains independent health counts for each of the four links. These counts describe the selected scope, not the visible page or an Inventory filter. Source projections contain `id`, `name`, nullable `runtime_instance_id`, worst-link `health`, `segment_health`, `mirror_count`, `attention_count`, `source_size` and `estimated_rows`. A segment filter evaluates that segment rather than the Source's worst link.

Runtime projections contain `id`, nullable `runtime_instance_id`, `source_count`, `affected_source_count` and a scalar worst-link `health`. `source_count` includes every fleet Source in the scoped group before health filtering. Without an explicit `health`, `affected_source_count` counts Sources whose relevant health is not healthy; with `health`, it counts Sources matching that value, including healthy Sources when `health=healthy`. Groups with no matches are omitted only when `health` is explicit. The relevant health is the selected segment's health when `segment` is present, otherwise the Source's worst-link health; the runtime's scalar `health` is the worst of those values across its scoped Sources.

Inventory items add `grouped_state`, nullable `attention_cause`/`attention_since`, nullable `source_size_bytes` and `estimated_rows`. `cause_counts` describes scope, search, state and publication predicates before the selected cause. Priority order is attention, copying, synchronizing, stopped. Attention sorts blocked unpublished Mirrors, blocked published Mirrors, then pending stops; blocked groups sort longest wait first. Numeric sorts descend with unknowns last; table sort ascends. Every order has an identity tie-breaker. Filtering, sorting, total and paging apply to the entire set.

### 2.3 Throughput History

`GET /mirror-throughput` requires `mirror:read`. It accepts optional `source_id`/`runtime_id` and `hours=1|6|24` (default 6), which changes only the chart window. The response has `observed_at`, `window_start`, `window_end`, `hours`, `unit: MB/s`, `mirror_count`, `source_count` and bounded `points`. Each point has `at`, `bucket_start`, `received` and `committed`. Each rate has nullable `value`, `sampled`, `missing`, nullable `interval_start`/`interval_end`, nullable `oldest_observation`/`newest_observation`, and `measured_seconds`.

Rates compare measured eligible incremental payload bytes per measured second, divided by 1,000,000. The signed interval sample accepts nullable `captured_bytes` and `committed_bytes`; both use the uncompressed key/value/header byte definition in section 2.1. Snapshots, control records, tombstones and replay are excluded. Native committed byte deltas require complete target byte coverage at both interval boundaries; counter or lineage resets produce an unavailable interval. Captured bytes require an independent qualified capture observation. Neither field derives from event counts, Source size, snapshot progress, Kafka position distance or physical I/O.

Durable bounded history retains at least 24 hours of completed measurement intervals, including their Source/runtime and generation lineage. A later authority or publication change does not erase valid historical observations. Sum measured per-Mirror rates with their actual intervals and explicit coverage. Missing series values remain null; a measured idle interval is zero. The Console labels both series accurately and inspects chart samples in UTC.

### 2.4 Deployment Guide

`GET /mirror-setup` requires `mirror:read` and takes no parameters. The body is a redacted reading of the capture and mirror-target contracts: connector version, site-input tokens and kinds, step ids, numeric bounds, validation patterns, target schema version, schemas, roles, `REFRAQ_MIRROR_TARGET` field names, bootstrap and runtime command argv, runtime configuration keys with placeholders, exit codes, reported fault codes, gateway and Connect paths, mandatory readiness checks, and one source-entry skeleton per registered engine. Placeholders use `<TOKEN>` form. The response contains no Source access, credentials, connector properties, or DDL. The Console fills same-named redacted access fields and registered tables in the browser. See `docs/business-source-mirrors.md` §6.3 and `docs/env.md` §1.4.

## 3. Management And Runtime Interfaces

The following entry points serve Metadata, runtime and deployment verification. Cross-package imports follow `docs/backend-layout.md`. Data transfer objects are immutable values; credentials are excluded. Composition binds external delivery, secret, target and notification adapters.

| Module | Callable Contract And Transaction Boundary |
| --- | --- |
| `backend.metadata.mirrors.service` | `enable_for_object(object_id, *, actor_user_id, actor_token_id=None)` accepts the already authorized canonical Catalog id and commits registry, Open operation and audit. `read_published_scope(session, source_id)` reads the registry under the caller’s Source lock |
| `backend.metadata.mirrors.history` | `capture_bound(*, mirror_id, execution_user_id)` returns epoch and bounds. `read_incremental(*, mirror_id, execution_user_id, after, through, limit)` checks current authorization and the gate and returns a bounded page. `invalidate_history(session, *, mirror_ids, reason, operation_id)` closes gates and enqueues target invalidation before target mutation |
| `backend.metadata.mirrors.application` | Runtime-only `apply_batch(*, authority, generation_id, partition_identity, records)` uses the sole fenced target transaction; returns committed coverage after commit |
| `backend.metadata.mirrors.publication` | Runtime/recovery `publish_generation(*, operation_id, authority, generation_id, certificate)` validates persisted complete certificate and atomically switches target pointer; reconciliation reports observed commit, not accepted intent |
| `backend.metadata.mirrors.bootstrap` | Administrative process `python -m backend.metadata.mirrors.bootstrap` idempotently installs Metadata-owned target schemas, roles, restricted functions and version marker; serving startup validates marker/roles and refuses mismatches rather than doing DDL |
| `backend.metadata.capture.runtime` | Independent product process entry `python -m backend.metadata.capture.runtime`, assembled with allowlisted Connect/signal/Kafka/secret/target adapters; durable command consumer and applier, not a Job or API child |
| `backend.admin.notifications.service` | `enqueue_notification(session, *, event_id, event_type, scope, evidence, severity, responder, safe_action)` writes redacted deduplicated notification intent within caller management transaction; Foundation never imports product packages |

Bootstrap identities are `refraq_mirror_owner` (`NOLOGIN NOSUPERUSER NOBYPASSRLS`, object/function owner), `refraq_mirror_applier` (restricted LOGIN, guarded apply/publication execution only) and `refraq_mirror_gateway` (restricted LOGIN for authorized read/pin functions, no direct row-table grants). None inherits Entity/query owner privileges. Guarded functions use a fixed safe search path and revoke PUBLIC execution. Administrative bootstrap alone may assume the owner role; the applier cannot assume it. Gateway authorization is established by the product service after current Source grant checks, not a caller-supplied User/Source id passed directly to arbitrary SQL. The target pool and secret settings in `docs/env.md` preserve these distinct identities.

`authority` contains Source/resource binding, owner epoch/runtime instance, control/credential revision and capture generation. `partition_identity` contains runtime cluster id, topic incarnation id and partition; records contain offset, typed key/schema mapping, operation origin and table/capture lineage. Offsets are contiguous coverage, including classified non-row records. Supported operations are absolute upsert/delete; unsupported key/type/envelope blocks before progress. Batch rollback rolls back rows/log/progress together. Only current installed task authority is accepted; historical record credential age is not a replay rejection rule.

`certificate` contains operation/table/capture/target generation ids, owner/control stamps, successful correlated source completion evidence, producer quiescence/exclusion evidence, reconciled durable source checkpoint, exact expected partition set/end-offset vector, target applied coverage, schema/key fingerprint and empty-table proof when applicable. Persist it before pointer change and recover it by operation id. If the selected profile cannot prove ordered source-to-delivery coverage, reject publication; never synthesize a certificate from lag or elapsed time.

The guarded first switch requires target coverage at the exact certified boundary. An exact retry under the current fence confirms publication while the pointer still names that published generation and target coverage is at or beyond the certified boundary. A superseded pointer or contradictory publication state blocks reconciliation.

Initial open reconciliation requires the committed target pointer, matching certificate and current history epoch under a target observation guard. The guard stays held through the Management transaction that records the generation, initializes the history gate and marks the open applied. An exact retry can confirm its durable Management receipt after the pointer or epoch changes. A historical receipt provides no current pointer or readiness guarantee.

Qualified writers serialize changes to the target pointer, history epoch, and authority against the same Management Source and history fences through target commit. This serialization also covers loss of the target observation session, which releases its database locks. A deployment with independent writers requires a durable target barrier that stays in force through the matching Management commit.

Management consumes `history_loss` receipts through `invalidate_lost_history(text,jsonb,boolean)` on the restricted target applier. The target commits the epoch reset, per-Mirror capture lineage exclusion, and an immutable receipt together under the same stream locks used by allocation, apply, certificate persistence, and publication. An exact replay acknowledges the original transition after a lost reply. The legacy `invalidate_history(text,jsonb)` entry point continues to handle ordinary retention and preserves existing exclusions.

Upgrade requires rerunning the administrative target bootstrap and replacing old Management receipt consumers before loss processing resumes. A missing loss function leaves a pending Management gate invalidating. An existing unfenced target receipt cannot acknowledge a loss. Previously applied legacy losses require explicit qualification of the target epoch and old writer exclusion, or remediation, before reuse. An applied Management receipt alone cannot establish a clean epoch.

A position serializes as `{mirror_id, history_epoch, commit_seq, entry_seq}`. `commit_seq` is a locked committed-prefix counter, not a database sequence reservation; `entry_seq` orders entries within that commit. An entry includes position, source/capture/target lineage, `origin: live`, operation, typed key, before/after images. Only effective live entries appear in incremental pages. `through` fixes an upper committed bound; each page checks retained lower bound and matching gate/target epoch. Cursor tokens cannot bypass authorization.

## 4. Signed Capture Scope

The internal signed `published_scope` contains each registered Mirror’s immutable table binding, `mirror_id`, `mirror_revision`, and `included` from its explicit desired state. A disabled entry remains in scope with `included: false` so the runtime can prove exclusion for that revision. Source admission and runtime evidence govern execution. The deployment profile lists the tables the DBA has qualified. The connector and applier run the enabled subset of that inventory. The registry includes a newly enabled sibling as soon as Open is accepted. When the current connector is completing an in-flight first copy, it keeps its existing signed command through publication. The runtime then expands the connector scope to include the queued table. An exclusion or revision change to a configured table takes effect immediately. An ordinary takeover reserves and signs the desired registry at the time of reservation. A lost gateway response can be retried with that request while the previous authority still matches. Promotion requires exclusion and target-fence verification for the reserved inventory. If the registry changed during takeover, the promotion transaction also writes the superseding command for the current inventory. Only an active snapshot bound to that excluded authority and a verified target fence can release its reservation during takeover.

The private scope-fence observation binds the current Source command, scope and per-table target fence receipts. A running observation may carry `table_exclusions` with the excluded scope entry and the connector exclusion, delivery drain and target fence references. The runtime verifies signatures, freshness and the exact revisions before recording exclusions.

An interrupted first-copy scope fence may carry `inconclusive_tables`, keyed by Mirror ID with a signed evidence reference per table. This holds the first Open at its current revision until the observer supplies a verified partition in `table_boundaries`. A new Open also waits for an abandoned snapshot reservation on the same Source. The runtime accepts the original scan's authenticated terminal notifications, a matching terminal Source stop, or proven takeover exclusion as release evidence.

Retained resume decisions bind the original published generation and current Source scope. A continuous decision requires authorization for the current target fence. A gap decision identifies the qualified data partition and last skipped offset for an empty replacement. Unknown continuity leaves that table pending. Table-gap invalidation advances only the affected history epoch and retires its old writers before the new generation receives records. The normal capture loop reconciles publication after the independent deployment verifier stores a completion certificate in the target.

Capture engines are registered in `backend.metadata.capture.engines`. Each registration supplies the profile, decoder, topic name, publication checkpoint confirmer and replacement baseline keys of one Source engine. The runtime selects the engine from the single `<engine>_profile` key of a Source entry. Replacement candidate baselines carry exactly the engine's baseline keys plus `connect`, `kafka` and `task_running`. The per-engine log position and checkpoint evidence are defined in `docs/business-source-mirrors.md` §10 and validated by `backend.metadata.capture.checkpoints`. `Mirror` responses include `source_engine`, the registered engine code of the Source.

## 5. Foundation Notification HTTP

| Method And Path | Permission | Contract |
| --- | --- | --- |
| `GET /settings/notification-channel` | `settings:read` | `{channel: {configured, primary_configured, fallback_configured, responder, delivery_state, last_test_at, last_fault_code}}`; no URLs/credentials |
| `PUT /settings/notification-channel` | `settings:write` | `{primary: {https_url, credential}, fallback: {https_url, credential}, responder}`; credentials write-only, whole route stored encrypted; returns redacted channel projection; routes must be distinct and approved for independent failure handling |
| `POST /settings/notification-channel/test` | `settings:write` | Enqueue explicit redacted route test, return 202 `{operation_id, state: pending}`; eventual primary/fallback outcomes visible in `delivery_state`, never report queued as delivered |

Credential is `{header_name, secret}` used only for authenticated HTTPS delivery; reject hop-by-hop/reserved header names, insecure destinations and redirects outside approved egress policy. Updates replace full route configuration and write redacted audit atomically. Delivery uses event id as an idempotency key and records attempts/next-attempt/final failure; bounded profile-approved retry/fallback is independent from workflow actions. A route test must exercise both paths before production admission. Endpoint tests never contain source data. Notification errors use `NOTIFICATION_ROUTE_INVALID` (422), `NOTIFICATION_DELIVERY_UNCONFIRMED` (409) for attempted admission without verified routes; asynchronous delivery failure is visible state, not a false HTTP success certificate.

## 6. Errors And Audit

| Code | HTTP | Meaning |
| --- | --- | --- |
| `MIRROR_NOT_FOUND` | 404 | Unknown id or hidden data binding |
| `AUTH_FORBIDDEN` | 403 | Missing capability, missing current data grant or inactive User |
| `MIRROR_READ_UNAVAILABLE` | 503 | Target unreachable or no complete eligible generation; retryable, no rows/progress |
| `MIRROR_HISTORY_INVALID` | 409 | Epoch, retained bound or management/target gate mismatch; no implicit reset |
| `MIRROR_CONTROL_CONFLICT` | 409 | Stale expected epoch/control, contradictory command or unproven owner exclusion |
| `MIRROR_PUBLICATION_BLOCKED` | 409 | Missing/invalid completion certificate, schema/key or coverage proof |
| `MIRROR_IN_USE` | 409 | Disable synchronization before deleting the Mirror |
| `MIRROR_STOP_UNCONFIRMED` | 409 | The current stop or target fence remains unverified |
| `MIRROR_SNAPSHOT_IN_USE` | 409 | The snapshot reservation still needs to be released |
| `MIRROR_READERS_IN_USE` | 409 | A reader retains a pin on this Mirror |
| `MIRROR_RECOVERY_AUTHORIZATION_REQUIRED` | 409 | Unsafe/unknown schema or non-allowlisted recovery requires explicit decision |
| `SOURCE_CAPTURE_RESOURCES_RETAINED` | 409 | Source has retained capture binding; delete refused before cascades |

Audit `mirror.enable`, `mirror.disable`, `mirror.delete`, `mirror.recovery_request` and `notification_channel.replace|test` with actor, Instant, operation and scope ids, reason and allowlisted state. Automatic events use typed notification envelopes.

## 7. Non-Goals

- Public row SQL, raw connector settings, credential fetch, automatic resource release, mirror MCP or per-table ACL APIs.
- A second cursor authority, distributed-transaction assumption, automatic workflow external dispatch or a qualified version matrix inferred from these contracts.
