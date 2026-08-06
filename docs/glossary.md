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

A revocable personal access token owned by a User for non-browser API and MCP access (`Authorization: Bearer`).
Coexists with Console Session cookies; authenticates the same User and Role permissions.
Avoid calling it a Client token, a Session id reused as Bearer, or a machine principal.

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

The product-owned locked Role `super_admin`: stable identity, not editable via Role APIs, permissions always equal the current Permission catalog.
Aligned only by **Foundation Upgrade**, not by ordinary Role edits or Site Bootstrap on a non-empty store.
Avoid calling every seeded role a System Role (`operator` is a seeded ordinary role).

### Foundation Upgrade

The official product upgrade path: schema migration under advisory lock, then ensure of the System Role.
Does not create or rewrite Users, and does not reset editable roles.
Invoked as `python -m backend.core.upgrade` or as the first phase of `python -m backend.core.entry`.

### Site Bootstrap

First-time empty-store initialization: insert seed roles when none exist; create the initial admin User when no users exist.
Does not realign permissions on an already-present System Role.
Runs from the API process lifespan (and must not be confused with Foundation Upgrade).

### Permission

A concrete allowed action expressed as `resource:action`, such as `dashboard:read`, `console:access`, `settings:read`, or `sources:read`.
Chosen only from a fixed catalog when editing Roles.
Avoid reducing it to a menu or a page label.
Avoid free-form permission strings invented in the UI.

## Metadata Foundation

### Source

A registered data origin whose catalog refraq owns. Slice A covers live databases (for example U9 or MES); later kinds may include static imports such as CSV.
Has a stable key, display name, `kind`, and kind-specific catalog scope (for database: database name and optional schema filter); not a login directory.
Avoid calling it Identity Source, Connection, or Client. Avoid assuming every Source is an enterprise application.

### Connection

Live reachability and credentials for a Source that needs them: host, port, engine, encrypted username/secret (database endpoints in slice A).
Does not own database name or schema scope; collectors compose Source scope with Connection endpoint.
A Source may have one or more Connections; catalog identity stays on the Source.
Avoid calling the Connection the Source, or treating Identity Source as a Connection.
Avoid forcing non-live Source kinds through Connection.
Avoid putting catalog scope on Connection.

### Job

A single durable asynchronous execution with an observable lifecycle (queued → running → terminal), discriminated by kind, carrying only a generic input payload that each domain interprets.
Domains expose enqueue/list facades (for example under Source for structure work); the Job record is not owned by Connection or Source.
API (or a **Scheduled Task**) enqueues; a Celery worker executes; operator-visible status lives on the Postgres job record.
Avoid calling it an Ingestion Job. Avoid running long work inside the Management Console API request.
Avoid treating a Job as a **Scheduled Task**, or reading Celery result/Flower as the product lifecycle.
Avoid promoting domain foreign keys into universal Job fields.

### Scheduled Task

A platform schedule definition (interval or cron) stored in Postgres that triggers work when due.
Celery Beat reads these rows (single Beat replica). Distinct from any one **Job** instance.
Avoid storing product schedules only in Redis Beat state or static code when operators need to change them.

### Catalog Object

A collected structural unit (table, view, or equivalent) under exactly one Source, including columns and optional DDL.
Avoid calling a Catalog Object a Data Product or Business Entity.
Avoid binding catalog identity to a Connection.

### Metadata Nav Group

The Console Navigation group with stable id `metadata` for Sources, Jobs, and catalog browsing modules.
Avoid mounting these modules under Administration or a Data products group.

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
