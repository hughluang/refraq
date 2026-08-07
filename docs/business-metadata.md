# refraq Business Rules: Metadata Foundation

## 1. Scope

This document defines the **metadata foundation** phase for refraq: Sources, Connections, metadata ingestion, catalog browsing, semantics and join enrichment, controlled read-only query, Management Console mounts under the `metadata` nav group, MCP exposure, and the companion system base required to operate that surface safely.

Related boundaries:

- **Management Foundation** (login, Session, Users, Roles) remains the enabling layer; rules live in `docs/business-login-auth.md`.
- **User PAT** rules live in `docs/business-user-tokens.md`.
- Console shell and module registration contract: `docs/business-management-console.md`.
- Terminology: `docs/glossary.md` and root `CONTEXT.md`.
- Source / catalog identity: `docs/adr/0007-source-owns-catalog-identity.md`.
- Job shape: `docs/adr/0008-job-generic-input.md`.
- This phase does **not** define Business Entity, Data Product catalog, Serving delivery, or Access Contract marketplace workflows.

These rules are the working source of truth unless superseded by a later ADR or business document.

## 2. Problem And Decision

### 2.1 Gap

Foundation P0 delivered people, permissions, and Console mount contract. Product identity still requires an authoritative in-product path from registered data origins to governed data outputs. Without Source / Connection / collection / MCP inside refraq, later Entity and Data Product work has no substrate.

### 2.2 Confirmed Direction

1. **Productize into refraq** — Source registration, ingestion, catalog, MCP, and companion base live in this repository; external `dbmeta` is design reference only.
2. **Empty rebuild** — do not migrate or dual-read legacy `dbmeta` data; operators re-register Sources and re-collect.
3. **Phase north star** — metadata capability face comparable to structure + semantics + join + controlled query, plus companion base (secrets, Celery worker/beat, User PAT, management audit, permissions, `metadata` nav).
4. **Deliver in slices A→B→C→D** with companion base started alongside A — not a single big-bang milestone.
5. **Defer** Entity, Data Product catalog, Serving, Access marketplace, Client management, and Console P1 cosmetics (scope/search/theme/notifications).
6. **Source is the catalog owner** — not limited to enterprise systems; `kind` leaves room for later non-live origins (for example CSV).

## 3. Principles

1. **Source is the business/catalog identity** (including database-kind scope such as database name and schema); **Connection is only live reachability and credentials** (host, port, user/secret, engine).
2. **Catalog Object identity is Source-scoped only** — not Connection-scoped.
3. **Long work never blocks the API process** — enqueue **Jobs**; workers execute.
4. **Credentials are secrets** — encrypted at rest in Postgres; never returned in full by APIs; never written to Settings Override or logs.
5. **Backend Permission catalog is authoritative** for Console, REST, and MCP.
6. **MCP authenticates a User** (Session or User PAT), not an anonymous service key and not a Client in this phase.
7. **Write honesty** for semantics and joins — evidence-backed join edges; incomplete understanding stays incomplete (open questions allowed); do not invent business meaning.
8. **Controlled query is read-only** with platform guards, not a general SQL console.
9. **Kind extensibility** — slice A implements Source `kind=database` only; other Source kinds are planned extension points, not delivered in this phase.
10. **Job is an independent durable execution** — discriminated by Job `kind`, carrying a generic `input` payload; not owned by Connection. Domains provide enqueue/list facades.

## 4. Object Model

### 4.1 Source

Fields (business meaning):

| Field | Notes |
| --- | --- |
| id | Stable technical identifier |
| key | Stable unique key (e.g. `mes-prod`, `u9-uat`) |
| name | Display name |
| kind | Collection modality; slice A: `database`. Catalog may grow (e.g. `file`) without renaming Source |
| status | `active` / `disabled` |
| description | Optional |
| database_name | Required when `kind=database`; catalog/DB scope (engine-specific: database, service/SID, etc.) |
| schema_filter | Optional when `kind=database`; schema (or equivalent) scope for collection |

Rules:

- Distinct environments or physical instances are **distinct Sources** (separate keys and catalogs).
- For `kind=database`, **business/catalog scope** (what is being integrated: database name, schema filter) lives on the Source — not on Connection.
- Disabling a Source blocks new ingestion until re-enabled (existing catalog snapshots remain readable unless later retention rules say otherwise).
- Non-`database` kinds are out of scope for slice A implementation; models and APIs must not hard-code that every Source requires a Connection. Kind-specific scope fields for non-database kinds arrive with those kinds.

### 4.2 Connection

| Field | Notes |
| --- | --- |
| id | Stable technical identifier |
| source_id | Parent Source (`kind=database` in slice A) |
| name | Display name |
| engine | `postgresql` \| `mssql` \| `oracle` in slice A (wire/protocol family) |
| host / port | Reachability; engine-specific endpoint extras allowed (e.g. SSL flags) without carrying catalog scope |
| secret_ref | Encrypted credential material (username/password or equivalent; never plaintext in API responses) |
| status | `active` / `disabled` |

Rules:

- Connection carries **only** how to reach and authenticate the live endpoint. It does **not** own `database_name` / schema scope.
- Ingestion and controlled query compose runtime access as **Source scope + Connection endpoint/credentials**.
- Cardinality for `kind=database`: Source **0 or 1** Connection (strict **1:1** once registered). Creating a second Connection on the same Source is rejected.
- Future non-live kinds may use zero Connections and a different attachment; do not force every Source kind through Connection.
- Endpoint or credential change is a **switch on the same Connection** (update host/port/engine and/or rotate secret) — not a second Connection row, and not a new Source.
- Prefer the authoritative / primary endpoint; do not register read replicas as alternate Connections for the same Source.
- Connection is not the catalog identity; rotating host/port/secret must not mint a new Source or orphan Catalog Objects of that Source.

### 4.3 Job

Platform durable asynchronous execution (see root `CONTEXT.md`). Metadata structure collection is one Job `kind`, not the definition of Job.

| Field | Notes |
| --- | --- |
| id | Job id |
| kind | `structure` \| `semantics_refresh` \| … as slices/domains add |
| status | `queued` \| `running` \| `succeeded` \| `failed` \| `cancelled` |
| input | Generic object; domain interprets per `kind`. Slice A database structure: includes `source_id` and `connection_id` |
| created_by | User id |
| timestamps / error summary | Operational visibility |

Rules:

- Job is **not** owned by Connection or Source. Do not treat `connection_id` / `source_id` as universal Job columns — they live in `input` when required.
- Metadata enqueue/list for Source-scoped work uses the **Source facade** (`docs/api-contracts-jobs.md`): `POST/GET /sources/{id}/jobs`.
- Creating a structure Job requires `jobs:run` and, for database Sources, a usable Connection secret in `input`.
- Jobs are durable records; queue transport is Redis-backed via Celery (see `docs/adr/0004-redis-queue-for-ingestion.md`, `docs/adr/0006-celery-platform-async-runtime.md`).
- Successful structure Jobs write/refresh **Catalog Objects** on the Source identified in `input`.
- Console module id `jobs`.

### 4.4 Catalog Object And Columns

Collected structure includes object identity **under Source**, object type, name, columns (name, type, nullable), and DDL when available.
Optional provenance may record that the Source's Connection last collected the snapshot; provenance is not part of identity.
Later slices attach business semantics and join edges to these objects/columns.

### 4.5 Future foresight — non-database Source kinds (not delivered in A–D)

Planned shape only; no Attachment APIs, ORM, or Console flows in this phase:

- A later Source `kind` (for example `file`) remains a **Source** with Catalog Objects under it — not a parallel identity.
- Live **Connection** stays optional (often zero). File bytes or external URI are expected to use a distinct **Attachment** (or equivalent) concept — not Connection.
- Structure refresh is still a **Job** with `kind=structure`; domain targets (Source, Attachment id/URI, format hints) live in Job `input`, via a Source (or kind-specific) facade.
- Do not force file/static origins through Connection; do not promote Attachment fields onto universal Job columns.
- Full Attachment cardinality, versioning, blob storage, and reference-data governance remain out of scope until that phase is grilled and documented.

## 5. Delivery Slices

| Slice | Business delivery |
| --- | --- |
| **Companion base** (with A) | User PAT; Connection secret encryption; Celery worker/beat + Scheduled Task; Job status APIs; Permission catalog extensions; `metadata` Console nav group; management-plane audit |
| **A** | Source/Connection CRUD for `kind=database`; PostgreSQL + MSSQL + Oracle structure collection; Console browse; MCP read-only structure tools |
| **B** | Object/column business name and description read/write via API and MCP |
| **C** | Join graph with evidence threshold for writes |
| **D** | Controlled read-only query (`run_sql`) with guards and audit |

Slice B–D must not ship before A’s structure substrate exists for the same Source.
Non-database Source kinds (e.g. CSV) are **not** in slices A–D.

## 6. Permission Catalog (Metadata)

Fixed catalog additions (exact strings are normative for Roles UI):

| Permission | Meaning |
| --- | --- |
| `sources:read` | List/view Sources and Connections (non-secret fields) |
| `sources:write` | Create/update/disable Sources and Connections; set secrets |
| `metadata:read` | Browse Catalog Objects, columns, DDL, semantics, joins |
| `metadata:write` | Write semantics and join edges |
| `jobs:run` | Enqueue/cancel **Jobs** (structure and later kinds) via domain facades; view Jobs on those facades |
| `query:run` | Execute controlled read-only SQL against a Connection |
| `tokens:read` | List own User PAT metadata (never full token after creation) |
| `tokens:write` | Create/deactivate/restore/soft-delete (deactivated only) own User PATs |
| `audit:read` | Read management audit events |

Rules:

- Seeded `super_admin` always receives the full current catalog (including these entries) via Foundation Upgrade / System Role ensure.
- Seeded `operator` does **not** receive `sources:write`, `metadata:write`, `jobs:run`, `query:run`, `tokens:*`, or `audit:read` by default.
- No object-level ACL in this phase.
- Nav visibility for modules uses each module’s `list` action Permission (same Console Module contract as Foundation).

## 7. Console Modules (`metadata` Group)

Group id: `metadata`.

Initial modules (ids stable):

| Module id | Purpose | list permission |
| --- | --- | --- |
| `sources` | Sources and nested Connection management | `sources:read` |
| `catalog` | Browse Catalog Objects / columns | `metadata:read` |
| `jobs` | Job list and trigger entry points | `jobs:run` (list) |

User PAT management is **not** in this group; see `docs/business-user-tokens.md` (Administration module `tokens`).

## 8. Secret Storage

- Connection credentials are stored encrypted in Postgres using an application master key from environment (`REFRAQ_SECRETS_MASTER_KEY`).
- Decryption occurs only in worker/API paths that need to open a Connection.
- APIs may acknowledge `has_secret` / last-rotated metadata; they must not return plaintext secrets.
- External Vault/KMS is out of scope for this phase (see `docs/adr/0005-app-encrypted-connection-secrets.md`).

## 9. Structure Job Runtime (database)

- Source facade validates and enqueues; worker processes execute connectors.
- Slice A connectors: **PostgreSQL**, **MSSQL**, **Oracle**.
- Structure collection persists object inventory, columns, and DDL when obtainable, keyed by Source.
- **Current catalog** is authoritative (not a per-Job version history). Natural key:
  `(source_id, schema_name, name, object_type)`. Surrogate ids are preserved across successful refreshes.
- **Success-only commit:** only a Job that reaches a complete successful collect may mutate catalog.
  Failed, cancelled, or aborted collects leave the prior successful catalog unchanged (no absent marks).
- **In-scope absent:** after a complete collect, objects previously present within the Job's schema
  scope (`schema_filter` when set) that are missing from the collect are marked `is_present=false`
  (tombstone). Out-of-scope objects are not bulk-absent when the filter shrinks.
- **Fail-safe:** if the fraction of in-scope present objects that would become absent exceeds
  `REFRAQ_CATALOG_FAIL_SAFE_THRESHOLD` (default `0.75`), the Job fails with `JOB_FAIL_SAFE` and
  writes nothing.
- **Semantics preservation:** structure upserts whitelist structural columns only; never overwrite
  `business_name` / `business_description` (or later join edges).
- **Structure single-flight:** at most one non-terminal `kind=structure` Job per Source
  (`JOB_ALREADY_ACTIVE`). Enforced on the Job store (not a Celery lock). Re-run = new Job after
  terminal status.
- Collectors compose **Source scope + Connection endpoint/credentials**. Introspection uses
  engine-native catalogs (`pg_catalog`, `sys.*`, `ALL_`/`DBA_`).
- Collection account guidance: prefer least privilege (PostgreSQL schema `USAGE` + catalog read;
  MSSQL `VIEW DEFINITION`; Oracle `SELECT_CATALOG_ROLE` or equivalent).

## 10. Semantics And Joins (Slices B–C)

- Semantics fields: business name, business description; optional enum catalog later.
- Writes are additive/corrective; do not clear existing semantics with nulls unless an explicit clear API exists.
- Join edges require evidence (verified SQL/DDL or successful validation); name-similarity alone is insufficient.
- Open questions may be recorded when evidence is incomplete.

## 11. Controlled Query (Slice D)

- Allowed: single read-only statement (SELECT or engine-equivalent).
- Reject: DDL, DML, multi-statement batches, and anything the platform cannot classify as read-only.
- Enforce timeout and maximum row count.
- Execute through the Source's Connection; audit every attempt (statement summary or hash, User, Connection, outcome).
- Prefer a Connection DB user that is itself read-only as defense in depth; platform guards remain mandatory.

## 12. MCP

- MCP tools are a first-class product surface backed by the same domain services and Permissions as HTTP APIs.
- Authentication: User Session (where applicable) or **User PAT** Bearer.
- Tool availability follows slices (structure read in A; semantics write in B; joins in C; query in D).
- Contract detail: `docs/api-contracts-metadata-mcp.md`.

## 13. Management Audit

Persist management-plane events for at least:

- Source / Connection create/update/disable and secret set/rotate
- Job enqueue / cancel / terminal failure (summary)
- Semantics and join writes
- User PAT create / deactivate / restore / soft-delete
- Controlled query execution

Each event: actor User id, timestamp, resource type/id, action, result (`success` / `failure`), optional detail payload without secrets.
Full platform audit of every login/Settings/Users path is out of scope for this phase (Foundation login paths may remain hook-ready only).

## 14. Success Criteria (Phase)

1. An authorized User can register database Sources and Connections for PostgreSQL, MSSQL, and Oracle under Console group `metadata`, enqueue structure **Jobs**, and browse Catalog Objects under each Source.
2. MCP clients using a User PAT can exercise slice-appropriate tools; mutating calls are attributable to that User in audit.
3. Connection secrets are never stored or logged in plaintext; long-running Jobs do not block the API process.
4. Roles can grant read-only metadata access without granting Connection write, query, or PAT management.
5. Documentation under `docs/` matches behavior; refraq is the sole authoritative registry (no `dbmeta` dual-read).

## 15. Non-Goals

- Business Entity model and UI
- Data Product catalog / discovery / owners marketplace
- Serving / delivery layers
- Access request and contract approval workflows
- Client / machine-token management APIs
- Console P1: scope switcher implementation, global search implementation, theme workshops, notification center
- Persisted multi-replica Settings Override (unless a concrete metadata-config blocker appears)
- Object-level ACL
- Write SQL / unrestricted SQL consoles
- Migrating or dual-reading legacy `dbmeta` datasets
- Pre-creating empty domain packages before implementation code arrives
- Multiple Connections per database Source (standby rows, replica targets, or collection-active flags)
- Treating read replicas as alternate Connection targets for the same Source
- Delivering non-database Source kinds (CSV/file import, Attachment APIs, etc.) in this phase — foresight only in §4.5

## 16. References

- `docs/adr/0007-source-owns-catalog-identity.md`
- `docs/adr/0008-job-generic-input.md`
- `docs/business-user-tokens.md`
- `docs/business-management-console.md`
- `docs/api-contracts-sources.md`
- `docs/api-contracts-jobs.md`
- `docs/api-contracts-metadata.md`
- `docs/api-contracts-tokens.md`
- `docs/api-contracts-audit.md`
- `docs/api-contracts-metadata-mcp.md`
- `docs/adr/0004-redis-queue-for-ingestion.md`
- `docs/adr/0006-celery-platform-async-runtime.md`
- `docs/adr/0005-app-encrypted-connection-secrets.md`
