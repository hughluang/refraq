# refraq API Contracts: Source Mirrors

## 1. Purpose

This document specifies the approved Metadata mirror management and internal execution seams, Channel extensions and Foundation Notification Channel interface. These are implementation contracts, not claims of deployed endpoints or qualified support. Mandatory unknown evidence keeps admission blocked.

Related boundaries:

- Invariants and qualification: `docs/business-source-mirrors.md`
- Sources: `docs/api-contracts-sources.md`
- Channel endpoints and existing Entity streams: `docs/api-contracts-data-channel.md`
- Errors, pagination and time: `docs/conventions-errors.md`, `docs/conventions-pagination.md`, `docs/conventions-time.md`
- Published modules: `docs/backend-layout.md`

## 2. Management HTTP

All paths are API-relative, authenticated by Session or User PAT; failures use Problem Details, UTC Instants and request ids. Unknown request fields are `422 REQUEST_INVALID`. There is no public connector configuration, secret read, target SQL, source offset mutation or snapshot REST endpoint.

| Method And Path | Permission | Contract |
| --- | --- | --- |
| `GET /mirrors` | `mirror:read` | Offset Page, `limit` default 100/max 500, `offset` default 0; optional `source_id`, `status`, `q` literal Source/object-name substring; order Source key, qualified table, mirror id |
| `GET /mirrors/{id}` | `mirror:read` | `{mirror: Mirror}` including redacted evidence, not row values |
| `PATCH /mirrors/{id}` | `mirror:write` | `{enabled: boolean}` durable intent; `{mirror: Mirror, operation_id}` does not claim observed stop |
| `DELETE /mirrors/{id}` | `mirror:write` | 204 only if disabled, stop confirmed, no published reference and no active/resumable pin; never deletes Source capture resources |
| `POST /mirrors/{id}/recovery-requests` | `mirror:write` | `{action: retry|run_now|postpone|manual|reconcile_state, expected_history_epoch, channel_id?, channel_version?, reason}`; scope is the path mirror; reason required for override/reconciliation; Channel fields required only for reconciliation; `{operation_id, state: pending}` (202) |
| `GET /sources/{id}/capture-status` | `sources:read` on Source | `{source_id, profile_id, availability, control, readiness, operations}`; no secrets; availability `disabled|available|degraded|unknown` distinct from Source configuration `capture_state` |

`Mirror` includes `id`, immutable `source_id`/table binding, qualified table name, `enabled`, `status`, `published_generation_id` (nullable), `capture_generation`, `history_epoch`, `retained_lower_bound`, `committed_upper_bound`, `control`, `progress`, `profile`, `readiness`, `fault`, `published_reference_count`. Status is `waiting|snapshotting|catching_up|ready|stale|rebuilding|paused|needs_attention|disable_pending|unknown|disabled|source_fault`. A correlated snapshot notification projects `progress` with `stage` (scan or catching_up), `generation_id`, `notification_offset` and nullable `observed_at`. Until the current allocation has a verified notification, progress is null. Runtime/profile details contain non-secret identity/version and qualified/unverified state. Readiness items have `key`, `result` (`pass|fail|unknown|not_applicable`), `expected`, `observed`, `observed_at`, `owner`, `action`. Unknown required items block admission.

`control` exposes desired `control_revision`, `credential_revision`, `owner_epoch`, `runtime_instance_id`, observed `applied_revision`, `observed_at`, and nullable `stop_ack` with the same stamps and independent exclusion/fence evidence references. It never exposes a credential or infers stop from timestamps. Operations carry durable id, kind, state (`pending|applied|superseded`), observed evidence references and safe fault code. An unapplied command from an older control revision is superseded, never dispatchable pending work. Recovery requests require current expected epoch (409 on mismatch), are deduplicated by operation identity and audited in the management transaction. `retry` never authorizes a destructive change; reconciliation requests are validated against the conservative classifier. No command sacrifices history automatically.

Global management metadata is controlled by `mirror:*`; row/log services require `sources:data_read` Role intersected with viewer-or-higher Source Membership. A missing Role key returns 403 before id resolution. Unknown mirror or no Source level on a data read returns `MIRROR_NOT_FOUND`; a held level without the data key returns `AUTH_FORBIDDEN`. No public raw row/log HTTP is required: Channel adapters consume the authorized internal services below. Logs/errors do not include row values.

## 3. Published Execution Seams

Paths below are approved leaf surfaces to implement with real consumers, not permission to create empty facades or export stores/ORM. Data transfer objects are immutable values; credentials are excluded. Composition binds external delivery, reference, secret, target and notification adapters.

| Module | Callable Contract And Transaction Boundary |
| --- | --- |
| `backend.metadata.mirrors.service` | `resolve_object_binding(object_id, *, session=None)`, `resolve_object_bindings(*, object_ids, session=None)` resolve supported immutable bindings without writes or capture; `authorize_object_reads(*, object_ids, execution_user_id, session=None)` rechecks current grants with the supplied session. `ensure_open_intent(session, *, operation_id, channel_id, channel_version, object_ids, confirmed_mirrors_to_open=None)` deduplicates shared opens and writes reference/open intent in the caller's management transaction; Channel supplies the exact explicit confirmation. `reconcile_references(session, *, channel_id, channel_version, object_ids)` withdraws obsolete published references without destructive capture cleanup |
| `backend.metadata.mirrors.reads` | `acquire_pin(*, run_id, mirror_id, execution_user_id)` returns `Pin(run_id, mirror_id, generation_id, source_id)` by one target pointer/pin transaction; `read_page(*, pin, execution_user_id, after_key, limit)` returns `{rows, next_key, generation_id, source_ids, freshness}` after current authorization; `release_run_pins(*, run_id, terminal_proof)` requires proven non-resumability |
| `backend.metadata.mirrors.history` | `capture_bound(*, mirror_id, execution_user_id)` returns epoch/lower/committed upper; `read_incremental(*, mirror_id, execution_user_id, after, through, limit)` returns authorized `{entries, next_position, lower_bound, upper_bound, source_ids}` in that epoch; `settlement_guard(session, *, proposals, execution_user_id)` locks sorted management gates, checks current auth/epoch/bounds and required bounded target evidence, retaining locks through caller commit; `invalidate_history(session, *, mirror_ids, reason, operation_id)` closes gates and enqueues target invalidation before target mutation |
| `backend.metadata.mirrors.application` | Runtime-only `apply_batch(*, authority, generation_id, partition_identity, records)` uses the sole fenced target transaction; returns committed coverage after commit, never consumer progress; no Channel caller |
| `backend.metadata.mirrors.publication` | Runtime/recovery `publish_generation(*, operation_id, authority, generation_id, certificate)` validates persisted complete certificate and atomically switches target pointer; reconciliation reports observed commit, not accepted intent |
| `backend.metadata.mirrors.bootstrap` | Administrative process `python -m backend.metadata.mirrors.bootstrap` idempotently installs Metadata-owned target schemas, roles, restricted functions and version marker; serving startup validates marker/roles and refuses mismatches rather than doing DDL |
| `backend.metadata.capture.runtime` | Independent product process entry `python -m backend.metadata.capture.runtime`, assembled with allowlisted Connect/signal/Kafka/secret/target adapters; durable command consumer and applier, not a Job or API child |
| `backend.admin.notifications.service` | `enqueue_notification(session, *, event_id, event_type, scope, evidence, severity, responder, safe_action)` writes redacted deduplicated notification intent within caller management transaction; Foundation never imports product packages |

Bootstrap identities are `refraq_mirror_owner` (`NOLOGIN NOSUPERUSER NOBYPASSRLS`, object/function owner), `refraq_mirror_applier` (restricted LOGIN, guarded apply/publication execution only) and `refraq_mirror_gateway` (restricted LOGIN for authorized read/pin functions, no direct row-table grants). None inherits Entity/query owner privileges. Guarded functions use a fixed safe search path and revoke PUBLIC execution. Administrative bootstrap alone may assume the owner role; the applier cannot assume it. Gateway authorization is established by the product service after current Source grant checks, not a caller-supplied User/Source id passed directly to arbitrary SQL. Pool/secret env wiring must be added alongside consuming code and documented in `docs/env.md`; it must preserve these distinct identities.

`authority` contains Source/resource binding, owner epoch/runtime instance, control/credential revision and capture generation. `partition_identity` contains runtime cluster id, topic incarnation id and partition; records contain offset, typed key/schema mapping, operation origin and table/capture lineage. Offsets are contiguous coverage, including classified non-row records. Supported operations are absolute upsert/delete; unsupported key/type/envelope blocks before progress. Batch rollback rolls back rows/log/progress together. Only current installed task authority is accepted; historical record credential age is not a replay rejection rule.

`certificate` contains operation/table/capture/target generation ids, owner/control stamps, successful correlated source completion evidence, producer quiescence/exclusion evidence, reconciled durable source checkpoint, exact expected partition set/end-offset vector, target applied coverage, schema/key fingerprint and empty-table proof when applicable. Persist it before pointer change and recover it by operation id. If the selected profile cannot prove ordered source-to-delivery coverage, reject publication; never synthesize a certificate from lag or elapsed time.

The guarded first switch requires target coverage at the exact certified boundary. An exact retry under the current fence confirms publication while the pointer still names that published generation and target coverage is at or beyond the certified boundary. A superseded pointer or contradictory publication state blocks reconciliation.

Initial open reconciliation requires the committed target pointer, matching certificate and current history epoch under a target observation guard. The guard stays held through the Management transaction that records the generation, initializes the history gate and marks the open applied. An exact retry can confirm its durable Management receipt after the pointer or epoch changes. A historical receipt provides no current pointer or readiness guarantee.

Qualified writers serialize changes to the target pointer, history epoch, and authority against the same Management Source and history fences through target commit. This serialization also covers loss of the target observation session, which releases its database locks. A deployment with independent writers requires a durable target barrier that stays in force through the matching Management commit.

Management consumes `history_loss` receipts through `invalidate_lost_history(text,jsonb,boolean)` on the restricted target applier. The target commits the epoch reset, per-Mirror capture lineage exclusion, and an immutable receipt together under the same stream locks used by allocation, apply, certificate persistence, and publication. An exact replay acknowledges the original transition after a lost reply. The legacy `invalidate_history(text,jsonb)` entry point continues to handle ordinary retention and preserves existing exclusions.

Upgrade requires rerunning the administrative target bootstrap and replacing old Management receipt consumers before loss processing resumes. A missing loss function leaves a pending Management gate invalidating. An existing unfenced target receipt cannot acknowledge a loss. Previously applied legacy losses require explicit qualification of the target epoch and old writer exclusion, or remediation, before reuse. An applied Management receipt alone cannot establish a clean epoch.

A position serializes as `{mirror_id, history_epoch, commit_seq, entry_seq}`. `commit_seq` is a locked committed-prefix counter, not a database sequence reservation; `entry_seq` orders entries within that commit. An entry includes position, source/capture/target lineage, `origin: live`, operation, typed key, before/after images. Only effective live entries appear in incremental pages. `through` fixes an upper committed bound; each page checks retained lower bound and matching gate/target epoch. Cursor tokens cannot bypass authorization.

`settlement_guard` must take the same SQLAlchemy management session as `channel.checkpoints` advancement. Channel adds a session-taking advancement entry; in one transaction it acquires all referenced gates in sorted order, validates all proposals and the active mirror identity, conditionally updates its existing checkpoints, then commits. Invalidation uses those exact gates and commits its outbox before target cleanup. A target RPC outside this transaction or a second CDC checkpoint table is forbidden. Gate/target disagreement or invalidating state yields no checkpoint updates. The successful bounded target validation under gate locks is the linearization point, not a guarantee of future connectivity.

## 4. Channel Integration Shape

Add nullable `mirror_execution_user_id` to workflow settings; required for unattended mirror graphs, validated at publish and mint. Manual runs persist actor id as the separate mirror execution identity. Run serialization includes that identity, target pin references, Source provenance and freshness annotations; restart-resume retains them. Entity/SQL nodes retain existing identity rules. A new rerun is a new run, with identity selected by its trigger semantics.

`read.mirror` configuration is `{object_id, freshness_policy: continue|skip|fail}`. Resolve object to a supported table/mirror at validation and publish. Authoring requires `channel:write` and Source viewer level; actual data execution additionally requires the selected identity's `sources:data_read`. Node output is `{rows, generation_id, freshness, source_ids}` and carries server-enforced provenance. Paging uses the run's target pin and stable keyset, not a newly selected pointer. Unavailable target/no complete generation fails with `MIRROR_READ_UNAVAILABLE` regardless of freshness policy; skip is allowed only for reachable complete stale data.

`read.changes` and `volume.changes_dataset` add `source: {kind: mirror, mirror_id}`; absent/Entity source keeps existing serialization. Mirror proposal/checkpoint fields are `stream_kind: mirror`, existing `stream` = opaque mirror id (within the existing 64-character column), `history_epoch`, position and `source_ids`. Existing Entity checkpoint fields stay backward compatible; mirror epoch must never be overloaded into Entity `xact`. Dataset and transformed/mixed output provenance is the union of contributing Source ids.

Publish confirmation's `mirrors_to_open` is an array of `{source_id, object_id, mirror_id}` for supported required tables not already requested. A stable logical mirror id may be reserved without capture. Confirmed publish commits the actual version references and deduplicated management outbox in the same transaction; a response never asserts readiness. Shared opens reconcile by live published references. Draft sample/preview never opens capture. Missing explicit unattended identity or required grant rejects publish/mint; no fallback.

Every Channel run output, execution, container-round, dataset page, node sample, template preview, export and cache reuse response containing mirror-derived data requires its ordinary permission plus the viewer's current `sources:data_read` on all provenance Sources. Unknown provenance denies the data. Protect nested/mixed payloads conservatively as a whole; no row values in logs/errors. Metadata-only run lists may remain readable under `channel:read` without returning protected payloads. Revocation also denies retry cache reuse and final checkpoint settlement. Non-mirror outputs retain the ordinary Channel rule.

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
| `AUTH_FORBIDDEN` | 403 | Missing capability/current data grant or inactive explicit execution identity |
| `MIRROR_READ_UNAVAILABLE` | 503 | Target unreachable or no complete eligible generation; retryable, no rows/progress |
| `MIRROR_HISTORY_INVALID` | 409 | Epoch, retained bound or management/target gate mismatch; no implicit reset |
| `MIRROR_CONTROL_CONFLICT` | 409 | Stale expected epoch/control, contradictory command or unproven owner exclusion |
| `MIRROR_PUBLICATION_BLOCKED` | 409 | Missing/invalid completion certificate, schema/key or coverage proof |
| `MIRROR_REFERENCED` | 409 | Published workflow references prevent deletion |
| `MIRROR_IN_USE` | 409 | Unconfirmed stop or active/resumable pins prevent deletion |
| `MIRROR_RECOVERY_AUTHORIZATION_REQUIRED` | 409 | Unsafe/unknown schema or non-allowlisted recovery requires explicit decision |
| `SOURCE_CAPTURE_RESOURCES_RETAINED` | 409 | Source has retained capture binding; delete refused before cascades |

Channel may translate invalid mirror proposals to existing `CHANNEL_CHECKPOINT_INVALID` while preserving mirror scope/epoch in secret-free details. No unavailable or authorization error advances checkpoints. An invalid request cannot return partial images. Audit `mirror.enable`, `mirror.disable`, `mirror.delete`, `mirror.recovery_request` and `notification_channel.replace|test` with actor, Instant, operation/scope ids, reason and allowlisted state only. Automatic fault/publication events use typed notification envelopes, not fabricated human audit actors.

## 7. Non-Goals

- Public row SQL, raw connector settings, credential fetch, automatic resource release, mirror MCP or per-table ACL APIs.
- A second cursor authority, distributed-transaction assumption, automatic workflow external dispatch or a qualified version matrix inferred from these contracts.
