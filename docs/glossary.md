# Refraq Glossary

## Product Identity

### Refraq

The human-facing brand name of the product.
Avoid lowercase `refraq` in user-visible strings; avoid a Other translation of the brand.

### refraq

The technical identifier for the same product (repository, packages, cookies, env vars).
Avoid title-case `Refraq` for technical identifiers.
Avoid describing the product as a scaffold only or an auth demo.
Avoid using “machine tokens” here as a synonym for **User PAT** or **Client** credentials.

### Data Business Platform

An internal platform that combines data workflows, operational interfaces, and management capabilities into a single business system.
Avoid describing it as an auth shell or a generic admin starter.

### Data Product Integration Platform

An internal platform that integrates data from distributed business systems and turns it into unified, consumable data products.
This is the preferred, more specific product identity of Refraq.
UI copy is locale-specific and will grow beyond the first locales; translate the product-identity phrase for each locale, keep the brand `Refraq` in Latin script, and follow that locale's natural casing (English UI uses Title Case).
Avoid hard-coding one locale's phrasing as the only product name, or treating the current locale set as closed.
Avoid describing it as a generic admin platform or an auth-first product.

### Data Product Capability

A business-defining capability that turns distributed source-system data into unified, consumable, and governable data outputs.
Avoid treating it as a generic admin feature or a page-level function.

### Management Foundation

The generic administrative capabilities required by almost any internal system, such as users, organizations, roles, permissions, and login.
Avoid treating it as the core product identity or the differentiating business capability.

### Management Console

The operator-facing UI surface of Refraq, not the product identity.
This is a docs/domain term, not user-visible UI copy.
Avoid treating it as the product definition, a standalone admin project, or a synonym for Refraq itself.

### Console Module

A first-class Management Console capability mounted in structural navigation (for example Workbench home, Users, Roles, Platform Settings).
Declared in the backend code-seeded catalog; Foundation modules are always present.
Avoid treating it as a toggleable app install, a microservice name, or a Plugin.

### Console Navigation

The permission-filtered, grouped side-nav payload derived from the Console Module catalog for the current User.
Served by the backend navigation API; labels are i18n keys.
Avoid building side-nav truth only from frontend static menus.

### Console Module Identity

The UX identity of a Console Module: stable id, label key, list/create/edit routes, and Refine action → Permission map.
Authored only in the backend Console Module catalog seed; bootstrapped to the SPA unfiltered (separate from Console Navigation).
Avoid treating it as a second frontend catalog, as navigation grouping, or as the security authority for API calls.

### Platform Settings

The Console Module that presents **System Parameter**s.
Distinct from Administration master data (Users / Roles) and from **Account Center**.
Avoid treating the module as the parameter itself, or conflating it with user preferences or Data Product governance.

### System Parameter

A named, site-wide configuration key that an operator can decide from the business, presented by **Platform Settings**.
The product seeds a default stored row; that row is what the operator sees. Consumers derive a safe value from the declared constraint when the stored value sits outside it. Reset restores the seed default.
A field of one **Scheduled Task** / **Source** / **User** is not a **System Parameter**. Occupancy lost-detection and session TTL are **System Parameter**s. Changing session TTL does not rewrite existing **Session**s. Widening lost-detection is live; tightening waits one old renew interval before the reaper cutoff shrinks. The hidden system reaper **Scheduled Task** interval is derived from lost-detection. Worker concurrency is a deployment concern. Beat loop / reload intervals are in-code constants (`docs/business-system-parameters.md` §5.2).
Avoid env as the home of these keys; avoid Settings Override as a second entity; avoid Platform Parameter; avoid **Account Center** preferences; avoid treating the Console Module as the key; avoid moving **Running Time Limit** here; avoid editing the hidden system **Scheduled Task** as the reaper-interval UI; avoid putting an engineering tuning knob (pool size, loop interval, replica count) on this page.

### Settings Override

Retired as a named entity. A persisted override is a state on a **System Parameter**, not a second object.
The former in-process overlay is the thing this slice replaces.

### Plugin

An optional sub-capability extension under a Console Module (future).
Not a top-level Console Module enable/disable mechanism.
Out of scope for Foundation and for the metadata foundation phase.
Avoid using Plugin as a synonym for Console Module.

## People And Access

### User

A person identity in the Management Foundation (local today; LDAP later).
A User may or may not hold a Role that grants Management Console access.
Avoid using User for machine integration principals.

### Administrator

Historical / colloquial label for a User who can operate the Management Console.
Not a separate entity; console access is conferred by Role permissions (notably `console:access`).
Avoid modeling Administrator as its own table or API resource.

### Account

The login identifier used by a User.
Initially modeled as a single username-like field.
Avoid calling it a user id or employee id.

### Identity Source

Where a User's credentials and directory attributes originate.
The current slice uses `local` only; `ldap` is reserved for a later integration.
Avoid treating identity source as a role or permission.
Avoid conflating Identity Source with **Source** (registered data origins).

### Client

A machine integration principal that will consume APIs or product capabilities with its own credentials.
Distinct from User (people). Client credential management remains out of scope for the metadata foundation phase.
Avoid calling a Client a User or an Administrator.
Avoid conflating Client with **User PAT** (person-owned Bearer credentials) or Serving-layer "consumer" (product delivery target).

### Session

Server-managed authenticated state created after successful console login and carried through a cookie.
Avoid calling it a User PAT, a Bearer token, or a permanent login.

### User PAT

A personal access token owned by a User for non-browser API and MCP access (`Authorization: Bearer`); may be deactivated (restorable) or soft-deleted.
Coexists with Console Session cookies; authenticates the same User and Role permissions.
Avoid calling it a Client token, a Session id reused as Bearer, or a machine principal.

### Display Timezone

An optional IANA zone on a **User** that the **Management Console** uses to format **Instants** for that operator. `null` means follow the browser’s system timezone. Not part of Instant storage or HTTP/MCP Instant JSON (those stay UTC `Z`).
Avoid Schedule Timezone, worker process timezone, or treating the preference as a second Instant type.

### Account Center

The current User’s self-service Console surface for profile, local password change, UI locale, **Display Timezone**, and User PAT management.
Avoid conflating with **Platform Settings** / **System Parameter**, or treating User PAT as a sidebar Administration module.

### Backing Service

A replaceable attached store for shared or durable state (for example Postgres or Redis), selected through configuration.
Avoid treating process memory or sticky load-balancer affinity as the production source of Session or User truth.

### Store Backend

Which adapter class implements Foundation User, Role, and Session ports: `memory` (automated tests only) or `persistent` (default runtime; Postgres + Redis).
Avoid inferring memory mode from missing URLs, or documenting `memory` as a supported production setting.

### Current User

The User resolved from the active Session or User PAT for the current request.

### Role

A named, configurable access bundle assigned to at most one Role per User (nullable).
Roles bind a subset of the fixed Permission catalog.
Seeded roles include locked `super_admin` and editable `operator`.
Avoid calling it a job title or department.

### System Role

The product-owned locked Role `super_admin`: stable identity (`key`), not editable via Role APIs; **effective** permissions are definitionally the current Permission catalog.
Stored `permissions` are not authoritative for this Role. **Foundation Upgrade** ensures the identity row exists; it does not grant access by rewriting that list.
Avoid calling every seeded role a System Role (`operator` is a seeded ordinary role).

### Foundation Upgrade

The official product upgrade path: schema migration under advisory lock, then ensure of the System Role identity row.
Does not create or rewrite Users, does not reset editable roles, and does not realign System Role permissions for authz correctness.
Invoked as `python -m backend.core.upgrade` or as the first phase of `python -m backend.core.entry`.

### Site Bootstrap

First-time empty-store initialization: insert seed roles when none exist; create the initial admin User when no users exist.
Does not substitute for Foundation Upgrade schema migrate / identity ensure.
Runs from the API process lifespan (and must not be confused with Foundation Upgrade).

### Permission

A concrete allowed action expressed as `resource:action`, such as `dashboard:read`, `console:access`, `settings:read`, or `sources:read`.
Chosen only from a fixed catalog when editing Roles.
Avoid reducing it to a menu or a page label.
Avoid free-form permission strings invented in the UI.

## Platform Mechanisms

### Job

A single durable asynchronous execution with an observable lifecycle (queued → running → terminal), discriminated by kind, carrying only a generic input payload that each domain interprets.
Domains mint structure and join-detection **Jobs** only via a **Scheduled Task** (due tick or run-now); the Job record is not owned by Source and is not a Metadata business object.
API (or a **Scheduled Task**) enqueues; a Celery worker executes; operator-visible status lives on the Postgres job record.
Lifecycle stamps (`created_at`, `started_at`, `finished_at`, log line times) are **Instants**.
Successful Jobs may carry a nullable generic **Job result**; failed/cancelled/fail-safe Jobs leave it null.
Occupancy lost-detection is a **System Parameter** (seed 60s → `JOB_WORKER_LOST`) and assumes Beat is alive; if Beat is down, reaping stops — API alone does not clear a false `RUNNING`. Widening the window is live; tightening waits one old renew interval before the reaper uses the new cutoff.
A minted **Running Time Limit** snapshot may end the Job `failed` with `JOB_RUNNING_TIMEOUT`; a null snapshot is not limited this way. That stamp is cooperative: the worker process is not killed; the structure runner stops before catalog write.
Avoid calling it an Ingestion Job. Avoid running long work inside the Management Console API request.
Avoid treating a Job as a **Scheduled Task**, or reading Celery result/Flower as the product lifecycle.
Avoid promoting domain foreign keys into universal Job fields.
Avoid promoting kind-specific result fields (for example structure `class`) into universal Job fields.
Avoid overloading enqueue **summary** with outcome, or writing `{}` to mean “no result”.
Avoid treating a global env as the **Running Time Limit** definition, or conflating worker-lost with running-timeout.
Avoid treating **Kind execution lock** or `JOB_ALREADY_ACTIVE` as a schedule mutex, Beat skip, or schedule HTTP error.

### Kind execution lock

Metadata control that serializes same-kind structure or join-detection **Job** execution per **Source**. After claim, the runner try-acquires a lock for `structure:{source_id}` or `join_detection:{source_id}` for the whole run (collect/parse through persist). Failure ends that Job `failed` with `JOB_ALREADY_ACTIVE`. Cross-kind may overlap. Authority is the lock, not the Job table. The **Scheduled Task** always mints.
Avoid Source-wide cross-kind single-flight, Job-table collision scans, using the lock as a schedule mutex, or treating a stale Job row as still holding the lock after the worker connection is gone.

### Job result

A nullable JSON outcome written when a Job reaches a successful terminal state. The platform does not interpret the document; each `kind` supplies its envelope (structure: `class`, `counts`, `structure_diff_id`; join detection: `join_detection.v1` counters).
Avoid Celery result backend, **Management Audit Event** `result`, treating result as whether the Job succeeded, treating structure `class` as a public Job attribute, or treating join-detection `joins_upserted` as the count of pairs planned after the join-graph baseline (it is the count of rows this Job inserted). Console Job detail may show the document uninterpreted; classification is read on **Structure Diff**.

### Scheduled Task

The platform **scheduling foundation**: a cadence intent stored in Postgres that commits a next-due Instant (`next_run_at`), consumes a due tick only by minting a domain **Job**, and can be paused or **withdrawn** by the calling domain via opaque **owner_ref**.
Celery Beat reads these rows (single Beat replica). Distinct from any one **Job** instance.
A platform mechanism like **Job**, not a product domain, not a Metadata business object, and **not owned by Source** (no Source FK; scheduler never parses Source).
Operator-facing identity is a closed work kind plus target projected by a **domain facade** (`structure` and `join_detection` targeting a **Source**), not a Celery task name. Facades may register several schedules of each kind that *target* one Source; that target lives in facade/kwargs projection, not as schedule ownership.
Cron wall clock uses **Schedule Timezone**; `last_run_at` is the consumed-due cursor Instant; `next_run_at` is the stored commitment (null when paused). An optional **Running Time Limit** on the definition is copied onto each minted **Job**. Operator run-now enqueues without moving those fields. Observation “last run” joins related **Jobs**.
Console operator copy, docs that name the row, and identifiers whose referent is this entity use **schedule**, not clock.
Avoid storing product schedules only in Redis Beat state or static code when operators need to change them.
Avoid treating Celery `timezone` as the business schedule zone.
Avoid treating a Scheduled Task as a Job, putting cron **on** a **Source**, or treating Source delete as an ORM cascade into schedules.
Avoid scanning schedule kwargs for `source_id` as the withdraw key (use **owner_ref**).
Avoid treating **Kind execution lock** (or the retired phrases “Source catalog-write single-flight” / “structure single-flight”) as a schedule mutex, Beat skip, or schedule HTTP conflict.
Avoid treating Scheduled Task **as** a DAG/workflow; dispatched work may later be those kinds.
Avoid Clock as a product noun, Console label, or identifier for this entity. Avoid renaming Instant test `Clock` / `get_clock`, cron wall-clock English, or ADR file `0025-clock-first-structure-jobs.md`.
Avoid treating stored `next_run_at` as a debt of missed ticks or computing it only on GET.
Avoid treating **Running Time Limit** as cron wall-clock or a global Job env.

### Running Time Limit

An optional positive-second bound on a **Scheduled Task** (`running_timeout_sec`) for how long a minted **Job** may stay `running`. Default, seed, and omit are null: the reaper does not mark `JOB_RUNNING_TIMEOUT`. Mint copies the value onto the Job; the reaper reads only that snapshot. PATCH of the definition does not rewrite in-flight Jobs. The stamp is cooperative (not process kill); the structure runner does not write catalog after it. Console: Running time limit.
Avoid wall-clock, timeout, clock, a global env as the definition, a platform safety cap beside the schedule field, live-reading the schedule at reap time, merging with occupancy / `JOB_WORKER_LOST`, or treating null as a hidden 3600s default.

### owner_ref

Opaque string on a **Scheduled Task** written only by a domain facade (product HTTP cannot set it). Create and withdraw must use the same literal (Metadata structure: `metadata:source:{id}`). Null only for platform system rows. The scheduler stores and matches it; it does not parse domain meaning.

### Withdraw (schedule)

Caller asks the scheduler to delete all non-system definitions matching an **owner_ref** and immediately terminalize unfinished **Jobs** those schedules minted (`cancelled`). Historical Jobs remain. Distinct from pause (`enabled=false`) and from single-row `DELETE /schedules/{id}`.
Avoid “cascade from Source”, “wait for the worker”, or scanning kwargs for Source id.

### Instant

An absolute moment on the timeline, represented as aware UTC in process, `timestamptz` in Postgres, and RFC 3339 on the wire (outbound `Z`).
Contract: [`docs/conventions-time.md`](conventions-time.md).
Avoid wall-clock local time, treating cron hour/minute as a stored Instant, or encoding a viewer’s **Display Timezone** into the Instant wire form.

### Schedule Timezone

An IANA zone on a **Scheduled Task** that interprets **cron** wall-clock fields; ignored for interval schedules; not part of an **Instant** and not the Celery process timezone.
Avoid storing the zone inside a timestamptz Instant, conflating with **Display Timezone**, or assuming interval schedules shift when the zone changes.
Avoid calling **Running Time Limit** wall-clock.

### Operations Nav Group

The Console Navigation group with stable id `operations` for platform-wide **Job** observe and domain **Scheduled Task** definition modules.
Console IA only; not a product domain.
Avoid mounting these modules under **Metadata**, Administration, or Platform Settings.
Avoid treating the group as a synonym for **Job**.

## Metadata Foundation

### Source

A registered data origin whose catalog refraq owns. Slice A covers live databases (for example U9 or MES); later kinds may include static imports such as CSV.
Has a stable key, display name, `kind`, and kind-specific catalog scope (for database: engine-dialect keys inside `access` such as `database`/`schema` or `service_name`/`owner`); not a login directory.
For `kind=database`, the Source also carries `engine` and a per-engine validated `access` document (secrets and scope inside; whole document encrypted at rest). Non-database kinds may omit those fields.
Avoid calling it Identity Source or Client. Avoid assuming every Source is an enterprise application. Avoid treating reachability as a separate reusable entity. Avoid fixed top-level `database_name` / `schema_filter` beside `access`.

### Structure Diff

A persisted record of structural changes committed by one successful structure **Job**, belonging to exactly one **Source**. Full locators live here; Job result holds only class, counts, and the Diff id.
Avoid Catalog Snapshot, Drift entity, Job child table, using the Diff as the live catalog, or treating Diff `class` as a Job list or detail field.

### Catalog Object

A collected structural unit (table, view, materialized view, or equivalent) under exactly one Source, including columns, constraints when collected, and optional DDL.
Avoid calling a Catalog Object a Data Product or Business Entity.
Avoid treating catalog identity as anything other than Source-scoped.

### Current catalog

The live Catalog Objects under a Source after the last successful structure Job, including tombstones (`is_present=false`). Authoritative; not versioned per Job.
The Per-Source object list pages this set as summaries (optional literal substring on schema, technical name, or business name; optional filter on **Object Semantics** readiness). Columns, foreign keys, indexes, and DDL are not part of that list projection.
Avoid Catalog Snapshot; avoid treating **Structure Diff** as the live catalog; avoid requiring a search query to page a Source's objects; avoid matching locator or business description on list `q`.

### Locator

A readable unique key addressing a Source (`src/…`), Catalog Object (`obj/…`), or column (`col/…`).
Derived from natural keys; MCP is locator-first; HTTP echoes `locator_key` on responses.
Avoid treating it as a second identity or requiring agents to use opaque surrogate ids.

### Object Semantics

Business meaning fields on a Catalog Object (name, description, category, grain, business primary key, Business Domain reference, evidence, open questions, and readiness).
Every field must pass the ADR 0015 admission criteria; time/status semantics, relation summary, and confidence were removed by that ADR.
Avoid inventing meaning without evidence; persist open questions instead.
Avoid electing one "primary" column out of several of the same kind at object level — that is a use-time choice, not a source fact.

### Business Domain

A global flat registry entity with immutable `code` and mutable `name` that Catalog Objects reference (ADR 0017).
Console Module `business-domains` reuses `metadata:read` / `metadata:write`.
Avoid free-text domain labels on objects; avoid hierarchical domain trees in this phase.

### Semantic Type

Optional free-text annotation on a column's `column_semantics.semantic_type`.
A closed vocabulary and derived completeness gaps are deferred until a concrete reader exists (ADR 0016).
Several columns on one object may each describe a time axis; there is no elected primary axis.
Avoid re-introducing object-level primary time or status fields.
Avoid conflating with **Normalized Type**.

### Normalized Type

A closed coarse physical type on a catalog column (`string` | `integer` | `number` | `boolean` | `date` | `timestamp` | `time` | `interval` | `binary` | `json` | `array` | `unknown`). On a database-kind Source it is assigned by a **Type Mapping** for that `engine` and native type. The value on a column is the snapshot from the last successful structure **Job**, not a live lookup.
`type_changed` on a **Structure Diff** compares native `data_type` strings, not Normalized Type.
Avoid replacing native `data_type`; avoid **Semantic Type**; avoid treating Normalized Type as MCP catalog payload.

### Type Mapping

A global rule that assigns one **Normalized Type** to one native type of one `engine` (ADR 0024). Unique on `(engine, native type)`. The native type is parameter-free: `varchar(50)` and `varchar(100)` share one mapping; aliases such as `varchar` and `character varying` are distinct. Product seed mappings are immutable. A structure **Job** records a mapping with `unknown` when it first sees a native type that has no row. Console Module `type-mappings` lists mappings and may PATCH a non-seed row (`metadata:read` / `metadata:write`); no CREATE or DELETE.
Avoid Source-local type override; avoid a code dict or sqlglot DType as the catalog; avoid treating Type Mapping as per-operator personalization of product seeds.

### Type Mapping Origin

Whether a **Type Mapping** is the product seed (`product`), was recorded by a structure **Job** (`job`), or was assigned by an operator as gap-fill (`user`).
Avoid **Semantic Source**, **Join Origin**, treating origin as an audit log, or treating origin as per-Source personalization.

### Enum Catalog

Discrete `{ code, label, description }` entries on a column when evidenced.
Avoid unconstrained free-form maps without codes.

### Semantic Source

Provenance tag on semantics writes (`mcp`, `user_input`).
Records the last write; field-level MCP protection is deferred (ADR 0014).
Avoid conflating with **Source** (data origin) or **Identity Source**.

### Join Origin

First attester of a directed column pair, recorded on the **Join Change** create event: `foreign_key`, `sql_lineage`, `human`, or `mcp`. Not a column on the live join row. Not a rank and not the current witness.
`sql_lineage` is a discovered SQL attestation, not a claim that current DDL still contains the join.
Avoid storing Join Origin on `catalog_joins`; treating origin as authority, precedence, last-writer, or “FK still present”; encoding **Join Rejection** as an origin value.

### Join Change

An append-only fact ledger on a directed column pair: create (includes first attester / **Join Origin**), human/MCP amend, **Join Rejection**, restore. Not a **Management Audit Event** and not a **Structure Diff**. List, **Join Path**, and public join HTTP do not read it. There is no PAT/MCP resource. A collected FK disappearing is recorded on **Structure Diff** (`fk_removed`) and Current catalog foreign keys; it does not append here and does not mutate the join row. Join detection does not append when the pair already has a row.
Avoid appending “still seen” or SQL corroboration; writing automatic lineage into **Management Audit Event**; stuffing join lineage into **Structure Diff**; recording FK-gone as a join-row reclaim or delete; joining **Join Change** on catalog list or path reads.

### Join Rejection

A durable operator judgment that a directed column pair carries no relationship. Stored as `rejected_at` (and `rejected_by_user_id`) on the unique join row; evidence stays. Rejected pairs are omitted from **Join Path**. List endpoints include rejected rows by default. Single HTTP/MCP create or amend on a rejected pair is refused. Batch create / `upsert_joins` report rejected pairs without restoring. Automatic Jobs skip an existing row, including a rejected one. A later collected FK does not restore. FK collection and Structure Diff are unaffected.
Avoid a second uniqueness table, implicit revive by upsert or by structure seeing a FK, treating rejection as a delete, or writing **Join Rejection** because a collected FK disappeared.

### Join Path

A multi-hop chain of join edges discovered by graph search between objects or columns. It walks a join when endpoint columns are present and the pair is not rejected.
Avoid guessing paths from column-name similarity alone. Avoid walking rejected joins as relationships. Avoid gating the path on current FK, SQL discovery, User create, or **Join Origin**.

### Catalog Sample

A first-class live peek of rows for one Catalog Object: structured filters and offset/limit pagination, platform-compiled dialect SQL, readonly execution guards.
Permission: `catalog:sample`. Not an Explore, not Controlled Query UI sugar, and not an MCP tool in this phase.

### Controlled Query

Caller-submitted single read-only SQL against a Source, guarded by platform AST allowlist, timeout, row cap, and audit.
Permission: `query:run`. Distinct from Catalog Sample.

### Metadata Nav Group

The Console Navigation group with stable id `metadata` for Sources, catalog browsing, Business Domains, and Type Mappings.
Avoid mounting these modules under Administration or a Data products group.
Avoid mounting **Job** or **Scheduled Task** modules here — those belong to the **Operations Nav Group**.

### Management Audit Event

A persisted record of a sensitive management-plane action (who, when, resource, action, result) for metadata and related credentials.
Avoid treating it as a full platform SIEM or a substitute for application access logs.

## Auth Concepts

### Authentication

The process of proving User identity, through Console login/Session validation or User PAT Bearer validation.

### Authorization

The process of deciding whether an authenticated User can access a route or perform an action, based on their Role's permissions.

### Protected Route

A frontend route that requires a valid authenticated Session (Console); APIs may equivalently accept a User PAT.

### Forbidden

The state where a user is authenticated but does not hold the required permission.
Mapped to HTTP `403`.

### Unauthenticated

The state where no valid Session or User PAT is present.
Mapped to HTTP `401`.

### API Contract

The agreed request and response shape between frontend and backend.

### Offset Page

The platform envelope for a paged collection list: `{ "items", "total", "limit", "offset" }`. `total` is the filtered set. Newest-first pages order by `created_at DESC` with an `id` tiebreaker.
Contract: [`docs/conventions-pagination.md`](conventions-pagination.md).
Avoid `{items}`-only collection responses for new lists; avoid `total_count`; avoid a Cursor Page without ADR admission; avoid treating page bounds as Job retention.

## Repository And Process

### Project Boundary

The rule that new refraq code is implemented inside refraq as the standalone implementation home of the product.
Concretely, new logic belongs only in `backend/` and `frontend/`, not in the old system.
Avoid a hybrid home or temporary dual-write.

### Process Document

A transient repository document that captures execution sequencing or working guidance for a specific implementation phase.
Avoid treating it as a canonical spec, a durable product document, or a governance rule.

### Process Workspace

A repository-local location dedicated to Process Documents and excluded from the versioned product baseline.
In this repository it is `.process/`.
Avoid treating it as the docs directory or the committed documentation set.

### Agent Protocol Entry

A repository-root file with a conventional name that tooling may discover automatically to load stable repository guidance.
In this repository the root `AGENTS.md` is the Agent Protocol Entry.
Avoid treating it as a transient process note or a business specification.
