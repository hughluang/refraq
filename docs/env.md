# refraq Environment Conventions

## 1. Purpose

This document records the current environment variables and the expected local-development and site-install conventions.

These conventions serve the **Management Console**, **Management Foundation**, and the **metadata foundation** phase (secrets master key, Celery worker/beat). Data Product catalog capabilities may add further variables later.

### 1.1 Optional Capture Deployment Boundary

Source Mirror deployment follows `docs/business-source-mirrors.md` and `docs/api-contracts-source-mirrors.md`. The deployer pins Connect/Kafka/applier artifacts, private mTLS agent transport and secret mounts, distinct target mirror-owner/applier/read-gateway identities, durable command/delivery storage and independent alarm routes. Metadata's administrative mirror bootstrap installs `source_mirror`/`source_mirror_state` and guarded functions; it must not reuse runtime Entity owner/query credentials or expose admin credentials to serving processes. The API target gateway has no raw Mirror grants. The independent capture process has its own declared capacity and pools, never an implicit API/worker default. Startup validates schema/function versions and refuses unbootstrapped optional capability. No production WAL/binlog, disk, buffer, scan, observation or retry limits are invented here: a redacted DBA/deployer-approved profile sheet is mandatory for admission. The exact optional serving and notification settings are defined below; they do not establish profile qualification or start capture. No credentials belong in chat, audit or connector projections.

### 1.2 Optional Mirror Target Settings

`REFRAQ_MIRROR_TARGET` is a protected JSON object, unset by default. Every field is required when the object is present:

| Field | Required Value And Ownership |
| --- | --- |
| `gateway_url` | Secret `postgresql+psycopg` URL with username `refraq_mirror_gateway`, password, host and database |
| `applier_url` | Secret `postgresql+psycopg` URL with username `refraq_mirror_applier`, password, host and the same target database |
| `timeout_ms` | Explicit positive integer, at most 2147483647; target statement and lock timeout |
| `connect_timeout_seconds` | Explicit positive integer; target connection timeout |

Both URLs require `sslmode=verify-full`; only `sslmode` and optional `sslrootcert` query options are accepted. The target must not be the management database. These identities are distinct from Entity owner/reader credentials. Treat the whole object as a secret; never print Settings dumps or validation-error inputs. No production timeout is supplied by default.

The persistent API assembles restricted History and recovery adapters for an explicitly configured Mirror target. They use separate `NullPool` engines, hidden SQL parameters and explicit timeouts. Startup validates target role and schema/function versions before binding. The API disposes adapters on shutdown or assembly failure. Missing policy or memory mode leaves the target unbound. Budget these connections separately from the ordinary entity pools.

Serving assembly neither installs target DDL nor creates a capture/applier data-plane consumer. Run Metadata administrative bootstrap with an independently protected administrative URL selected by `python -m backend.metadata.mirrors.bootstrap --admin-url-env <variable-name>`; do not give that URL to serving processes. Bootstrap owns `source_mirror`/`source_mirror_state` roles and functions; login passwords are provisioned separately. Apply the management migrations through Foundation Upgrade before starting code that uses the changed management schemas, then restart API/worker/Beat. Role/version validation is not exhaustive deployment privilege or network qualification.

Upgrade existing Mirror targets to schema version 3 with the administrative bootstrap before restarting serving processes or Capture Runtime. Version 3 adds guarded certificate reads, retained delivery across table scope changes and isolated replacement after a proven table history gap. Upgrades from versions 1 and 2 retain existing published generations and reader pins. Version 2 introduced exact admitted JSONB numbers and the distinction between JSON null and SQL NULL in target rows and change history. Recover previously lost values from the Source or retained original capture records.

Set `REFRAQ_MIRROR_RECOVERY_RETRY_DELAYS_SECONDS` to a deployer-approved, nonempty JSON array of positive integer delays to enable audited Recovery admission on a persistent API with a qualified Mirror target. The API records operator intent. For a whole-Source PostgreSQL loss covering one admitted Mirror, invoke `python -m backend.metadata.capture.runtime --config-file <protected-file> --dispatch-recovery <operation-id>` with the same retry policy and qualified Mirror target. The independent runtime verifies signed loss and readiness observations that bind the operation, previous authority, Mirror scope, and History epoch. `invalidated` and `dispatched` are successive durable states. Owner promotion and guarded publication use the reserved replacement identity.

### 1.3 Optional Notification Deployment Settings

These are deployer-owned process environment settings, not System Parameters. They contain policy/bounds, never route credentials. Encrypted primary/fallback endpoints, credentials and responder are configured through `/settings/notification-channel` with `settings:write`.

| Variable | Value And Missing-Configuration Behavior |
| --- | --- |
| `REFRAQ_NOTIFICATION_REVIEWED_ORIGINS` | JSON object mapping canonical HTTPS origins to independently reviewed failure-domain labels; unset defaults to an empty deny-all mapping |
| `REFRAQ_NOTIFICATION_DELIVERY` | Optional JSON object requiring every budget field below; unset provides no delivery budget or invented cadence |

A canonical origin has no path/trailing slash, userinfo, query, fragment or explicit default port 443. Primary/fallback require distinct approved origins and distinct failure-domain labels. Labels record an independent deployment review; different labels/DNS names alone do not prove independence. Redirects and ambient HTTP proxy settings are not used; deployment still owns egress isolation and DNS protections.

The delivery budget requires exactly these fields:

| Field | Constraint |
| --- | --- |
| `max_attempts_per_route` | Positive integer |
| `retry_delays_seconds` | Positive finite numeric array of exactly `max_attempts_per_route - 1` entries; empty for one attempt |
| `timeout_seconds` | Positive finite remote timeout |
| `batch_size` | Positive integer; bounds work while management row locks are held |
| `interval_seconds` | Positive integer; delivery duty cadence |

All values require approved retry/capacity/lock-duration evidence; there are no production defaults. API needs the reviewed-origin mapping for route writes. Worker needs both settings to deliver; schedule assembly used by Upgrade and Beat/worker enables the hidden, locked, undeletable, store-only `system.notification_delivery` duty only with both settings. Missing either disables an existing duty, does not invent a new row/cadence, and produces a fixed blocked warning. The registered task is `backend.worker.tasks.deliver_notifications`; due-tick consumption and delivery share the management transaction. Configure API/worker/Beat consistently and restart affected processes after env changes.

Queued route tests are not delivery confirmation: both routes must have observed successful delivery for the current configuration. Remote acceptance before a local crash may repeat; receivers must deduplicate the event-id `Idempotency-Key`. Failed terminal deliveries remain visible. This management outbox is not management-independent source protection, a CDC observation producer, or proof of production alarm reachability.

### 1.4 Independent Capture Process Configuration

`python -m backend.metadata.capture.runtime --config-file <protected-path> [--once]` reads an explicit private JSON file. It reconciles signed owner assignment, PostgreSQL capture preparation, Connect lifecycle and the restricted Kafka-to-target applier. A current-owner stop remains available when preparation or start readiness fails. Snapshot signaling and generation publication have separate evidence requirements.

The configuration contains `management_database_url_file` (private PostgreSQL URL file requiring `sslmode=verify-full`), `state_directory` (pre-created private effective-user-owned durable journal/lock directory), `poll_interval_seconds` (positive, at most 3600), and `sources` (1..100 unique assignments). Each Source entry requires `source_id`, generated `connector_name`, `connect_tls`, `signals_tls`, `readiness_policy`, `signing_trust`, `postgresql_profile` and `credential_files`. Each TLS object supplies HTTPS-only `origin`, private `ca_file`/`cert_file`/`key_file`, positive `timeout_seconds` at most 120 and positive `max_response_bytes` at most 1048576. Readiness supplies `runtime_instance_id`, positive `max_age_seconds` at most 3600 and mandatory checks for profile, source pressure, bounded delivery, credential validity, alarm drill, owner exclusion and target fence. `signing_trust` pins the EdDSA `public_key_files` by key id, `issuer` and `audience`. `owner_allocation_file` supplies the exact deployment-signed `operation_id` and `signature` for an assignment. The transport limits bound individual calls. Source safety limits come from the approved profile.

For each current pending open, `delivery_settings_file` supplies one protected table entry with `topic`, `partition_identity`, `schema_fingerprint`, canonical PostgreSQL `native_types`, `start_offset` and `decoder`. The decoder pins the stable catalog table identity, Source database and table names, connector namespace/version and full ordered key and value schemas. Management resolves the mirror operation and assigns the generation id durably. The runtime binds authority and capture generation at reconciliation time. Leave `generation_id`, `authority` and decoder `capture_generation` out of pending-open entries. An already installed table without a current pending open uses the explicitly pinned generation id and authority. The delivery settings also supply bounded `limits`, `max_age_seconds`, `kafka`, `group_id` and `target`. The target takes a private applier `url_file` with verified PostgreSQL TLS and `timeout_seconds`. The runtime reads `delivery_metadata` with the restricted applier and compares the installed mirror, operation, history epoch, authority, schema, physical primary key and broker incarnation before Connect configuration or resume. For a pending open, it also checks the immutable starting offset and compares the signed fence receipt digest with the target's committed receipt for the current authority and history epoch.

The deployment artifact is the independently supervised private mTLS `signals_tls` gateway. Give its privileged target adapter a bounded administrative connection that can assume the mirror owner role. Mount the administrative URL and signing keys only in the deployment gateway's trust boundary. The runtime receives pinned public signing keys and its dedicated restricted target login. The gateway authenticates each runtime assignment, independently observes source safety, task and agent exclusion, target inventory and alarm readiness, and journals exact requests. On `POST /v1/capture/owner-allocations`, it calls `backend.metadata.mirrors.bootstrap.prepare_authority` on each required target before signing the owner observation. Use the stable mirror and catalog identities and `initial_history_epoch(mirror_id)` for a new mirror. For an existing target, verify the current history epoch and prior fence under producer exclusion. Include retained targets in the inventory and recover the same committed receipt after an uncertain response.

When a table switch changes the published scope under the same owner, `POST /v1/capture/scope-fences` requests a fence for the new Source control revision. The gateway verifies the exact reconciliation operation and scope, excludes the previous producer, drains in-flight delivery and prepares target fences for each included or excluded Mirror in the approved profile. The signed `observation:scope_fence` binds the operation, authority, profile and published scope. Its `mirror_receipts` maps every such Mirror ID to the committed target receipt digest. During running observation, `table_exclusions` can confirm an individual stop after the gateway verifies the connector excluded that table, the target fenced its old writers and in-flight delivery drained.

When an allocated snapshot is interrupted by another switch, the gateway also supplies a signed `table_boundaries` entry for the affected Mirror. Identify the current Mirror revision and original Kafka cluster, topic incarnation and partition. While the previous producer and delivery are drained, verify the stable end of the partition. Supply `mirror_revision`, `partition_identity`, the last offset before the fresh snapshot as `start_offset` (`-1` for an empty partition), and an `evidence_ref` SHA-256 digest. This also applies when an operator closes and reopens a table before its initial or replacement generation has published. The runtime can then fence the incomplete generation and allocate an empty replacement under the new history epoch.

The ordinary `owner_allocation_file` contains exactly `operation_id` and `signature`. The signature is the signed assignment authorization for the current capture lineage. A rejected file blocks assignment while allowing the current owner to execute an authenticated stop. Whole-Source recovery after `history_loss` requires deployment evidence of a fresh PostgreSQL connector start bound to the recovery operation and candidate authority. An independent observer must verify the database and WAL lineage, the slot incarnation and start position, the durable Connect offset identity and position, and the admitted Kafka topic incarnations, partitions, and start offsets. The ordinary assignment and fence receipts prove owner assignment and target fencing at the existing lineage. Replacement snapshot preparation requires a separately verified recovery allocation.

For `POST /v1/capture/open-generation-bindings`, the gateway signs `observation:open_generation_binding` only after checking the current fence receipt, full Source schema/key, Kafka topic and partition incarnation, and admitted starting offset against its own evidence. For `POST /v1/capture/generation-allocations`, revalidate the binding proof and fence, and call `backend.metadata.mirrors.bootstrap.create_generation` with `require_prepared_fence=True` and the management-claimed generation id. Sign `observation:generation_allocation` after the target transaction commits. Both observations bind the exact request operation, authority and scope, including the profile, published scope, open identity and immutable table. The allocation scope adds the claimed generation id. Each signed result supplies `verified`, `observed_at` and the verified `fence_receipt`. When the authority matches the committed owner assignment, the binding receipt must also match that assignment's receipt for the mirror. Repeat the same allocation request after uncertainty. Return the existing exact outcome or reject the conflicting binding.

For the initial incremental snapshot trial, add `snapshot` to `postgresql_profile.scope`. Set `signal_table`, `signal_relation_identity` as `<database-oid>:<relation-oid>`, `notification_topic`, and `notification_partition`. The PostgreSQL 18.6 profile uses the Debezium 3.7.1.Final source signal channel, `insert_insert` watermarks, and sink notifications on a dedicated partition 0 in the same Kafka cluster. The DBA creates the permanent signal relation with text or varchar `id`, `type`, and `data` columns in that order, a nondeferrable primary key on `id`, and no row security. Include the signal relation in the DBA publication and grant the connector `SELECT` and `INSERT`. Keep it outside the mirror table list.

Set `snapshot_observers` on the Source entry with `max_age_seconds` and separate `receipt` and `notification` objects. Each supplies `tls` and `signing_trust`. Pin disjoint signing keys for the receipt and notification observers. The `signals_tls` gateway handles `POST /v1/capture/snapshots/submit` with the exact operation and relation binding. The receipt observer verifies the retained signal row using its independent reader identity. The notification observer binds each challenged `baseline` and `notifications` response to the pinned topic incarnation, and attests exclusive signal authority and the observed offset range. Both observer endpoints return the signed observation as `signature`. Exercise loss of the submission response and observer continuity in the site drill. The confirmed attempt enters catch-up and still requires the publication evidence in the Source Mirror contract.

At startup, run the Metadata administrative bootstrap from §1.2 with the matching release to install the fence receipt relation and restricted delivery metadata projection. Start the gateway with inventory, signing, exclusion and alarm integrations before launching the supervised runtime. Preserve the protected journal across restarts. For rotation, stage new CA trust, client certificates and signing key pins while existing trust is usable. Replace protected configuration and reload the affected processes. Confirm authenticated observations and restricted target metadata under the new settings before removing previous trust. For owner replacement, independently exclude the old executor, commit the new fences through the gateway, and submit the exact assignment file. The disposable native fixture exercises the gateway protocol. Production qualification requires an observed deployment drill for exclusion, source safety and alarm delivery.

## 2. Current Files

### Backend

Current `backend/.env.example` defines:

- `REFRAQ_ENV=dev`
- `REFRAQ_API_HOST=127.0.0.1`
- `REFRAQ_API_PORT=8000`
- `REFRAQ_MCP_HOST=127.0.0.1` (Metadata MCP process bind; local default localhost)
- `REFRAQ_MCP_PORT=8001`
- `REFRAQ_ENTITY_MCP_HOST=127.0.0.1` (Entity MCP process bind; local default localhost)
- `REFRAQ_ENTITY_MCP_PORT=8002`
- `REFRAQ_STORE_BACKEND=persistent`
- `TZ=UTC` (process timezone default; override via standard `TZ` only)
- `DATABASE_URL=postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq`
- `ENTITY_DATABASE_URL=postgresql+psycopg://refraq_entity_owner:change-me@127.0.0.1:5432/refraq_entity` (entity owner connection; not a superuser)
- `ENTITY_READER_DATABASE_URL=postgresql+psycopg://refraq_reader:change-me@127.0.0.1:5432/refraq_entity` (entity reader connection; persistent API and Entity MCP)
- `ENTITY_SIGNER_DATABASE_URL=postgresql+psycopg://refraq_signer:change-me@127.0.0.1:5432/refraq_entity` (entity signer connection; Entity MCP and bootstrap; username `refraq_signer`)
- `ENTITY_ADMIN_DATABASE_URL=postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq_entity` (entity bootstrap only; never read by api, mcp, entity_mcp, worker, or beat)
- `REDIS_URL=redis://127.0.0.1:6379/0`
- `ADMIN_SESSION_SECRET=change-me`
- `INITIAL_ADMIN_ACCOUNT=root`
- `INITIAL_ADMIN_PASSWORD=change-me`
- `REFRAQ_SECRETS_MASTER_KEY=change-me-secrets-master-key` (metadata foundation: encrypt Source secrets at rest)
- `CELERY_BROKER_URL=redis://127.0.0.1:6379/2` (Celery broker; prefer a logical DB separate from Session `REDIS_URL`). If unset, broker is derived from `REDIS_URL` (`…/2`); if both unset, resolution fails (no localhost invent).
- `REFRAQ_EMBEDDING_API_URL`, `REFRAQ_EMBEDDING_MODEL`, `REFRAQ_EMBEDDING_TIMEOUT_SEC` (retired. Catalog Search vector path is an in-use **Model Service**. These names are ignored and reported at startup as dead. They are not **System Parameter**s and are not imported into rows)
- `REFRAQ_CATALOG_FAIL_SAFE_THRESHOLD` (retired. A complete successful structure collect always commits. Leftover name is ignored and reported at startup)
- `REFRAQ_PEEK_SLOTS` (retired. Admission size is `REFRAQ_ADMISSION_SLOTS` / `REFRAQ_ADMISSION_ACTOR_SHARE`. Leftover name is ignored and reported at startup)

Session TTL, occupancy lost-detection, live-peek timeout, and live-peek row cap are **System Parameter**s (`docs/business-system-parameters.md` §5). They are not environment variables. A leftover name matching a registered key (`ADMIN_SESSION_TTL_HOURS`, `REFRAQ_JOB_LOST_DETECTION_SEC`, `REFRAQ_QUERY_TIMEOUT_SEC`, `REFRAQ_QUERY_MAX_ROWS`, or the key itself in uppercase) is ignored and reported at startup as dead. The stored row is the only home.

Worker concurrency is neither. It is owned by the deployment and set on the worker command line (§8); `REFRAQ_JOB_WORKER_CONCURRENCY` is retired and reading it is not implemented anywhere. Beat loop / reload intervals and the reaper poll interval are in-code constants or derived from lost-detection (`docs/business-system-parameters.md` §5.2), not environment variables and not System Parameters.

Runtime capacity (ADR 0040 / 0045) is also deployment env, not System Parameters. Each process declares `REFRAQ_PROCESS_ROLE` (`api` / `mcp` / `worker` / `entity_mcp`) at its entry so import-time pool construction sees the role. Do not put this key in a shared `.env` — API, Metadata MCP, Entity MCP, and worker would then share one value. Unset keys use process-role defaults (`api` / `mcp` / `worker` / `entity_mcp`):

| Variable | api default | mcp default | entity_mcp default | worker default |
| --- | --- | --- | --- | --- |
| `REFRAQ_DB_POOL_SIZE` | 8 | 5 | 5 | 5 |
| `REFRAQ_DB_MAX_OVERFLOW` | 4 | 3 | 3 | 5 |
| `REFRAQ_DB_POOL_TIMEOUT_SEC` | 5 | 5 | 5 | 5 |
| `REFRAQ_DB_POOL_RECYCLE_SEC` | 1800 | 1800 | 1800 | 1800 |
| `REFRAQ_DB_STATEMENT_TIMEOUT_MS` | 30000 | 30000 | 30000 | unset (no statement_timeout) |
| `REFRAQ_HTTP_MAX_INFLIGHT` | 32 | 16 | 16 | n/a |
| `REFRAQ_THREAD_TOKENS` | 8 | 4 | 4 | n/a |
| `REFRAQ_ADMISSION_SLOTS` | 32 | 16 | 16 | n/a |
| `REFRAQ_ADMISSION_ACTOR_SHARE` | 8 | 8 | 8 | n/a |

`REFRAQ_ADMISSION_SLOTS` is the concurrent-people declaration for work that waits on an external system (ADR 0045). `REFRAQ_ADMISSION_ACTOR_SHARE` is one User's concurrent external waits (agent fan-out); it is clamped to the slot count and is 0 when slots is 0. `REFRAQ_ADMISSION_SLOTS=0` on api, mcp, and entity_mcp is honored: admitted work is refused immediately (`ADMISSION_CAPACITY_EXCEEDED`). Worker admission stays 0 regardless of the env keys. `REFRAQ_PEEK_SLOTS` is retired; leftover names are ignored and reported at startup. Tune slots from `/metrics` (`refraq_admission_slots_occupied`, `refraq_admission_slots_limit`, `refraq_admission_actor_share_limit`, `refraq_capacity_rejects_total`). Intranet `GET /metrics` (Prometheus text) is on the API, Metadata MCP, and Entity MCP processes, compose-internal and never published. The Console proxy returns 404 for `/api/metrics` so the `/api/:path*` rewrite cannot expose it. `/api/readyz` stays as today. `/healthz`, `/readyz`, and `/metrics` on the process bypass load-shed.

The entity database is a separate database that the worker, persistent API, and Entity MCP process open. It may share a server with the metadata database, but it must not be the same database: startup of api and worker refuses a configuration where `ENTITY_DATABASE_URL` and `DATABASE_URL` resolve to the same server and database name. Entity MCP refuses that equality on the reader URL. Runtime entity connections must not be superusers; api and worker check `rolsuper` on each entity pool at startup and refuse to start otherwise. They also refuse to start when schema `entity_data`, `entity_access`, `acl`, or `channel_dataset` is absent. Startup does not create those schemas. Entity MCP checks the reader login and the signer login for superuser and `BYPASSRLS`, and does not open the owner pool, so it does not run that schema check. The roles and their rights are `docs/business-entity-access.md` §15:

| Connection | Role | Used by | Purpose |
| --- | --- | --- | --- |
| `ENTITY_DATABASE_URL` | `refraq_entity_owner` (LOGIN, not superuser) | api, worker | Publish and drop DDL, Profile View regeneration, Entity Data API writes, Data Channel SQL when the node selects the entity database, and access-context signing for API and worker |
| `ENTITY_READER_DATABASE_URL` | `refraq_reader` (LOGIN, `NOSUPERUSER NOBYPASSRLS NOINHERIT`, read-only by default) | api, entity_mcp | Entity Data API reads and Entity MCP reads, including Entity SQL, through Profile Views |
| `ENTITY_SIGNER_DATABASE_URL` | `refraq_signer` (LOGIN, `NOSUPERUSER NOBYPASSRLS NOINHERIT`) | entity_mcp | Execute `acl.ensure_signing_key()` only. The function may insert a key. Direct reads of `acl.signing_keys` are denied. User SQL does not run as this role. Bootstrap reads the password from this URL; the username is `refraq_signer` |
| `ENTITY_ADMIN_DATABASE_URL` | an administrative role able to create roles and extensions | `python -m backend.entity.bootstrap` only | Create roles, schemas `entity_data` / `entity_access` / `acl` / `channel_dataset`, `pgcrypto`, `acl` functions and key table; move existing tables into `entity_data`; enable and force row-level security |

The bootstrap is idempotent. It does not create `refraq_channel_reader`. When that role is present, the bootstrap revokes the privileges it holds in the entity database and drops the role. Runtime processes never read `ENTITY_ADMIN_DATABASE_URL`; do not put it in the api, mcp, entity_mcp, worker, or beat environment. Role passwords are site secrets in the live `.env`. Bootstrap takes the signer password from `ENTITY_SIGNER_DATABASE_URL`. Compose interpolates `ENTITY_SIGNER_PASSWORD` into that URL for role `refraq_signer`. A site env without that password cannot bootstrap the signer role.

The product always treats each entity connection as a separate engine, a separate pool, and a separate budget line. The Metadata MCP process and Beat hold no entity-database connection. Persistent API uses the owner and reader pools for the **Entity Data API** and applies `REFRAQ_DB_STATEMENT_TIMEOUT_MS` plus `lock_timeout` on those connections (`docs/api-contracts-entity-data.md`); the reader role also carries role-level timeouts set by the bootstrap. The worker opens the owner URL for publish, drop, and view regeneration Jobs; by existing convention the worker sets no statement timeout on entity connections used for long DDL. The Entity MCP process opens the reader pool and a signer pool of size 1 and overflow 0. The signer pool is outside `entity_pool_count` and outside the `REFRAQ_ENTITY_DB_*` line for that process. API and worker sign with the owner pool. Entity schemas are fixed (`entity_data`, `entity_access`, `acl`, `channel_dataset`). A persistent api or worker whose entity database is missing any of them refuses to start and names `python -m backend.entity.bootstrap`. `REFRAQ_ENTITY_DB_SCHEMA` is retired; a leftover name is ignored and reported at startup.

Local `compose.yaml` and `deploy/compose.yaml` default the entity connections to database `refraq_entity` on the same Postgres instance as `DATABASE_URL`. `POSTGRES_DB` only creates `refraq`; a one-shot `ensure-entity-db` service creates `refraq_entity` when missing, including on an already-initialized volume. Site compose runs `python -m backend.entity.bootstrap` in that service before api and worker start. Local compose only creates the database; run the bootstrap from the backend environment before a persistent API or worker. `/readyz` does not probe the entity database.

An entity database that already holds physical tables or stem views in `public` is moved by that same bootstrap (`--legacy-schema` names another schema when the tables were not in `public`). The command is idempotent. Stop api and worker, take a dump of the entity database, then run the bootstrap with `ENTITY_ADMIN_DATABASE_URL` before starting the upgraded processes on `ENTITY_DATABASE_URL` and `ENTITY_READER_DATABASE_URL`. Metadata migration `0050_entity_attribute_ids` is a separate Foundation Upgrade step on the metadata database.

Rollback of the entity database, before any Profile View depends on the new layout: stop api and worker; as the admin role, for each table and stem view in `entity_data`, `ALTER ... SET SCHEMA public`, `DROP POLICY`, `DISABLE ROW LEVEL SECURITY`, and `ALTER ... OWNER TO` the previous owner; point `ENTITY_DATABASE_URL` back at that owner. Dropping `refraq_entity_owner`, `refraq_exposure_owner`, `refraq_acl_owner`, or `refraq_reader` requires `REASSIGN OWNED` / `DROP OWNED` in the entity database after the relations have a new owner. Restore the dump instead when the bootstrap moved data and a later step failed. Downgrade `0050_entity_attribute_ids` strips `attribute_id` from stored attribute documents; do that only together with a code rollback that does not read the field.

| Variable | api default | mcp default | entity_mcp default | worker default |
| --- | --- | --- | --- | --- |
| `ENTITY_DATABASE_URL` | required (fail-fast when persistent); must not name the metadata database | n/a (no entity pool) | not opened; when set, the reader database must be that same database | required; must not name the metadata database |
| `ENTITY_READER_DATABASE_URL` | required (fail-fast when persistent); same database as `ENTITY_DATABASE_URL` | n/a | required (fail-fast when persistent); must not name the metadata database; same database as `ENTITY_DATABASE_URL` when that variable is set; login must not be superuser or `BYPASSRLS` | n/a |
| `ENTITY_SIGNER_DATABASE_URL` | n/a | n/a | required (fail-fast when persistent); same database as `ENTITY_READER_DATABASE_URL`; login must not be superuser or `BYPASSRLS` | n/a |
| `ENTITY_ADMIN_DATABASE_URL` | n/a | n/a | n/a | n/a (bootstrap only) |
| `REFRAQ_ENTITY_DB_POOL_SIZE` | 4 | n/a | 4 (reader pool; signer pool is fixed at 1) | 5 |
| `REFRAQ_ENTITY_DB_MAX_OVERFLOW` | 0 | n/a | 0 (signer overflow is 0) | 5 |
| `REFRAQ_ENTITY_DB_POOL_TIMEOUT_SEC` | 5 | n/a | 5 | 5 |
| `REFRAQ_ENTITY_DB_POOL_RECYCLE_SEC` | 1800 | n/a | 1800 | 1800 |

The `REFRAQ_ENTITY_DB_*` sizing applies to each entity pool counted in the budget below. The Entity MCP signer pool is size 1 and overflow 0 and does not use those variables.

Pool-budget line items (each line is `pool_size + max_overflow`):

| Process role | Pools opened | This-process budget |
| --- | --- | --- |
| api | metadata (`REFRAQ_DB_*`), entity owner and entity reader (`REFRAQ_ENTITY_DB_*` each) | the sum of the three pools |
| mcp | metadata (`REFRAQ_DB_*`) | that pool |
| entity_mcp | metadata (`REFRAQ_DB_*`) and entity reader (`REFRAQ_ENTITY_DB_*`) | the sum of both pools; the signer pool (size 1, overflow 0) is one connection beside that sum |
| worker | metadata (`REFRAQ_DB_*`) and entity owner (`REFRAQ_ENTITY_DB_*`) | the sum of both pools |
| beat | metadata (`REFRAQ_DB_*`) | that pool |

Processes that open several pools (api, entity_mcp, and worker) print each counted pool separately; the "this process budget" number is their sum and does not include the signer connection. Deploy constraint: the sum of every process-role budget across API + Metadata MCP + Entity MCP + worker + Beat, plus the Entity MCP signer connection, should stay at or below `0.8 ×` Postgres `max_connections`. That inequality is a printed deployment constraint, not a startup assertion — no process reads Postgres `max_connections`, and no process can see the other roles' pools. Admission slots are not part of that sum.

Database supply is the other half of ADR 0040. Local `compose.yaml` and `deploy/compose.yaml` set `shm_size: 2gb` and start Postgres with `shared_buffers=1GB`, `effective_cache_size=3GB`, `work_mem=16MB`. These are Compose command flags, not `REFRAQ_*` process env and not System Parameters. Do not leave `shared_buffers` at the 128MB factory default: Catalog embeddings are toast-heavy and neighbor SQL is an exact scan. `effective_cache_size` is a planner hint (it does not allocate). Container `shm_size` must exceed `shared_buffers` or PostgreSQL will not start.

Persistent Store Backend requires **PostgreSQL 18 or newer** with `pg_trgm` and `pgvector` enabled (ADR 0041). Local `compose.yaml` and `deploy/compose.yaml` use `pgvector/pgvector:pg18`. Foundation Upgrade fail-fasts if either extension cannot be created. `amcheck` is an optional operations extension for verifying btree indexes after a restore or an image change. Foundation Upgrade does not create it and does not depend on it. Catalog embeddings are stored as `vector` plus `embedding_dim` (no typmod). Catalog Search projects query and index vectors to 1024-d (`EMBEDDING_OUTPUT_DIM`) so a later ANN index is physically possible (`vector` HNSW limit 2000). Exact `<=>` scan is the neighbor path until ADR 0041 Decision 5 fires.

A PG16 data directory cannot be opened by PG18. Upgrading an existing volume is dump → replace the image → restore (`scripts/upgrade_platform_postgres_to_pg18.sh`). Do not attach a 16-era `refraq_pg` volume to the pg18 image. A site that needs the data on a specific host disk overrides the volume (`docker-compose.override.yml` or `driver_opts` bind) instead of editing the template. After restore, run Foundation Upgrade so revision `0040_catalog_embeddings_vector` converts JSONB embeddings.

New installs and this compose persist Postgres on the named volume `refraq_pg` at `/var/lib/postgresql` (the image VOLUME; default PGDATA is `/var/lib/postgresql/18/docker`). `/var/lib/postgresql/data` is not the data directory. A site that already runs with that mount, including one hand-edited to it, keeps its data when compose is replaced, provided the named volume already contains the cluster. A site that only ever used the published v0.1.8 asset (`refraq_pg:/var/lib/postgresql/data`) has its cluster in an anonymous volume; replacing compose with this file does not see that data. Move it once before `up -d`, while the v0.1.8 compose is still in place: stop postgres without removing volumes, and copy the anonymous volume's `18` directory onto `refraq_pg` (`cp -a /var/lib/postgresql/18 /var/lib/postgresql/data/18` through that container's mounts) so the cluster is at `/var/lib/postgresql/18/docker` after the new mount, or dump with `pg_dumpall` and restore. There is no automatic copy.

Remove `ADMIN_SESSION_TTL_HOURS`, `REFRAQ_JOB_LOST_DETECTION_SEC`, `REFRAQ_QUERY_TIMEOUT_SEC`, and `REFRAQ_QUERY_MAX_ROWS` from live `.env` files. Changing them and restarting has no effect. Tune those values in Platform Settings. Set concurrency where the worker is launched.

`REFRAQ_STORE_BACKEND=memory` is for automated tests only. Do not use it in production examples.
Metadata foundation variables are required when running ingestion/secret features; Foundation-only local login may still boot without them until those code paths are exercised.

### Frontend

Current `frontend/.env.example` defines:

- `NEXT_PUBLIC_REFRAQ_API_BASE_URL=/api`
- `REFRAQ_API_UPSTREAM=http://127.0.0.1:8000`
- `REFRAQ_MCP_UPSTREAM=http://127.0.0.1:8001` (web Route Handler streams `/mcp` here; never expose `readyz`)
- `REFRAQ_ENTITY_MCP_UPSTREAM=http://127.0.0.1:8002` (web Route Handler streams `/mcp/entity` here; timeout 305s; never expose `readyz`)
- `NEXT_PUBLIC_DEFAULT_LOCALE=en-US`

`REFRAQ_API_UPSTREAM` has matching build-time and runtime duties. Next.js reads it at build time to compile browser `/api` rewrites. Server-only frontend code reads it at runtime for direct SSR calls such as public Site Branding. Local `next dev` uses the env file. Published web images bake `http://api:8000` as a Docker build argument; the site compose also sets the same runtime value.

### Deploy

`deploy/` holds the site compose template, the scrape file, and the secrets example. It is not a live site directory and is not an install source. Download `docker-compose.yaml`, `.env.example`, and `prometheus.yml` from the GitHub Release (`https://github.com/hughluang/refraq/releases/latest/download/docker-compose.yaml`, `…/download/.env.example`, and `…/download/prometheus.yml`). Replacing only the Compose file leaves Prometheus without configuration, so the scrape file is replaced with it. Never commit the live `.env`.

Current Release / `deploy/.env.example` defines:

- `INITIAL_ADMIN_ACCOUNT=root`
- `INITIAL_ADMIN_PASSWORD` (required live secret)
- `ADMIN_SESSION_SECRET` (required live secret)
- `REFRAQ_SECRETS_MASTER_KEY` (required live secret; stable per site)
- `POSTGRES_PASSWORD` (required; platform Postgres, internal Docker network only)
- `ENTITY_OWNER_PASSWORD` (required; password for `refraq_entity_owner`; URL-safe characters only)
- `ENTITY_READER_PASSWORD` (required; password for `refraq_reader`; URL-safe characters only)
- `ENTITY_SIGNER_PASSWORD` (required; password for `refraq_signer`; URL-safe characters only; Compose interpolates it into `ENTITY_SIGNER_DATABASE_URL`. Bootstrap reads the password from that URL, not from this name)
- `REFRAQ_MONITOR_PASSWORD` (required; password for `refraq_monitor`; `LOGIN`, `NOSUPERUSER`, granted `pg_monitor`; URL-safe characters only, no `@ : / % ? #`; Compose interpolates `${REFRAQ_MONITOR_PASSWORD:?set REFRAQ_MONITOR_PASSWORD}` and refuses the Postgres collector and the monitor-role one-shot when it is unset)
- `REFRAQ_PROMETHEUS_URL` (optional; URL the API uses to read the in-stack series store; default `http://prometheus:9090`. Not a capacity knob and not grouped with `REFRAQ_HTTP_MAX_INFLIGHT`)
- `REFRAQ_WEB_PORT=3001` (host port for the Management Console)
- `REFRAQ_BROWSER_FACING_PROTO` (optional on web; default `http`; set `https` when TLS terminates in front of the Console)
- `REFRAQ_BROWSER_FACING_HOST` (optional on web and API; host or `host:port` the browser uses for the Console, without scheme. Required for non-loopback Console URLs so OIDC `redirect_uri` is not taken from request `Host`)

Prometheus keeps samples for `15d` or `1073741824` bytes, whichever comes first, on the named volume `refraq_prometheus`. A `blkio_config` weight is a relative preference under contention, not latency isolation. A second named volume on the same device is not isolation. node_exporter listens on host port `9100` because it uses the host network; block `9100` from everything except the Compose bridge. The Compose file does not publish that port and does not enforce the firewall rule.

Image tags live in the stamped Release compose, not in `.env`. A leftover `REFRAQ_VERSION` in an older site `.env` has no effect after the compose attachment replaces the interpolated template. Published images are **linux/amd64** only (`ghcr.io/hughluang/refraq-api:<version>` and `ghcr.io/hughluang/refraq-web:<version>`). Compose project name is `refraq-prod` so volumes do not collide with the local Postgres/Redis Compose and stay attached when the site directory moves.

## 3. Local Convention (Unified)

- backend host: `127.0.0.1`
- backend port: `8000`
- Metadata MCP process: `127.0.0.1:8001` (`python -m backend.metadata.mcp_http`)
- Entity MCP process: `127.0.0.1:8002` (`python -m backend.entity.mcp.http`)
- browser API base URL: `/api` (same-origin)
- browser Metadata MCP URL: `{origin}/mcp` (same-origin; the MCP workspace copies this)
- browser Entity MCP URL: `{origin}/mcp/entity` (same-origin; the MCP workspace copies this)
- browser OpenAPI UI: `{origin}/docs` (Swagger UI; Next.js rewrite to the API)
- browser OpenAPI spec: `{origin}/openapi.json` (same-origin rewrite; Swagger loads this path)
- Next.js rewrite upstream: `http://127.0.0.1:8000` (dev)
- Next.js `/mcp` stream upstream: `http://127.0.0.1:8001` (`REFRAQ_MCP_UPSTREAM`)
- Next.js `/mcp/entity` stream upstream: `http://127.0.0.1:8002` (`REFRAQ_ENTITY_MCP_UPSTREAM`); proxy timeout 305s
- Next.js server-rendering API upstream: `http://127.0.0.1:8000` (dev)

The browser talks to the backend through a Next.js rewrite so the session cookie is set on the frontend origin and `proxy.ts` can see `refraq_sid`. Server-only rendering code calls the same upstream directly through `REFRAQ_API_UPSTREAM`; it does not make a loopback request to the Next.js server. URLs emitted into HTML remain browser-facing same-origin paths and never expose this internal upstream. ReDoc is disabled. `/api/docs` may still reach Swagger via the generic `/api/:path*` rewrite; operators should use `/docs` and `/openapi.json` on the web origin.

Swagger Try it out uses OpenAPI `servers: [{"url": "/api"}]` so browser calls go to `{origin}/api/...` (rewrite strips `/api` before the API process). Protected operations document HTTP Bearer for a User PAT via Authorize (`Authorization: Bearer`). Session cookie auth is unchanged: after Console login on the same origin, Try it out also sends `refraq_sid` on same-origin `/api` requests. Do not paste the HttpOnly session cookie into Authorize.

Site compose exposes only the web service to browsers; the API stays on the internal network and must be named `api`. The Metadata MCP process is the same api image with `python -m backend.metadata.mcp_http`; compose names it `mcp` and does **not** publish its port. The Entity MCP process is the same image with `python -m backend.entity.mcp.http`; compose names it `entity-mcp` and does **not** publish its port. Web streams `{origin}/mcp` to `REFRAQ_MCP_UPSTREAM` (`http://mcp:8001` on site) and `{origin}/mcp/entity` to `REFRAQ_ENTITY_MCP_UPSTREAM` (`http://entity-mcp:8002` on site, timeout 305s). Process `readyz` is compose-internal only. The MCP workspace copies the Console origin plus `/mcp` and the Console origin plus `/mcp/entity`. There is no second public hostname. The host port defaults to `3001` (`REFRAQ_WEB_PORT`) so a local Console on `127.0.0.1:3000` can keep running. Bind local `next dev` to `127.0.0.1` so the office network cannot open the sandbox Console.

Session cookie `Secure` follows browser-facing HTTPS. The web `proxy.ts` hop for `/api` overwrites `X-Forwarded-Proto` from `REFRAQ_BROWSER_FACING_PROTO` (default `http`) and `X-Forwarded-Host` from `REFRAQ_BROWSER_FACING_HOST` when set, otherwise from a loopback request Host; it does not pass through client-supplied public Hosts. The API then reads those stamped headers (then a loopback request Host). `REFRAQ_ENV=prod` does not force `Secure`. HTTP sites must keep the Session; set `REFRAQ_BROWSER_FACING_PROTO=https` on web when TLS terminates in front of the Console. Set `REFRAQ_BROWSER_FACING_HOST` on web and API to the browser-facing Console host when it is not loopback.

## 4. Variable Ownership

### Backend-Owned Variables

- `REFRAQ_ENV`
- `REFRAQ_API_HOST`
- `REFRAQ_API_PORT`
- `REFRAQ_MCP_HOST` (Metadata MCP process bind; local default `127.0.0.1`)
- `REFRAQ_MCP_PORT` (Metadata MCP process port; default `8001`)
- `REFRAQ_ENTITY_MCP_HOST` (Entity MCP process bind; local default `127.0.0.1`)
- `REFRAQ_ENTITY_MCP_PORT` (Entity MCP process port; default `8002`)
- `REFRAQ_STORE_BACKEND` (`persistent` default; `memory` tests only)
- `TZ` (process timezone; default UTC in examples/images; not `APP_TIMEZONE`)
- `DATABASE_URL` (required when `persistent`)
- `ENTITY_DATABASE_URL` (entity-database owner connection; unprefixed because it is a connection setting. Required on persistent API and on the worker; must name a database other than the metadata database and a role that is not a superuser. A persistent API or worker without it must fail fast. Metadata MCP, Entity MCP, and Beat do not open the owner pool. Entity MCP compares it, when set, to the reader database)
- `ENTITY_READER_DATABASE_URL` (entity-database reader connection as `refraq_reader`; required on persistent API and on Entity MCP; fail-fast when missing, when the database is the metadata database, or when the role is a superuser or `BYPASSRLS`)
- `ENTITY_SIGNER_DATABASE_URL` (entity-database signer connection as `refraq_signer`; required on Entity MCP; same database as the reader; fail-fast when missing or when the role is a superuser or `BYPASSRLS`. Bootstrap reads the signer password from this URL. The signer may execute only `acl.ensure_signing_key()`)
- `ENTITY_ADMIN_DATABASE_URL` (administrative connection used only by `python -m backend.entity.bootstrap`; never set on runtime processes)
- `REDIS_URL` (required when `persistent`)
- `ADMIN_SESSION_SECRET` (reserved for future signed-cookie usage; v1 sessions are server-managed)
- `INITIAL_ADMIN_ACCOUNT`
- `INITIAL_ADMIN_PASSWORD`
- `REFRAQ_SECRETS_MASTER_KEY` (required to store/read Source secrets)
- `CELERY_BROKER_URL` (required when running Celery worker/beat; default same host Redis DB `2`)
- `REFRAQ_BROWSER_FACING_HOST` (optional; host or `host:port`, no scheme) — canonical Console host for OIDC `redirect_uri`; when unset, only a loopback Host is used
- `REFRAQ_CATALOG_FAIL_SAFE_THRESHOLD` (retired; ignored and reported at startup)
- `REFRAQ_EMBEDDING_API_URL`, `REFRAQ_EMBEDDING_MODEL`, `REFRAQ_EMBEDDING_TIMEOUT_SEC`, `REFRAQ_PEEK_SLOTS` (retired; ignored and reported at startup)
- `REFRAQ_INTEGRATION_DATABASE_URL` (pytest `@pytest.mark.integration` only; default `…/refraq_test`)
- `REFRAQ_INTEGRATION_REDIS_URL` (integration only; default `redis://127.0.0.1:6379/1`)
- `REFRAQ_INTEGRATION_CELERY_BROKER_URL` (integration only; default `redis://127.0.0.1:6379/3`)
- `REFRAQ_PROCESS_ROLE` (`api` / `mcp` / `worker` / `entity_mcp`; declared per process at the entry, not in a shared `.env`)
- `REFRAQ_DB_POOL_SIZE`, `REFRAQ_DB_MAX_OVERFLOW`, `REFRAQ_DB_POOL_TIMEOUT_SEC`, `REFRAQ_DB_POOL_RECYCLE_SEC`, `REFRAQ_DB_STATEMENT_TIMEOUT_MS` (SQLAlchemy platform pool; role defaults in §2)
- `REFRAQ_ENTITY_DB_POOL_SIZE`, `REFRAQ_ENTITY_DB_MAX_OVERFLOW`, `REFRAQ_ENTITY_DB_POOL_TIMEOUT_SEC`, `REFRAQ_ENTITY_DB_POOL_RECYCLE_SEC` (entity pool; api, worker, and the Entity MCP reader pool; role defaults in §2. The signer pool does not use these)
- `REFRAQ_ENTITY_DB_SCHEMA` (retired; entity schemas are fixed; ignored and reported at startup)
- `REFRAQ_HTTP_MAX_INFLIGHT`, `REFRAQ_THREAD_TOKENS`, `REFRAQ_ADMISSION_SLOTS`, `REFRAQ_ADMISSION_ACTOR_SHARE` (API/MCP runtime capacity; ADR 0040 / 0045)
- Postgres `shared_buffers` / `effective_cache_size` / `work_mem` / container `shm_size` (database supply; ADR 0040; set on the Compose `postgres` service, not as process env)
- `REFRAQ_PROMETHEUS_URL` (optional series-store URL; default `http://prometheus:9090`. Not a capacity knob and not one of `REFRAQ_HTTP_MAX_INFLIGHT`, `REFRAQ_THREAD_TOKENS`, `REFRAQ_ADMISSION_SLOTS`, or `REFRAQ_ADMISSION_ACTOR_SHARE`)

The optional deployer-supplied backend settings `REFRAQ_MIRROR_TARGET`, `REFRAQ_NOTIFICATION_REVIEWED_ORIGINS` and `REFRAQ_NOTIFICATION_DELIVERY` follow §§1.2-1.3. They are not browser settings and must never use a `NEXT_PUBLIC_` name. Backend dotenv loading accepts them. The site Compose environment must explicitly pass the applicable settings to the process that uses them, using a site-owned override or protected process environment. Putting an arbitrary key in the Compose interpolation `.env` alone does not inject it into containers. The repository backend/deploy examples and site Compose do not supply these optional policies or approved numeric values.

### Frontend-Owned Variables

- `NEXT_PUBLIC_REFRAQ_API_BASE_URL` (browser-facing base; default `/api`)
- `REFRAQ_API_UPSTREAM` (internal backend origin; build-time rewrite target and runtime server-rendering target; never exposed to browser code)
- `REFRAQ_MCP_UPSTREAM` (internal Metadata MCP origin; runtime stream target for `/mcp` only; never `readyz`)
- `REFRAQ_ENTITY_MCP_UPSTREAM` (internal Entity MCP origin; runtime stream target for `/mcp/entity` only; default `http://127.0.0.1:8002`; timeout 305s; never `readyz`)
- `NEXT_PUBLIC_DEFAULT_LOCALE`
- `REFRAQ_BROWSER_FACING_PROTO` (`http` | `https`; default `http`) — stamped onto `/api` rewrite as `X-Forwarded-Proto` for Session `Secure`; set `https` when TLS terminates in front of the Console
- `REFRAQ_BROWSER_FACING_HOST` (optional; host or `host:port`, no scheme) — stamped onto `/api` rewrite as `X-Forwarded-Host` for OIDC callback origin; when unset, only a loopback request Host is stamped

### Deploy-Owned Variables

- `POSTGRES_PASSWORD` (platform Postgres password; Compose interpolation; not published to the host)
- `REFRAQ_WEB_PORT` (host port for the web service; default `3001`)
- `REFRAQ_BROWSER_FACING_PROTO` (optional; forwarded to web; default `http`)
- `REFRAQ_BROWSER_FACING_HOST` (optional; forwarded to web and API; browser-facing Console host or `host:port`)
- `REFRAQ_API_UPSTREAM` (web build argument and web runtime environment; both use the internal API origin `http://api:8000` on a site)
- `REFRAQ_MCP_UPSTREAM` (web runtime; site value `http://mcp:8001`; not a public origin)
- `REFRAQ_ENTITY_MCP_UPSTREAM` (web runtime; site value `http://entity-mcp:8002`; not a public origin)
- `ENTITY_SIGNER_PASSWORD` (Compose interpolation for `refraq_signer`; not read by the process. The process and bootstrap read `ENTITY_SIGNER_DATABASE_URL`)
- `REFRAQ_MONITOR_PASSWORD` (required Compose interpolation for role `refraq_monitor`; URL-safe characters only, no `@ : / % ? #`; `${REFRAQ_MONITOR_PASSWORD:?set REFRAQ_MONITOR_PASSWORD}` refuses the Postgres collector and the monitor-role one-shot when unset)

## 5. Process timezone (`TZ`)

- Site and image default is process `TZ=UTC` (backend Dockerfile `ENV`, Compose service environment, `.env.example`).
- Override only via the standard `TZ` environment variable; do **not** invent `APP_TIMEZONE`.
- Production must run UTC. Instant semantics do not depend on process TZ, but default UTC avoids accidental local interpretation in libraries that read `TZ`.
- IANA zone data: declare Python package `tzdata` so Schedule Timezone / `zoneinfo` works without host OS zoneinfo.
- Full Instant / Schedule Timezone rules: [`docs/conventions-time.md`](conventions-time.md).

## 6. Usage Rules

- Use `.env.example` as the canonical template
- Keep docs and env examples in sync
- Do not commit real secrets
- Do not change API port in code and forget to update frontend env
- The initial admin password is meant for first-time local development only; rotate it before any non-local site. Site compose reads a live `.env` outside the git tree; do not leave example secrets in a live stack.
- Missing `DATABASE_URL` / `REDIS_URL` with `persistent` must fail fast; never silently fall back to memory
- Missing `ENTITY_DATABASE_URL` on a persistent API or persistent worker, or missing `ENTITY_READER_DATABASE_URL` on a persistent API or on Entity MCP, must fail fast; never silently fall back to an in-process recording table port. An entity URL that names the metadata database, or a superuser role, must fail fast. A persistent API or worker must also fail fast when `entity_data`, `entity_access`, `acl`, or `channel_dataset` is absent on the entity database. Entity MCP must also fail fast when `ENTITY_SIGNER_DATABASE_URL` is missing, names a different database from the reader, or logs in as a superuser or `BYPASSRLS` role. Metadata MCP and Beat do not open an entity pool and do not require the variables at process start. `/readyz` does not probe the entity database.
- Settings dotenv load order: repo-root `.env` then `backend/.env` (later wins). Prefer `backend/.env` as the local canonical file
- Integration tests must not reuse interactive `DATABASE_URL` / `REDIS_URL`; they use `REFRAQ_INTEGRATION_*` defaults so Compose live data stays intact

## 7. Initial Admin Seeding

On backend startup, if the user store is empty, default roles are ensured and a single `super_admin` user is created from `INITIAL_ADMIN_ACCOUNT` and `INITIAL_ADMIN_PASSWORD`. The display name defaults to the account value. Subsequent restarts do not re-seed. Multiple replicas remain safe because seeding is gated on an empty user store.

## 8. Celery Worker And Beat

Platform async runtime (`docs/adr/0006-celery-platform-async-runtime.md`):

- API process: create durable Job rows and enqueue via Celery after commit (`docs/api-contracts-jobs.md`)
- Worker: `celery -A backend.worker.app worker` — concurrency is a deployment concern, not a **System Parameter** (`docs/business-system-parameters.md` §5.2). No flag is passed, so Celery's own default (one process per CPU) applies; a deployment that needs to pin capacity passes `--concurrency` on this command line, and sizes it together with the replica count. The local `.vscode` launch configuration pins `--pool=solo --concurrency=1` because a debugger needs a single process; it overrides no stored value
- Beat (single replica): `celery -A backend.worker.app beat` — reads **Scheduled Task** rows from Postgres; do not run multiple Beat replicas. Loop `max_interval` and schedule reload `sync_every` are in-code constants (`BEAT_MAX_INTERVAL_SEC = 5`, `BEAT_SYNC_EVERY_SEC = 30`; `docs/business-system-parameters.md` §5.2). An overdue in-memory commitment is dispatched **once** until the next reload (or `BEAT_SYNC_EVERY_SEC` retry if the store row is still overdue); Beat does not tight-loop send while the worker consumes the tick. Occupancy lost-detection (`job_lost_detection_sec`, seed 60 → `JOB_WORKER_LOST`) is driven by the system reaper Scheduled Task on this Beat. Beat sync copies that same lost-detection value onto the reaper row's `interval_seconds` and does not recompute `next_run_at`, so tightening may wait for the current tick. If Beat is stopped, that reaping stops — starting only the API does not recover false `RUNNING` Jobs.
- Worker and Beat share `DATABASE_URL`, `CELERY_BROKER_URL`, and (when decrypting secrets) `REFRAQ_SECRETS_MASTER_KEY`. The worker also opens `ENTITY_DATABASE_URL` as a separate engine and pool. A persistent worker that cannot open that URL is not a healthy executor: startup fails, and `entity_reconcile` / `entity_table_drop` / `entity_access_views` cannot succeed by falling back to an in-process recording port. Persistent API opens the same owner URL plus `ENTITY_READER_DATABASE_URL` for the **Entity Data API**. Beat and the Metadata MCP process do not open an entity pool. The Entity MCP process opens `ENTITY_READER_DATABASE_URL` and `ENTITY_SIGNER_DATABASE_URL`, and does not open the owner URL. API and worker still sign with the owner pool.
- After Foundation Upgrade, restart worker and Beat. Code on disk does not change a live process's registered names; a leftover worker after a `task_name` revision yields Beat `NotRegistered` and structure clocks that never mint. Confirm with `celery -A backend.worker.app inspect registered` that registered names match Scheduled Task rows.
- No Celery result backend; operator-visible status and run logs live on Postgres Job rows (`log_body`; later large attachments if needed)
- Do not run long collection inside the interactive API request path (`docs/adr/0004-redis-queue-for-ingestion.md`)

## 9. Secret Handling

- Never commit real `REFRAQ_SECRETS_MASTER_KEY`, admin passwords, or Source database passwords
- Rotating `REFRAQ_SECRETS_MASTER_KEY` requires a documented re-encrypt procedure before it is safe in production; until then treat the key as stable per environment

## 10. Local Identity Provider (Keycloak)

Root `compose.yaml` includes a development Keycloak. `deploy/compose.yaml` does not; production Identity Provider configuration is an operator concern.

Start it with the rest of the local stack (`docker compose up`). Realm import is `dev/keycloak/refraq-realm.json`. The service publishes host port `8080`. When that port is already taken, remap the host side only (for example `18080:8080`) and use the new port in the issuer and discovery URLs below and in the Console provider configuration; the realm redirect URIs point at the Console on `3000` and do not change.

| Item | Local value |
| --- | --- |
| Admin console | `http://127.0.0.1:8080` (`admin` / `admin`) |
| Issuer | `http://127.0.0.1:8080/realms/refraq` |
| Discovery | `http://127.0.0.1:8080/realms/refraq/.well-known/openid-configuration` |
| Client id | `refraq` |
| Client secret | `refraq-dev-secret` |
| Redirect URIs | `http://127.0.0.1:3000/api/auth/sso/*`, `http://localhost:3000/api/auth/sso/*` |
| Group claim | `groups` (full path) |
| Fixture `alice` / `alice` | group `/dept/analytics` |
| Fixture `bob` / `bob` | no groups |

These fixture passwords are local-only. Do not reuse them outside development.

Console configuration (Administration → Identity Providers):

- Issuer and client values from the table
- Scopes `openid`, `profile`, `email`
- Group claim `groups`
- For auto-provisioning: allowlist `/dept/analytics` and a default Role that is not `super_admin` and does not include `users:write`, `roles:write`, or `identity_providers:write`

Walkthrough against that realm (Management Console on `http://127.0.0.1:3000`):

1. Auto-provision: enable auto-provisioning, sign in as `alice`. A User `alice` is created with `identity_source=oidc`.
2. Pending queue: sign in as `bob`. No Session is issued; `/login?error=AUTH_SSO_NOT_ADMITTED` and a pending identity appear for `users:write`. Copy exact group strings from that record when configuring an allowlist.
3. Account collision: create a local User whose `account` matches a later IdP `preferred_username` (for example local `alice` before the first alice SSO). The assertion is queued, not silently bound. Claim it to the existing User or create a new account from the editable prefill.
4. Unfederation: from the Users list, set a new local password. Later SSO follows unbound admission.
5. Every-login group check: with auto-provisioning on, remove alice from `/dept/analytics` in Keycloak and sign in again. No new Session, User unchanged, no pending row.
6. Disable or delete the provider: the confirmation shows bound-user count and may optionally disable those Users (clears Sessions; disabled status rejects PATs).
