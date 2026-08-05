# refraq Business Rules: Metadata Foundation

## 1. Scope

This document defines the **metadata foundation** phase for refraq: Source Systems, Connections, metadata ingestion, catalog browsing, semantics and join enrichment, controlled read-only query, Management Console mounts under the `metadata` nav group, MCP exposure, and the companion system base required to operate that surface safely.

Related boundaries:

- **Management Foundation** (login, Session, Users, Roles) remains the enabling layer; rules live in `docs/business-login-auth.md`.
- **User PAT** rules live in `docs/business-user-tokens.md`.
- Console shell and module registration contract: `docs/business-management-console.md`.
- Terminology: `docs/glossary.md` and root `CONTEXT.md`.
- This phase does **not** define Business Entity, Data Product catalog, Serving delivery, or Access Contract marketplace workflows.

These rules are the working source of truth unless superseded by a later ADR or business document.

## 2. Problem And Decision

### 2.1 Gap

Foundation P0 delivered people, permissions, and Console mount contract. Product identity still requires an authoritative in-product path from enterprise systems to governed data outputs. Without Source / Connection / collection / MCP inside refraq, later Entity and Data Product work has no substrate.

### 2.2 Confirmed Direction

1. **Productize into refraq** — Source registration, ingestion, catalog, MCP, and companion base live in this repository; external `dbmeta` is design reference only.
2. **Empty rebuild** — do not migrate or dual-read legacy `dbmeta` data; operators re-register Sources and re-collect.
3. **Phase north star** — metadata capability face comparable to structure + semantics + join + controlled query, plus companion base (secrets, queue/worker, User PAT, management audit, permissions, `metadata` nav).
4. **Deliver in slices A→B→C→D** with companion base started alongside A — not a single big-bang milestone.
5. **Defer** Entity, Data Product catalog, Serving, Access marketplace, Client management, and Console P1 cosmetics (scope/search/theme/notifications).

## 3. Principles

1. **Source System is the business identity; Connection is the technical attachment.**
2. **Metadata identity must be instance-aware** via Connection **Instance Key** (and optional filter scope).
3. **Long collection never blocks the API process** — enqueue Ingestion Jobs; workers execute.
4. **Credentials are secrets** — encrypted at rest in Postgres; never returned in full by APIs; never written to Settings Override or logs.
5. **Backend Permission catalog is authoritative** for Console, REST, and MCP.
6. **MCP authenticates a User** (Session or User PAT), not an anonymous service key and not a Client in this phase.
7. **Write honesty** for semantics and joins — evidence-backed join edges; incomplete understanding stays incomplete (open questions allowed); do not invent business meaning.
8. **Controlled query is read-only** with platform guards, not a general SQL console.

## 4. Object Model

### 4.1 Source System

Fields (business meaning):

| Field | Notes |
| --- | --- |
| id | Stable technical identifier |
| key | Stable unique key (e.g. `mes`, `u9`) |
| name | Display name |
| system_type | Business/system family label (opaque string catalog may grow) |
| status | `active` / `disabled` |
| description | Optional |

Rules:

- Disabling a Source System blocks new ingestion and new Connections from becoming active for collection until re-enabled (existing catalog snapshots remain readable unless later retention rules say otherwise).

### 4.2 Connection

| Field | Notes |
| --- | --- |
| id | Stable technical identifier |
| source_system_id | Parent Source System |
| name | Display name |
| engine | `postgresql` \| `mssql` \| `oracle` in slice A |
| instance_key | Required; unique per Source System |
| endpoint | Host/port and engine-specific locator fields |
| database_name / schema filter | Scope for collection where applicable |
| secret_ref | Encrypted credential material (never plaintext in API responses) |
| status | `active` / `disabled` |
| is_collection_active | Whether this Connection may run full metadata ingestion |

Rules:

- Cardinality: Source System **1—N** Connection.
- Runtime policy for early slices: at most **one** Connection with `is_collection_active=true` per `(source_system_id, instance_key)` for full metadata ingestion.
- Prefer **one Connection + filter** over multiple unscoped full-ingest Connections that target the same logical asset set.
- Parallel multi-Connection ingestion for the same Source System is a later runtime relaxation and requires scope-aware delete semantics before enablement.
- Read replicas are not a default Connection purpose for metadata collection; prefer primary / authoritative endpoints.

### 4.3 Ingestion Job

| Field | Notes |
| --- | --- |
| id | Job id |
| connection_id | Target Connection |
| kind | `structure` \| `semantics_refresh` \| … as slices add |
| status | `queued` \| `running` \| `succeeded` \| `failed` \| `cancelled` |
| created_by | User id |
| timestamps / error summary | Operational visibility |

Rules:

- Creating a job requires `ingestion:run` and a usable Connection secret.
- Jobs are durable records; queue transport is Redis-backed (see `docs/adr/0004-redis-queue-for-ingestion.md`).

### 4.4 Catalog Object And Columns

Collected structure includes object identity (under Source System + Instance Key), object type, name, columns (name, type, nullable), and DDL when available.
Later slices attach business semantics and join edges to these objects/columns.

## 5. Delivery Slices

| Slice | Business delivery |
| --- | --- |
| **Companion base** (with A) | User PAT; Connection secret encryption; Redis queue + worker; Job status APIs; Permission catalog extensions; `metadata` Console nav group; management-plane audit |
| **A** | Source/Connection CRUD; PostgreSQL + MSSQL + Oracle structure collection; Console browse; MCP read-only structure tools |
| **B** | Object/column business name and description read/write via API and MCP |
| **C** | Join graph with evidence threshold for writes |
| **D** | Controlled read-only query (`run_sql`) with guards and audit |

Slice B–D must not ship before A’s structure substrate exists for the same Connection.

## 6. Permission Catalog (Metadata)

Fixed catalog additions (exact strings are normative for Roles UI):

| Permission | Meaning |
| --- | --- |
| `sources:read` | List/view Source Systems and Connections (non-secret fields) |
| `sources:write` | Create/update/disable Sources and Connections; set secrets |
| `metadata:read` | Browse Catalog Objects, columns, DDL, semantics, joins |
| `metadata:write` | Write semantics and join edges |
| `ingestion:run` | Enqueue/cancel structure (and later) ingestion jobs; view jobs for permitted sources |
| `query:run` | Execute controlled read-only SQL against a Connection |
| `tokens:read` | List own User PAT metadata (never full token after creation) |
| `tokens:write` | Create/revoke own User PATs |
| `audit:read` | Read management audit events |

Rules:

- Seeded `super_admin` always receives the full current catalog (including these entries) via Foundation Upgrade / System Role ensure.
- Seeded `operator` does **not** receive `sources:write`, `metadata:write`, `ingestion:run`, `query:run`, `tokens:*`, or `audit:read` by default.
- No object-level ACL in this phase.
- Nav visibility for modules uses each module’s `list` action Permission (same Console Module contract as Foundation).

## 7. Console Modules (`metadata` Group)

Group id: `metadata`.

Initial modules (ids stable):

| Module id | Purpose | list permission |
| --- | --- | --- |
| `sources` | Source Systems and nested Connection management | `sources:read` |
| `catalog` | Browse Catalog Objects / columns | `metadata:read` |
| `ingestion` | Ingestion Job list and trigger entry points | `ingestion:run` (list) |

User PAT management is **not** in this group; see `docs/business-user-tokens.md` (Administration module `tokens`).

## 8. Secret Storage

- Connection credentials are stored encrypted in Postgres using an application master key from environment (`REFRAQ_SECRETS_MASTER_KEY`).
- Decryption occurs only in worker/API paths that need to open a Connection.
- APIs may acknowledge `has_secret` / last-rotated metadata; they must not return plaintext secrets.
- External Vault/KMS is out of scope for this phase (see `docs/adr/0005-app-encrypted-connection-secrets.md`).

## 9. Ingestion Runtime

- API validates and enqueues; worker processes execute connectors.
- Slice A connectors: **PostgreSQL**, **MSSQL**, **Oracle**.
- Structure collection persists object inventory, columns, and DDL when obtainable.
- Failed jobs leave prior successful snapshots readable unless a job explicitly replaces them under documented replace semantics.

## 10. Semantics And Joins (Slices B–C)

- Semantics fields: business name, business description; optional enum catalog later.
- Writes are additive/corrective; do not clear existing semantics with nulls unless an explicit clear API exists.
- Join edges require evidence (verified SQL/DDL or successful validation); name-similarity alone is insufficient.
- Open questions may be recorded when evidence is incomplete.

## 11. Controlled Query (Slice D)

- Allowed: single read-only statement (SELECT or engine-equivalent).
- Reject: DDL, DML, multi-statement batches, and anything the platform cannot classify as read-only.
- Enforce timeout and maximum row count.
- Execute only through a specified Connection; audit every attempt (statement summary or hash, User, Connection, outcome).
- Prefer Connections whose DB user is itself read-only as defense in depth; platform guards remain mandatory.

## 12. MCP

- MCP tools are a first-class product surface backed by the same domain services and Permissions as HTTP APIs.
- Authentication: User Session (where applicable) or **User PAT** Bearer.
- Tool availability follows slices (structure read in A; semantics write in B; joins in C; query in D).
- Contract detail: `docs/api-contracts-metadata-mcp.md`.

## 13. Management Audit

Persist management-plane events for at least:

- Source / Connection create/update/disable and secret set/rotate
- Ingestion Job enqueue / cancel / terminal failure (summary)
- Semantics and join writes
- User PAT create / revoke
- Controlled query execution

Each event: actor User id, timestamp, resource type/id, action, result (`success` / `failure`), optional detail payload without secrets.
Full platform audit of every login/Settings/Users path is out of scope for this phase (Foundation login paths may remain hook-ready only).

## 14. Success Criteria (Phase)

1. An authorized User can register Source Systems and Connections for PostgreSQL, MSSQL, and Oracle under Console group `metadata`, enqueue structure ingestion, and browse Catalog Objects.
2. MCP clients using a User PAT can exercise slice-appropriate tools; mutating calls are attributable to that User in audit.
3. Connection secrets are never stored or logged in plaintext; ingestion does not block the API process.
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
- Treating read replicas as standard metadata Connection targets

## 16. References

- `docs/business-user-tokens.md`
- `docs/business-management-console.md`
- `docs/api-contracts-sources.md`
- `docs/api-contracts-ingestion.md`
- `docs/api-contracts-metadata.md`
- `docs/api-contracts-tokens.md`
- `docs/api-contracts-audit.md`
- `docs/api-contracts-metadata-mcp.md`
- `docs/adr/0004-redis-queue-for-ingestion.md`
- `docs/adr/0005-app-encrypted-connection-secrets.md`
