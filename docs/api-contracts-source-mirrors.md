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
| `POST /objects/{object_id}/mirror` | `metadata:read` on Source and global `mirror:write` | Resolve the table by Catalog id or locator. Send no body. Returns 202 `{mirror: Mirror, operation_id}` after durable acceptance |
| `GET /mirrors` | `mirror:read` | Offset Page, `limit` default 100/max 500, `offset` default 0; optional `source_id`, `status`, `q` literal Source/object-name substring; order Source key, qualified table, mirror id |
| `GET /mirrors/{id}` | `mirror:read` | `{mirror: Mirror}` including redacted evidence, and a top-level `can_enable` flag reflecting current table eligibility |
| `PATCH /mirrors/{id}` | `mirror:write` | `{enabled: boolean}` durable intent; `{mirror: Mirror, operation_id}` does not claim observed stop |
| `DELETE /mirrors/{id}` | `mirror:write` | Requires disabled desired state and successful close through a configured target lifecycle adapter that verifies stop and excludes active or resumable pins. Returns 204 when deleted. Retains Source capture resources. Returns 503 when the target lifecycle adapter is unbound |
| `POST /mirrors/{id}/recovery-requests` | `mirror:write` | `{action: retry\|run_now\|postpone\|manual, expected_history_epoch, reason?}` scoped to the path Mirror. Run now, postpone and manual require a nonblank reason. Returns 202 `{operation_id, state: pending}` |
| `GET /sources/{id}/capture-status` | `sources:read` on Source | `{source_id, profile_id, availability, control, readiness, operations}`; no secrets; availability `disabled\|available\|degraded\|unknown` distinct from Source configuration `capture_state` |

`Mirror` includes `id`, immutable `source_id`/table binding, qualified table name, `enabled`, `status`, `published_generation_id` (nullable), `capture_generation`, `history_epoch`, `retained_lower_bound`, `committed_upper_bound`, `control`, `progress`, `profile`, `readiness`, `fault` (currently null), and `operations`. Status is `waiting|snapshotting|catching_up|ready|stale|rebuilding|paused|needs_attention|disable_pending|unknown|disabled|source_fault`. A correlated snapshot notification projects `progress` with `stage` (scan or catching_up), `generation_id`, `notification_offset` and nullable `observed_at`. Until the current allocation has a verified notification, progress is null. `profile.qualification` reports `qualified` or `unverified`. Readiness items have `key`, `result` (`pass|fail|unknown|not_applicable`), `expected`, `observed`, `observed_at`, `owner`, `action`. Unknown required items block admission.

The Catalog PUT and the compatible enable-only POST each accept one table. The global `mirror:write` check runs before Catalog object lookup. A missing permission returns `403 AUTH_FORBIDDEN`. An unknown or inaccessible Catalog object returns `404 CATALOG_OBJECT_NOT_FOUND`. A visible object that fails Mirror table eligibility returns `404 MIRROR_NOT_FOUND`. Concurrent or repeated enables of the same table converge on the same Mirror and accepted Open operation. Reopening a disabled Mirror retains its identity. A 202 records desired state. Snapshot progress and the published pointer depend on subsequent runtime evidence.

`control` exposes `control_revision`, `credential_revision`, `owner_epoch`, `runtime_instance_id`, `applied_revision`, `observed_at` and nullable `stop_ack`. The redacted acknowledgment contains `operation_id` for the Mirror disable, `source_operation_id` for the observed Source stop, and `observed_at`. Confirmation requires a disabled Mirror, matching current and applied revisions and the matching applied disable journal entry. Until current stop evidence is accepted, a requested disable reports `disable_pending`. A qualified runtime may acknowledge the exclusion of an individual table while other tables are active. It binds independent connector exclusion, drained delivery and target fence evidence to the exact table revision. The published generation is retained.

Operations include durable id, kind, revision, state (`pending|applied|superseded`), request time, evidence references and safe fault code. Recovery admission compares the expected History epoch and audits accepted intent transactionally. A retry cannot authorize destructive change. Reopening a published generation requires current target pointer, owner, fence, certificate and history observations before its open is applied.

Global `mirror:read` authorizes management reads. Global `mirror:write` authorizes lifecycle actions. User-authorized target reads require `sources:data_read` and viewer-or-higher Source Membership. Hidden data bindings return `MIRROR_NOT_FOUND`. A held Source level without the data permission returns `AUTH_FORBIDDEN`. The HTTP surface exposes management metadata. Deployment verification reads the target rows and committed History through restricted paths.

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

The internal signed `published_scope` contains each registered Mirror’s immutable table binding, `mirror_id`, `mirror_revision`, and `included` from its explicit desired state. A disabled entry remains in scope with `included: false` so the runtime can prove exclusion for that revision. Source admission and runtime evidence govern execution. The deployment profile lists the tables the DBA has qualified. The connector and applier run the enabled subset of that inventory. The signed field carries desired registry membership independently of the target publication pointer.

The private scope-fence observation binds the current Source command, scope and per-table target fence receipts. A running observation may carry `table_exclusions` with the excluded scope entry and the connector exclusion, delivery drain and target fence references. The runtime verifies signatures, freshness and the exact revisions before recording exclusions.

Retained resume decisions bind the original published generation and current Source scope. A continuous decision requires authorization for the current target fence. A gap decision identifies the qualified data partition and last skipped offset for an empty replacement. Unknown continuity leaves that table pending. Table-gap invalidation advances only the affected history epoch and retires its old writers before the new generation receives records. The normal capture loop reconciles publication after the independent deployment verifier stores a completion certificate in the target.

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
| `MIRROR_IN_USE` | 409 | Unconfirmed stop or active/resumable pins prevent deletion |
| `MIRROR_RECOVERY_AUTHORIZATION_REQUIRED` | 409 | Unsafe/unknown schema or non-allowlisted recovery requires explicit decision |
| `SOURCE_CAPTURE_RESOURCES_RETAINED` | 409 | Source has retained capture binding; delete refused before cascades |

Audit `mirror.enable`, `mirror.disable`, `mirror.delete`, `mirror.recovery_request` and `notification_channel.replace|test` with actor, Instant, operation and scope ids, reason and allowlisted state. Automatic events use typed notification envelopes.

## 7. Non-Goals

- Public row SQL, raw connector settings, credential fetch, automatic resource release, mirror MCP or per-table ACL APIs.
- A second cursor authority, distributed-transaction assumption, automatic workflow external dispatch or a qualified version matrix inferred from these contracts.
