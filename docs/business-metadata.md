# refraq Business Rules: Metadata Foundation

## 1. Scope

This document defines the **metadata foundation** phase for refraq: Sources (with embedded reachability for database kinds), metadata ingestion, catalog browsing, semantics and join enrichment, controlled read-only query, Management Console mounts under the `metadata` nav group, MCP exposure, and the companion system base required to operate that surface safely.

**Job** and **Scheduled Task** are platform mechanisms, not Metadata business objects. Their rules live in `docs/business-jobs.md` and `docs/business-scheduled-tasks.md`. This document keeps only the Source/structure facades that use those mechanisms.

Related boundaries:

- **Management Foundation** (login, Session, Users, Roles) remains the enabling layer; rules live in `docs/business-login-auth.md`.
- **User PAT** rules live in `docs/business-user-tokens.md`.
- Platform **Job**: `docs/business-jobs.md`. Platform **Scheduled Task**: `docs/business-scheduled-tasks.md`.
- Console shell and module registration contract: `docs/business-management-console.md`.
- Terminology: `docs/glossary.md` and root `CONTEXT.md`.
- Source / catalog identity: `docs/adr/0007-source-owns-catalog-identity.md`.
- Source-embedded access: `docs/adr/0010-source-owns-access.md`.
- Encrypted access blob + Connector Spec: `docs/adr/0011-encrypted-access-blob-and-connector-spec.md`.
- Catalog scope inside access: `docs/adr/0021-catalog-scope-in-access.md`.
- Locator addressing: `docs/adr/0012-locator-addressing.md`.
- Semantics provenance: `docs/adr/0013-semantics-provenance-and-protected-sources.md` (field protection deferred: `docs/adr/0014-defer-semantic-field-protection.md`).
- Semantics field admission criteria and field-set pruning: `docs/adr/0015-semantic-field-admission.md`.
- Type Mapping as Normalized Type authority: `docs/adr/0024-normalized-type-mapping.md`.
- Job shape: `docs/adr/0008-job-generic-input.md`.
- This phase does **not** define Business Entity, Data Product catalog, Serving delivery, or Access Contract marketplace workflows.

These rules are the working source of truth unless superseded by a later ADR or business document.

## 2. Problem And Decision

### 2.1 Gap

Foundation P0 delivered people, permissions, and Console mount contract. Product identity still requires an authoritative in-product path from registered data origins to governed data outputs. Without Source registration, collection, MCP inside refraq, later Entity and Data Product work has no substrate.

### 2.2 Confirmed Direction

1. **Productize into refraq** — Source registration, ingestion, catalog, MCP, and companion base live in this repository; external `dbmeta` is design reference only.
2. **Empty rebuild** — do not migrate or dual-read legacy `dbmeta` data; operators re-register Sources and re-collect.
3. **Phase north star** — metadata capability face comparable to structure + semantics + join + controlled query, plus companion base (secrets, Celery worker/beat, User PAT, management audit, permissions, `metadata` nav). **Job** / **Scheduled Task** delivered with that companion base remain platform mechanisms; Console modules `jobs` / `schedules` mount under **Operations**, not Metadata.
4. **Deliver in slices A→B→C→D** with companion base started alongside A — not a single big-bang milestone.
5. **Defer** Entity, Data Product catalog, Serving, Access marketplace, Client management, and Console P1 cosmetics (scope/search/theme/notifications).
6. **Source is the catalog owner** — not limited to enterprise systems; `kind` leaves room for later non-live origins (for example CSV).

## 3. Principles

1. **Source is the business/catalog identity and, for database kinds, owns live reachability and credentials** — `engine` and a per-engine validated **access** JSON document that carries both connectivity and catalog scope (engine-dialect keys; secrets inside that document), stored as one application-encrypted blob on the Source row (ADR 0011 / 0021).
2. **Catalog Object identity is Source-scoped only**.
3. **Long work never blocks the API process** — enqueue **Jobs**; workers execute.
4. **Credentials are secrets** — the whole access document is encrypted at rest in Postgres; read APIs strip `x-secret` fields; write/edit APIs may return the full decrypted tree; never written to a **System Parameter** or logs.
5. **Backend Permission catalog is authoritative** for Console, REST, and MCP.
6. **MCP authenticates a User** (Session or User PAT), not an anonymous service key and not a Client in this phase.
7. **Write honesty** for semantics and joins — evidence-backed join edges; incomplete understanding stays incomplete (open questions allowed); do not invent business meaning.
8. **Controlled query is read-only** with platform guards, not a general SQL console.
9. **Kind extensibility** — slice A implements Source `kind=database` only; other Source kinds are planned extension points, not delivered in this phase.
10. **Job is an independent durable execution** — discriminated by Job `kind`, carrying a generic `input` payload; not owned by Source. Structure Jobs are minted only by a **Scheduled Task**.

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
| engine | Required when `kind=database`; wire/protocol family — slice A: `postgresql` \| `mssql` \| `oracle` |
| access | Required when `kind=database`; per-engine Connector Spec–validated JSON (includes dialect catalog scope — PostgreSQL / MSSQL: required `database` and `schema`; Oracle: required `service_name` and `owner` — schema/owner is always required so object names are unique within the Source; plus `password` and other secrets, optional `extra`; TLS fields only where the engine Spec wires them — PostgreSQL full modes, mssql/oracle `disable` only in slice A); unknown root keys rejected; stored encrypted as a whole document |

APIs expose projected `access` (secrets stripped), plus `has_access` / `access_updated_at`. Full decrypted `access` is available only on the write-scoped edit endpoint. Non-database kinds may omit `engine` and `access`.

**Connector Spec:** backend-authored JSON Schema per engine, served via API; drives validation and Console SpecTree. `x-secret` marks fields for read/UI projection only — storage encryption is always whole-document. `x-scope` (`catalog` | `schema`) marks dialect keys that Source access uses to assemble runtime `SourceEndpoint`; it is not a UI projection marker.

Rules:

- Distinct environments or physical instances are **distinct Sources** (separate keys, catalogs, and reachability).
- For `kind=database`, **business/catalog scope** and **live reachability/credentials** both live in Source `access` (ADR 0021) — there is no separate Connection entity or credential reuse across Sources, and no fixed top-level `database_name` / `schema_filter` columns.
- Creating a database Source without `engine` and `access` is rejected (`SOURCE_ACCESS_REQUIRED`).
- Creating a database Source also inserts one ordinary structure **Scheduled Task** (product default: daily `0 2 * * *`, **Schedule Timezone** UTC, enabled, default name `structure · {source_key}`). Create and seed succeed or fail together. The insert is authorized by `sources:write` and does not require `jobs:run`. Source HTTP responses do not include the seed. The seed is not a **Job**.
- Endpoint or credential change updates the **same Source** (replace full `access`) — not a new Source row. Catalog Objects stay under that Source; the next structure Job uses the updated endpoint.
- Prefer the authoritative / primary endpoint; do not register read replicas as alternate Sources for the same physical server.
- Disabling a Source blocks new ingestion until re-enabled (existing catalog snapshots remain readable unless later retention rules say otherwise).
- A Source may be **hard-deleted** only while `status=disabled` (`DELETE /sources/{id}`); soft delete remains out of scope. Hard-delete calls schedule **withdraw** with the same opaque `owner_ref` the facade wrote at create (e.g. `metadata:source:{id}`). That is not a Source FK cascade and not a scan of schedule kwargs for `source_id`. The scheduler never interprets Source.
- Non-`database` kinds are out of scope for slice A implementation; models and APIs must not hard-code that every Source requires `engine` / `access`. Kind-specific scope fields for non-database kinds arrive with those kinds.
- Pre-0011 rows that used plaintext access plus a separate secret column are **not** auto-migrated; operators re-enter connectivity after cutover.

### 4.2 Structure Job and schedule facades

Platform **Job** and **Scheduled Task** rules live in `docs/business-jobs.md` and `docs/business-scheduled-tasks.md`. Those mechanisms are **not** Metadata objects and are **not** owned by Source.

Metadata owns only the **facades** that use them for structure collection:

| Facade | Role |
| --- | --- |
| `POST/GET /sources/{id}/schedules` | Register / list structure schedules whose **target** is this Source (operator create path) |
| Seed / ensure on Source create or mutating update | Insert the product-default structure schedule when needed (`sources:write`) |
| Hard-delete Source | **Withdraw** schedules by opaque `owner_ref` (same literal written at create). Scheduler does not know Source |
| `POST /schedules/{id}/run`, Beat tick | Mint structure **Jobs** (always). Domain constraints run at Job execution |

Rules:

- Structure **Jobs** are minted only by a **Scheduled Task** (run-now or Beat). Slice A database structure `input` is `{ "source_id": "…" }` only. There is no `POST /sources/{id}/jobs` and no MCP enqueue.
- Enqueue writes `summary` (`structure · {source_key}`) and `trigger_kind=schedule` / `trigger_ref` = schedule id. Operator run-now also sets `created_by`. Minting does **not** enforce structure single-flight or Source usable status; those fail on the Job during execution (`JOB_ALREADY_ACTIVE` / `JOB_SOURCE_DISABLED`).
- Creating a structure schedule via the facade requires `jobs:run` and a database Source with an access blob (registration gate). The schedule row still carries only opaque `owner_ref` (literal such as `metadata:source:{id}`) — not a Source FK. Product HTTP cannot set `owner_ref`.
- Workers load reachability from the Source identified in Job `input`; `input` does not carry endpoint material.
- Successful structure Jobs write/refresh **Catalog Objects** on that Source and produce at most one **Structure Diff**. **Job result** envelope: `{ "schema": "structure.diff.v1", "class", "counts", "structure_diff_id" }`. Failed, cancelled, or fail-safe Jobs write neither result nor Diff. An unexpected runner abort (including catalog persist) ends the Job `failed` with `JOB_EXECUTION_FAILED` so occupancy does not keep a false `RUNNING`. The structure runner honors a cooperative terminal stamp (`cancelled`, `JOB_RUNNING_TIMEOUT`, `JOB_WORKER_LOST`) before applying a catalog snapshot.
- Related Jobs hang on the **schedule** (`GET /schedules/{id}/jobs`), not on Source. Structure Diff browse is a Source-scoped Console page (`/console/sources/:id/structure-diffs`, `metadata:read`). Global Job observe is **Operations** `jobs`. Source related-schedules **workbench** is `/console/sources/:id/schedules` (facade create plus manage), not a Source Job list.
- Facade create/list: first slice `work_kind=structure`; several schedules may target one Source. Default name `structure · {source_key}` (not unique); key `structure:{source_id}:{schedule_id}` (facade convention). Patch / delete / run-now are by schedule id on `/schedules/{id}` (mechanism HTTP).
- Creating a database Source seeds one such schedule (product default cadence). Operators may add more, disable, or delete including the last one; zero schedules is allowed until the next mutating Source update, which inserts one product-default schedule when a database Source has none (disabled schedules count as present). That ensure writes `schedule.create` for the PATCH User; `PATCH /sources/{id}` includes the inserted `schedule` only when it actually inserted. Create and GET still omit it. It is not a process-start scan and not **Foundation Upgrade**.
- Create writes `last_run_at=now` and stores `next_run_at` as the next legal commitment (or null if created disabled). Run-now does not move those fields.
- Breaking **Structure Diff** does not pause the schedule or block the next structure Job (§9).
- **Structure single-flight** (at most one non-terminal structure Job per Source) is catalog-write serialization on the Source, enforced at Job **execution**, not a Scheduled Task mutex and not a schedule mint / HTTP conflict.

### 4.3 Catalog Object And Columns

Collected structure includes object identity **under Source**, object type, name, columns (name, full type string with precision/length when available, **Normalized Type**, nullable, default value, native comment), primary key column list, foreign keys, unique constraints, indexes, object-level native comment, and DDL when available.
Optional provenance may record collection timestamp; provenance is not part of identity.
Semantics and join edges attach to these objects/columns (see §10).

### 4.3.1 Locator keys

Every Source, Catalog Object, and column carries a stable readable **locator key** (stored, unique), derived from natural keys (ADR 0012):

| Kind | Format |
| --- | --- |
| Source | `src/{engine}/{source_key}` (non-database: `src/{kind}/{source_key}`) |
| Object | `obj/{engine}/{source_key}/{schema}/{object_type}/{name}` |
| Column | `col/{engine}/{source_key}/{schema}/{object_type}/{name}/column/{column_name}` |

Rules:

- Segment-internal `/` is percent-encoded.
- The `column` field_kind segment is reserved; only `column` is used in this phase.
- Locators are recomputed when Source `key`/`engine` or object/column natural keys change.
- **MCP** is locator-first (tool args resolve by locator). **HTTP** path params remain surrogate ids; responses always include `locator_key`.

### 4.3.2 Type Mapping

Global assignment of **Normalized Type** for one `engine` + canonical native type (ADR 0024). Not owned by a Source.

| Field | Notes |
| --- | --- |
| id | Stable technical identifier |
| engine | Wire/protocol family (`postgresql` \| `mssql` \| `oracle` in Slice A) |
| native_type | Canonical parameter-free type name (lowercase, whitespace folded, every `(…)` group removed). `varchar(50)` and `varchar(100)` share one row; `varchar` and `character varying` do not. `TIMESTAMP(6) WITH TIME ZONE` → `timestamp with time zone` |
| normalized_type | Closed 12-value **Normalized Type** |
| origin | **Type Mapping Origin**: `product` (seed), `job` (structure Job recorded `unknown`), `user` (Console PATCH) |

Rules:

- Unique on `(engine, native_type)`. Product seeds occupy that key on Upgrade (no second row). If a `job`/`user` row already exists for a seeded key, Upgrade takes it over (`origin=product` and the seed target).
- Product seed rows are immutable. Console has no CREATE / DELETE. Operators may PATCH a non-seed row to any closed value except `unknown`; PATCH sets `origin=user`.
- A structure **Job** canonicalizes collected `data_type`, looks up the row, and if missing inserts `unknown` with `origin=job`. It never replaces an existing row. Empty/blank `data_type` assigns column `unknown` and does **not** insert a mapping (no identity key).
- Column **Normalized Type** is the snapshot from that Job, not a live lookup. Patching a mapping does not rewrite existing columns until the next successful structure Job.
- Console PATCH writes a **Management Audit Event** (`resource_type=type_mapping`, `action=type_mapping.patch`). Job-recorded `unknown` does not.
- MCP catalog tools omit `normalized_type` and do not expose Type Mapping; agents use native `data_type`.

### 4.4 Future foresight — non-database Source kinds (not delivered in A–D)

Planned shape only; no Attachment APIs, ORM, or Console flows in this phase:

- A later Source `kind` (for example `file`) remains a **Source** with Catalog Objects under it — not a parallel identity.
- Live reachability fields stay optional (often zero). File bytes or external URI are expected to use a distinct **Attachment** (or equivalent) concept.
- Structure refresh is still a **Job** with `kind=structure`; domain targets (Source, Attachment id/URI, format hints) live in Job `input`, via a Source (or kind-specific) facade.
- Do not force file/static origins through database-style `engine` / `access`; do not promote Attachment fields onto universal Job columns.
- Full Attachment cardinality, versioning, blob storage, and reference-data governance remain out of scope until that phase is grilled and documented.

## 5. Delivery Slices

| Slice | Business delivery |
| --- | --- |
| **Companion base** (with A) | User PAT; Source access-blob encryption; Celery worker/beat; Permission catalog extensions; `metadata` Console nav group; management-plane audit. **Job** / **Scheduled Task** are platform mechanisms delivered alongside (see `docs/business-jobs.md`, `docs/business-scheduled-tasks.md`); their Console modules mount under **Operations**, not Metadata. |
| **A** | Source CRUD for `kind=database` (embedded reachability); PostgreSQL + MSSQL + Oracle structure collection; Console browse; MCP read-only structure tools |
| **B** | Object/column business name and description read/write via API and MCP |
| **C** | Join graph with evidence threshold for writes |
| **D** | Controlled read-only query (`run_sql`) with guards and audit |
| **Depth** | Locator addressing; deep structure (PK/FK/indexes/comments/defaults); full semantics model + provenance; catalog search; join path + batch upsert |

Slice B–D must not ship before A’s structure substrate exists for the same Source.
Non-database Source kinds (e.g. CSV) are **not** in slices A–D.
Depth builds on A–D; deliver locator → structure depth → semantics → search → join graph in that order.

## 6. Permission Catalog (Metadata)

Fixed catalog additions (exact strings are normative for Roles UI):

| Permission | Meaning |
| --- | --- |
| `sources:read` | List/view Sources (projected `access`, Connector Spec) |
| `sources:write` | Create/update/disable Sources; hard-delete disabled Sources; replace full `access`; fetch full access for edit; run Source reachability tests; creating a database Source, or a mutating update of one with zero structure schedules, also inserts the product-default structure **Scheduled Task** |
| `metadata:read` | Browse Catalog Objects, columns, DDL, semantics, joins, and **Type Mapping** |
| `metadata:write` | Write semantics and join edges; PATCH non-seed **Type Mapping** |
| `query:run` | Execute controlled read-only SQL against a Source |
| `catalog:sample` | Run Catalog Sample (structured live peek) on a Catalog Object |
| `tokens:read` | List own User PAT metadata (never full token after creation) |
| `tokens:write` | Create/deactivate/restore/soft-delete (deactivated only) own User PATs |
| `audit:read` | Read management audit events |

Rules:

- Structure facades (`POST/GET /sources/{id}/schedules`, `POST /schedules/{id}/run`, `GET /schedules/{id}/jobs`) require `jobs:run`, defined in `docs/business-jobs.md` (not a Metadata-owned permission).
- Seeded `super_admin` receives the full current catalog **by identity**; Foundation Upgrade ensures the System Role row exists but does not grant access by rewriting a stored permission list.
- Seeded `operator` does **not** receive `sources:write`, `metadata:write`, `jobs:run`, `query:run`, `catalog:sample`, `tokens:*`, or `audit:read` by default.
- No object-level ACL in this phase.
- Nav visibility for modules uses each module’s `list` action Permission (same Console Module contract as Foundation).

## 7. Console Modules (`metadata` Group)

Group id: `metadata`.

Initial modules (ids stable):

| Module id | Purpose | list permission |
| --- | --- | --- |
| `sources` | Source registration, reachability, structure Jobs, and **Structure Diff** browse (`/console/sources/:id/structure-diffs`) | `sources:read` |
| `catalog` | Browse Catalog Objects / columns; object detail at `/console/catalog/:id` (`show` → `metadata:read`) for full semantics, structure facts, Catalog Sample, joins, and DDL | `metadata:read` |
| `business-domains` | Global Business Domain registry (immutable `code`); create/edit/delete → `metadata:write` | `metadata:read` |
| `type-mappings` | Global **Type Mapping** list; PATCH non-seed target only (no create/delete) → `metadata:write` | `metadata:read` |

The catalog object detail page is the Console semantics maintenance surface: it exposes the admitted object/column semantics model (§10, ADR 0015), structure facts (PK/FK/indexes/comments), **Catalog Sample** when the actor has `catalog:sample`, and join graph / path exploration. List remains the Source-scoped browse entry; deep links use the `show` route so readers with only `metadata:read` can open detail without needing `metadata:write`.

**Structure Diff** browse lives under Source routes (`/console/sources/:id/structure-diffs`); viewing requires `metadata:read`. It is not a new sidebar module. Classification is read on **Structure Diff**, not on Job list/detail chrome.

Sources keep a **related schedules** workbench at `/console/sources/:id/schedules` (toolbar create plus the same row actions as Operations `schedules`; `jobs:run`; not a sidebar module and not `sources.show`). Global Job observe and domain **Scheduled Task** lists live under **Operations** (`docs/business-jobs.md`, `docs/business-scheduled-tasks.md`), not this group.

User PAT management is **not** in this group; see `docs/business-user-tokens.md` (Administration module `tokens`).

## 8. Access Blob Storage

- The whole Source `access` JSON document (including passwords and other `x-secret` fields) is stored encrypted in Postgres using an application master key from environment (`REFRAQ_SECRETS_MASTER_KEY`) — see ADR 0011.
- Decryption occurs in worker/API paths that open a live endpoint, and on write-scoped edit fetch.
- List/get return projected access (secrets stripped) plus `has_access` / `access_updated_at`.
- External Vault/KMS is out of scope for this phase (see `docs/adr/0005-app-encrypted-connection-secrets.md`).

## 9. Structure Job Runtime (database)

- Source facade validates and enqueues; worker processes execute connectors.
- Slice A connectors: **PostgreSQL**, **MSSQL**, **Oracle**.
- Structure collection persists, keyed by Source:
  - objects: type (`table` \| `view` \| `materialized_view`), schema, name, native comment, DDL when obtainable
  - columns: name, full type string (precision/length when the engine exposes it), **Normalized Type** (snapshot from **Type Mapping** for that engine + canonical native type), nullable, default value, native comment, ordinal
  - primary key column names; foreign keys (name, from/to columns); unique constraints; indexes
- A structure Job never writes Object Semantics or Column Semantics. Those fields belong to
  human/agent patch surfaces; refresh must not overwrite them.
- **Current catalog** is authoritative (not a per-Job version history). Natural key:
  `(source_id, schema_name, name, object_type)`. Surrogate ids are preserved across successful refreshes.
- **Success-only commit:** only a Job that reaches a complete successful collect may mutate catalog.
  Failed, cancelled, or aborted collects leave the prior successful catalog unchanged (no absent marks).
- **In-scope absent:** after a complete collect, objects previously present within the Job's schema
  scope (`access.schema` / `access.owner`; resolved at runtime) that are missing from the collect are marked `is_present=false`
  (tombstone). Out-of-scope objects are not bulk-absent when the filter shrinks. Same tombstone rules
  apply to columns, foreign keys, and indexes under present objects.
- **Fail-safe:** if the fraction of in-scope present objects that would become absent exceeds
  `REFRAQ_CATALOG_FAIL_SAFE_THRESHOLD` (default `0.75`), the Job fails with `JOB_FAIL_SAFE` and
  writes nothing (no catalog mutation, no **Job result**, no **Structure Diff**). Fail-safe answers
  “was this collect untrustworthy?”; it is not drift detection.
- **Structure Diff (detect, do not act):** after a successful commit, compare existing vs incoming
  (same identity and `schema_scope` as merge; do not reverse-engineer the touched-object plan) and
  persist a **Structure Diff** on the Source, associated with the Job. Write **Job result**
  `{ "schema": "structure.diff.v1", "class", "counts", "structure_diff_id" }`. Do not change Job
  status, pause a **Scheduled Task**, or block the next structure Job when `class=breaking`.
  Do not put outcome into enqueue **summary**.
  - `class` is derived: `breaking` if any breaking count > 0; else `non_breaking` if any
    non-breaking count > 0; else `unchanged`. First collect (all adds) is `non_breaking`.
  - Breaking: removed object, removed column, native `data_type` string change, PK set change,
    nullable tighten. `varchar(50)→varchar(100)` and `integer→bigint` are type changes.
    Rename is drop+add (no rename detection). FK/index/unique changes are recorded on the Diff
    but do not raise `class`.
  - Full locators live on the Diff; Job result holds counts only.
- **Normalized Type** values: `string` \| `integer` \| `number` \| `boolean` \| `date` \|
  `timestamp` \| `time` \| `interval` \| `binary` \| `json` \| `array` \| `unknown`.
  Native `data_type` remains the engine string. Assignment is a **Type Mapping** lookup
  (ADR 0024): canonicalize, look up `(engine, native type)`, insert `unknown` (`origin=job`)
  if missing, never overwrite an existing row. Product seeds are Upgrade-occupied and
  immutable. `type_changed` compares native `data_type` strings (exact inequality; not
  Normalized Type). Columns with `unknown` stay visible (Console Badge; one Job `WARN`
  with count and up to 10 locators). Job result / Structure Diff do not grow unknown counters.
- **Semantics preservation:** structure upserts whitelist structural columns only; never overwrite
  semantics fields or non-`foreign_key` join edges.
- **FK → join derivation:** each collected foreign key upserts a join edge with `origin=foreign_key`
  and evidence naming the FK constraint. Re-collection updates or tombstones those edges; it must
  not delete or overwrite edges with `origin=human` or `origin=mcp`.
- **Structure single-flight:** at most one non-terminal `kind=structure` Job may run catalog writes per Source
  (`JOB_ALREADY_ACTIVE` on the colliding Job). This is catalog-write serialization on the Source, not a **Scheduled Task**
  mutex. Enforced when the structure Job **executes** (not when the schedule mints). Authority remains the Job table.
  The schedule always mints; Beat does not swallow; run-now does not HTTP-409 for this reason.
  Re-run = new Job after terminal status.
- Collectors read **Source `engine` / decrypted `access`** (scope and credentials together). Introspection uses
  engine-native catalogs (`pg_catalog`, `sys.*`, `ALL_`/`DBA_`).
- Oracle schema scope is `access.owner` (required; same role as `schema` on PostgreSQL/MSSQL).
- Collection account guidance: prefer least privilege (PostgreSQL schema `USAGE` + catalog read;
  MSSQL `VIEW DEFINITION`; Oracle `SELECT_CATALOG_ROLE` or equivalent).
- Engine parity notes (explicit, not silent): when an engine cannot supply a field (e.g. some
  type-precision shapes), store null/best-effort string and document the gap in connector comments.

## 10. Semantics And Joins

### 10.1 Object semantics

| Field | Notes |
| --- | --- |
| `business_name` | Short display name |
| `business_description` | Natural-language role / grain summary |
| `object_category` | `transaction_fact` \| `master_data` \| `dimension` \| `reference` \| `event` |
| `grain_description` | Prefer “one row means …” |
| `business_primary_key` | List of column names; names must exist on the object (`SEMANTIC_COLUMN_UNKNOWN`) |
| `business_domain` | Nested `{ id, code, name }` on read; write via `business_domain_code` referencing a Business Domain entity (ADR 0017); unknown code → `BUSINESS_DOMAIN_UNKNOWN` |
| `evidence_summary` | List of short evidence phrases |
| `open_questions` | List of unresolved questions (persisted; never audit-only) |
| `semantic_source` | Provenance of the last write: `mcp` \| `user_input` |
| `business_semantics_ready` | Stored boolean; true when name+description present and open_questions empty |
| `semantics_updated_at` | Last semantics write timestamp |

`object_category` decision rules (so two writers reach the same value):

- `transaction_fact` — one row is one business transaction, carries a business time axis, references master data
- `event` — one row is one state change or system/user event; append-only, not updated in place
- `master_data` — one row is a business entity referenced by transactions, with its own lifecycle
- `dimension` — descriptive table built for analysis, typically derived from master data
- `reference` — code/dictionary table: small, stable, carrying `code → label`

Tie-breaks: source-system business entity → `master_data`, analytical derivative → `dimension`;
rows carrying only `code → label` → `reference`.

`model_routing_hint` is **not** delivered in this phase (see ADR 0013).
`time_semantics`, `status_semantics`, `relation_summary`, and `confidence` are **removed** (ADR 0015);
time and status meaning live on the relevant columns via `business_description` (and optional
free-text `semantic_type` / `enum_catalog` — closed vocabulary deferred, ADR 0016), object
relationships in join edges, and write certainty in `evidence_summary` / `open_questions` /
`business_semantics_ready`.

**Business Domain** (ADR 0017) is a global flat entity: immutable `code`, mutable `name`, optional
`description`. Catalog objects reference it by FK (`ON DELETE RESTRICT`). Console Module
`business-domains` reuses `metadata:read` / `metadata:write`.

### 10.2 Column semantics

| Field | Notes |
| --- | --- |
| `business_name` / `business_description` | Same write rules as object |
| `column_semantics` | `{ semantic_type, value_pattern, unit }` only; `semantic_type` is free text in this phase (ADR 0016) |
| `enum_catalog` | List of `{ code, label, description }` when discrete enums are evidenced |
| `semantic_source` | Same provenance values as object |
| `field_kind` | Default `column`; held by structure collection; **not** writable via semantics APIs |

`semantic_type` remains nullable free text. A closed vocabulary and derived `semantic_gaps` are
**deferred** until a concrete reader exists (ADR 0016). Unclassified columns leave the field null
and explain roles in `business_description`. Several columns may each describe a time axis; there
is no elected primary axis at object level.

### 10.3 Write rules

- **HTTP** semantics PATCH: omitted keys leave fields unchanged; a present JSON `null`,
  blank string (after trim), or empty list/object **clears** the field (ADR 0018).
- **MCP** adapters strip `null`, blank strings, and empty collections before writing — agents
  cannot clear via MCP in this phase (fill gaps only).
- Incomplete understanding stays incomplete — record `open_questions`, do not invent meaning.
- Column-name references in semantics payloads (`business_primary_key`) must resolve to columns on
  the object; unknown names are rejected with `SEMANTIC_COLUMN_UNKNOWN`.
- `business_domain_code` on object semantics writes must resolve to an existing Business Domain
  when non-empty; unknown codes are rejected with `BUSINESS_DOMAIN_UNKNOWN`. A present null/blank
  clears the object’s Business Domain link.
- Adding a semantics field requires passing the ADR 0015 admission criteria — carrier ownership,
  objective unique answer, falsifiability, structure paying for itself, and layer ownership.
  Object-level fields that elect one "primary" column out of several of the same kind, and free
  text read only by humans or agents, do not qualify.
- `semantic_source` records the **last write** provenance. Field-level protection against MCP
  overwrite is **deferred** (`docs/adr/0014-defer-semantic-field-protection.md`); Console and MCP
  both write submitted non-empty fields (HTTP may also clear via present-null).
- MCP column writes are **batch** per object (see MCP contract); batch reports
  `skipped_columns` for `invalid_column_name` (missing/blank names) or no-op payloads.
- Structure Jobs never mutate semantics columns.
- `field_kind` may be set/refreshed by structure collection, but semantics write endpoints
  (HTTP PATCH and MCP `set_*_semantics`) must not accept or change it.

### 10.4 Joins

Join edge fields:

| Field | Notes |
| --- | --- |
| from/to column | Single-column endpoints (composite FKs become multiple edges) |
| `evidence` | Required non-empty text |
| `join_kind` | Default `INNER` |
| `join_expression` | Optional; when omitted, server generates equality on the column pair |
| `origin` | `foreign_key` \| `human` \| `mcp` |
| created_by / created_at | Provenance |

Rules:

- Evidence required; name-similarity alone is insufficient (`JOIN_EVIDENCE_REQUIRED`).
- Same-Source only (`JOIN_CROSS_SOURCE`); no self-loop (`JOIN_INVALID`).
- Batch upsert limited to one Source per call; returns created / already_known counts.
- **FK resolution during structure Jobs:** if a collected foreign key cannot be resolved
  (missing referenced object/columns), has unequal local/ref column counts, or matches
  ambiguous referenced targets, the structure Job **fails** and the prior successful catalog
  snapshot is left unchanged (same success-only commit as §9).
- **Join path:** BFS over edges (max hops 1–5) from object or column locator; modes are
  explicit target locator or graph exploration. Returns path summary and per-hop join
  expressions; responses may include a `reason` when no usable path is available
  (e.g. unreachable target).

## 10.5 Catalog search

- Cross-Source object and column search by **non-empty** query text (locator, name, schema,
  business_name, business_description) with optional `source_id` / `object_type` filters and
  `limit`/`offset`. Empty or omitted query is rejected for both object and column search.
- Ranking tiers (portable lexical, identical in memory and SQL stores): exact locator/name →
  prefix → name substring → business name/description substring.
- Per-Source object list pages **Current catalog** under one Source. Pagination uses
  `limit`/`offset`. Filters: `include_absent` (default include tombstones), `object_type`,
  optional `business_semantics_ready` (`true` | `false`; omit for no readiness filter).
  List `q` is optional; when present it is a literal case-insensitive substring of schema,
  technical name, or **Object Semantics** business name (not **Locator**, not business
  description; `%` and `_` are literal). Search endpoints require a non-empty query and
  use ranking, including locator and description. List items are summaries: empty
  `columns` / `foreign_keys` / `indexes` and empty `ddl`. Currently present objects as a
  structure graph (**Structure Diff**, **Join Path**) are not this list.

## 11. Controlled Query (Slice D)

- Allowed: single read-only statement (SELECT, UNION/INTERSECT/EXCEPT, or `WITH … SELECT`).
- Reject: DDL, DML, multi-statement batches, row locking (`FOR UPDATE`), dangerous functions (for example `pg_sleep`, `xp_cmdshell`), and anything the platform cannot classify as read-only.
- L4 uses a dialect-aware SQL AST (sqlglot) keyed by Source `engine` (`postgresql` / `mssql` / `oracle`); parse failures and unclassified statements fail closed.
- Enforce timeout and maximum row count.
- Execute through the Source's embedded reachability; audit every attempt (statement summary or hash, User, Source, outcome).
- Prefer a database user that is itself read-only as defense in depth; platform guards remain mandatory.

## 11.1 Catalog Sample

- First-class live peek for **one Catalog Object**: structured request (`filters`, optional `columns` / `order_by`, `offset` / `limit`), platform compiles dialect SQL (sqlglot), then runs through the same readonly guards / timeout / audit internals as Controlled Query.
- Permission: `catalog:sample` (distinct from `query:run`). Seeded `operator` does **not** receive it by default.
- HTTP: `POST /objects/{id}/sample`. MCP does **not** expose a sample tool; agents use `run_sql` for ad-hoc peek.
- v1 filter ops: `eq`, `neq`, `contains`, `is_null` (AND of filter list). Pagination: `offset` + `limit` with hard cap `offset + limit ≤ REFRAQ_QUERY_MAX_ROWS`; response echoes `offset` / `limit` and `has_more` (heuristic); no default `total_count` / `COUNT(*)`. `order_by` is optional; without it, pagination order is unstable.
- Optional `include_sql` returns the compiled statement for transparency; default responses omit SQL.
- Mid-term (versioned): may add single-table ops such as comparisons / `in` / `is_not_null` and richer `order_by` UX. Never joins, aggregates, or arbitrary expressions. Never default `COUNT(*)`.

## 12. MCP

- MCP tools are a first-class product surface backed by the same domain services and Permissions as HTTP APIs.
- Authentication: User Session (where applicable) or **User PAT** Bearer.
- Tool availability follows slices (structure read in A; semantics write in B; joins in C; query in D).
- Contract detail: `docs/api-contracts-metadata-mcp.md`.

## 13. Management Audit

Persist management-plane events for at least:

- Source create/update/disable and access replace
- Source reachability test (`source.test`) — success and failure; no secrets in detail
- Job cancel / terminal failure (summary); structure minting via `schedule.run` / Beat (no Source Job enqueue)
- Semantics and join writes
- User PAT create / deactivate / restore / soft-delete
- Controlled query execution
- Catalog Sample execution (`catalog.sample`)
- Scheduled Task create / patch / delete / run (`schedule.create` / `schedule.patch` / `schedule.delete` / `schedule.run`; no secrets)

Each event: actor User id, timestamp, resource type/id, action, result (`success` / `failure`), optional detail payload without secrets.
A mutating Source update that inserts a missing structure schedule writes `schedule.create` for the same User as `source.update`. Source create writes `source.create` and `schedule.create` for the same User.
Full platform audit of every login/Settings/Users path is out of scope for this phase (Foundation login paths may remain hook-ready only).

## 14. Success Criteria (Phase)

1. An authorized User can register database Sources (with embedded reachability) for PostgreSQL, MSSQL, and Oracle under Console group `metadata`; registration seeds a structure **Scheduled Task**; they can create additional structure **Scheduled Task**s and run-now **Jobs**, and browse Catalog Objects under each Source.
2. MCP clients using a User PAT can exercise slice-appropriate tools; mutating calls are attributable to that User in audit.
3. Source access blobs are never stored or logged in plaintext; long-running Jobs do not block the API process.
4. Roles can grant read-only metadata access without granting Source write, query, or PAT management.
5. Documentation under `docs/` matches behavior; refraq is the sole authoritative registry (no `dbmeta` dual-read).
6. MCP addresses Sources/objects/columns by locator key; HTTP responses include `locator_key`.
7. Structure Jobs collect PK/FK/indexes/comments/defaults (engine parity documented); FK-derived joins use `origin=foreign_key`.
8. Object/column semantics persist across the admitted field set (including `open_questions`); every field passes the ADR 0015 admission criteria, column `semantic_type` is vocabulary-checked, and `semantic_source` records last-write provenance (field-level MCP protection deferred — ADR 0014).
9. Cross-Source object/column search with pagination works; join path lookup returns reachable hop chains.

## 15. Non-Goals

- Business Entity model and UI
- Data Product catalog / discovery / owners marketplace
- Serving / delivery layers
- Access request and contract approval workflows
- Client / machine-token management APIs
- Console P1: scope switcher implementation, global search implementation, theme workshops, notification center
- Registering `metadata` **System Parameter**s (catalog fail-safe threshold, query timeout / max rows) — candidates listed in `docs/business-system-parameters.md` §5.1, delivered after the first slice
- Object-level ACL
- Write SQL / unrestricted SQL consoles
- Migrating or dual-reading legacy `dbmeta` datasets
- Pre-creating empty domain packages before implementation code arrives
- A separate reusable Connection entity or credential sharing across Sources
- Treating read replicas as alternate Source targets for the same physical server
- Delivering non-database Source kinds (CSV/file import, Attachment APIs, etc.) in this phase — foresight only in §4.4
- Source soft delete / versioned credential history / audit-per-rotation (hard-delete of disabled Sources is delivered)
- Query result type normalization / continuation tokens / data masking (deferred past depth)
- Full-text search engines or PG-only FTS as the ranking authority
- Catchup / backfill / RRule
- Treating **Job** or **Scheduled Task** as Metadata domain entities (platform rules: `docs/business-jobs.md`, `docs/business-scheduled-tasks.md`)

## 16. References

- `docs/adr/0007-source-owns-catalog-identity.md`
- `docs/adr/0008-job-generic-input.md`
- `docs/adr/0025-clock-first-structure-jobs.md`
- `docs/adr/0026-seed-structure-schedule-on-source-create.md`
- `docs/adr/0010-source-owns-access.md`
- `docs/adr/0011-encrypted-access-blob-and-connector-spec.md`
- `docs/adr/0021-catalog-scope-in-access.md`
- `docs/adr/0012-locator-addressing.md`
- `docs/adr/0013-semantics-provenance-and-protected-sources.md`
- `docs/adr/0014-defer-semantic-field-protection.md`
- `docs/adr/0015-semantic-field-admission.md`
- `docs/adr/0024-normalized-type-mapping.md`
- `docs/business-user-tokens.md`
- `docs/business-jobs.md`
- `docs/business-scheduled-tasks.md`
- `docs/business-management-console.md`
- `docs/api-contracts-sources.md`
- `docs/api-contracts-jobs.md`
- `docs/api-contracts-schedules.md`
- `docs/api-contracts-metadata.md`
- `docs/api-contracts-tokens.md`
- `docs/api-contracts-audit.md`
- `docs/api-contracts-metadata-mcp.md`
- `docs/adr/0004-redis-queue-for-ingestion.md`
- `docs/adr/0006-celery-platform-async-runtime.md`
- `docs/adr/0005-app-encrypted-connection-secrets.md`
