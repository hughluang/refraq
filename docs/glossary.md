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

The Console Module for platform system parameters (non-secret operational configuration exposed in the Console).
Distinct from Administration master data (Users / Roles).
Avoid conflating it with user preferences or Data Product governance.

### Settings Override

An in-process runtime overlay over env-backed Settings for a narrow writable set (session TTL in this slice).
Restart clears it; it is not a Store Backend and must not mutate `core` Settings objects as the source of truth.
Avoid calling it persistent configuration or feature flags.

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
Avoid conflating with platform Settings / system parameters, or treating User PAT as a sidebar Administration module.

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
Domains mint structure **Jobs** only via a **Scheduled Task** (due tick or run-now); the Job record is not owned by Source and is not a Metadata business object.
API (or a **Scheduled Task**) enqueues; a Celery worker executes; operator-visible status lives on the Postgres job record.
Lifecycle stamps (`created_at`, `started_at`, `finished_at`, log line times) are **Instants**.
Successful Jobs may carry a nullable generic **Job result**; failed/cancelled/fail-safe Jobs leave it null.
Avoid calling it an Ingestion Job. Avoid running long work inside the Management Console API request.
Avoid treating a Job as a **Scheduled Task**, or reading Celery result/Flower as the product lifecycle.
Avoid promoting domain foreign keys into universal Job fields.
Avoid promoting kind-specific result fields (for example structure `class`) into universal Job fields.
Avoid overloading enqueue **summary** with outcome, or writing `{}` to mean “no result”.

### Job result

A nullable JSON outcome written when a Job reaches a successful terminal state. The platform does not interpret the document; each `kind` supplies its envelope (structure: `class`, `counts`, `structure_diff_id`).
Avoid Celery result backend, **Management Audit Event** `result`, treating result as whether the Job succeeded, or treating structure `class` as a public Job attribute. Console Job detail may show the document uninterpreted; classification is read on **Structure Diff**.

### Scheduled Task

A platform schedule definition (interval or cron) stored in Postgres that triggers work when due, and the only Console/HTTP/MCP path that mints domain **Jobs**.
Celery Beat reads these rows (single Beat replica). Distinct from any one **Job** instance.
A platform mechanism like **Job**, not a product domain, not a Metadata business object, and not a field of **Source**.
Operator identity is a closed work kind plus target, not a Celery task name. Several structure schedules may target one Source. Cron wall clock uses **Schedule Timezone**; `last_run_at` is an **Instant** cursor (missed cron slots are skipped). Operator run-now enqueues without moving that cursor.
Console operator copy, docs that name the row, and identifiers whose referent is this entity use **schedule**, not clock.
Avoid storing product schedules only in Redis Beat state or static code when operators need to change them.
Avoid treating Celery `timezone` as the business schedule zone.
Avoid treating a Scheduled Task as a Job, or putting cron on a **Source**.
Avoid treating structure single-flight as a schedule mutex.
Avoid Clock as a product noun, Console label, or identifier for this entity. Avoid renaming Instant test `Clock` / `get_clock`, cron wall-clock English, or ADR file `0025-clock-first-structure-jobs.md`.

### Instant

An absolute moment on the timeline, represented as aware UTC in process, `timestamptz` in Postgres, and RFC 3339 on the wire (outbound `Z`).
Contract: [`docs/conventions-time.md`](conventions-time.md).
Avoid wall-clock local time, treating cron hour/minute as a stored Instant, or encoding a viewer’s **Display Timezone** into the Instant wire form.

### Schedule Timezone

An IANA zone on a **Scheduled Task** that interprets **cron** wall-clock fields; ignored for interval schedules; not part of an **Instant** and not the Celery process timezone.
Avoid storing the zone inside a timestamptz Instant, conflating with **Display Timezone**, or assuming interval schedules shift when the zone changes.

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

Creation provenance of a join edge: `foreign_key`, `human`, or `mcp`.
Structure refresh must not delete human/mcp edges.

### Join Path

A multi-hop chain of join edges discovered by graph search between objects or columns.
Avoid guessing paths from column-name similarity alone.

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
