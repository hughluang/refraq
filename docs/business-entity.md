# refraq Business Rules: Entity

## 1. Scope

This document defines the **Business Entity** surface: how a reusable business thing is declared, what meaning its declaration must carry, how an unpublished version is saved, how **Publish** creates that version's **Entity Table**, how a published Entity is locked and iterated, how an Entity is deprecated, and how a never-published definition is deleted. It defines the authorization, Console, and audit rules for that surface. The surface is Console HTTP. The **MCP endpoint** does not expose Business Entity.

It does not define how rows reach an Entity Table. Mapping a source column onto an attribute, transforming values, moving rows, and recording lineage belong to a **Data Channel**, which is a separate domain. It also does not define a read path for Entity Table contents.

Related boundaries:

- Sources, catalog, **Object Semantics**, **Normalized Type**, and read-only **Controlled Query**: `docs/business-metadata.md`. Sources stay read-only registered data origins; refraq does not create tables inside one.
- Platform **Job**: `docs/business-jobs.md`. Platform **Scheduled Task**: `docs/business-scheduled-tasks.md`. Publish and table drop use the Job mechanism and do not make Entity a scheduling domain.
- **Permission** and role grants: `docs/business-login-auth.md`.
- HTTP contract: `docs/api-contracts-entity.md`.
- Console shell and module registration: `docs/business-management-console.md`.
- Problem Codes and error envelope: `docs/conventions-errors.md`. List envelopes: `docs/conventions-pagination.md`. **Instant** handling: `docs/conventions-time.md`.
- Connection settings and variable ownership: `docs/env.md`.
- Terminology: `docs/glossary.md`.

## 2. Business Entity Definition

### 2.1 Identity

A Business Entity is identified by an immutable `table_name`. That value is the live physical table name in the entity database (§4.3) and spans every **Entity Version** of the Entity. It is unique across the platform.

`table_name` is constrained because it is a physical table identifier: lowercase ASCII letters, digits, and underscores; it starts with a letter; length at most 48 so `{table_name}__rfq_v{version}` stays inside the entity-database identifier limit (63 bytes); and it must not match `.*__rfq_v[0-9]+$`, which is reserved for superseded tables. A `table_name` outside those constraints is rejected with `ENTITY_TABLE_NAME_INVALID`. A `table_name` already registered is rejected with `ENTITY_TABLE_NAME_DUP`.

A Business Entity is not scoped to a **Source**. It may describe a business thing whose rows will later be assembled from several Sources.

### 2.2 Required Meaning

A Business Entity exists only because a person authored it, so the product requires meaning at declaration time rather than accepting a bare shape. These fields are required:

| Field | Rule |
| --- | --- |
| `table_name` | §2.1 |
| `name` | Short display name |
| `description` | Natural-language statement of what the business thing is |

Shape is declared as `attributes` (§2.3). The list may be empty on an unpublished version. Publish refuses an empty list (`ENTITY_PUBLISH_EMPTY`).

Display identity (`name`, `description`) is one set for the whole Entity. It is writable only while the current version is unpublished and the Entity is not deprecated. `table_name` never changes after create.

The definition carries no source binding, extract SQL, transform, dependency graph, or lineage. Those are **Data Channel** concerns and are out of scope for this document.

### 2.3 Attributes

A version may declare no attributes while unpublished. When present, an attribute declares a `name`, a type from the **Normalized Type** closed set (`string`, `integer`, `number`, `boolean`, `date`, `timestamp`, `time`, `interval`, `binary`, `json`, `array`, `unknown`), whether it is nullable, whether it is `unique`, whether it is `indexed`, and an optional `description`. `unique` and `indexed` default to false.

Attribute names are unique within an **Entity Version** and follow the same character set as `table_name` (lowercase ASCII letters, digits, and underscores; starts with a letter), because each becomes a physical column. They are not subject to the reserved archive-suffix rule. The name `row_id` is reserved for the platform primary key (§2.4). Violations are `ENTITY_ATTRIBUTE_INVALID`; Problem `detail` names the concrete rule.

`unique` is a single-column UNIQUE constraint. A unique attribute may be nullable; Postgres treats distinct NULLs as non-conflicting. `indexed` is a non-unique btree. When `unique` is true, publish does not also create a non-unique index for that column. Composite unique constraints and composite indexes are out of scope.

The Normalized Type set is the platform's portable type vocabulary: it is what a catalog column carries once a **Type Mapping** has classified its engine-native type. Using it on Entity attributes means one type language spans the catalog a modeller reads and the Entity they declare, whatever engines the rows will later come from.

### 2.4 Platform Row Identity

Every **Entity Table** carries a platform column `row_id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY`. It is not an authorable attribute, is not listed on the definition, and is not a **Data Channel** upsert key. Inserts omit it; uniqueness that a writer cares about lives on attributes marked `unique`.

The column is named `row_id` so it does not occupy `id`, which is the usual source-system primary-key name an agent maps onto an attribute. Its values are short integers so a later `RETURNING` or lineage citation is a single token rather than a UUID.

## 3. Entity Version, Save, And Publish

### 3.1 A Version Is One Published Shape

An **Entity Version** is one shape under a Business Entity `table_name`, and it owns exactly one **Entity Table**. No Entity Table is shared between versions.

A version stores a publish status: `unpublished`, `publishing`, or `published`. Create and **Open new version** start `unpublished`. Publish is the only act that creates that version's table. A version is published at most once. There is no product path that ALTERs a published table.

A read-only classifier still reports `breaking` / `non_breaking` / `unchanged` for a proposed shape (`docs/api-contracts-entity.md` §3.4). That judgment is not a write gate. An unpublished current version may save any valid shape.

### 3.2 Save Writes Definition Only

Save writes metadata only. `PATCH` Entity identity may include the current unpublished version's `attributes` on the same request. `PATCH` a version's attributes remains valid. Save does not create or alter a table, does not change publish status, and does not enqueue a Job.

Save is refused when the Entity is deprecated (`ENTITY_DEPRECATED`), when any version of it is `publishing` (`ENTITY_PUBLISHING`), when the target version is not the current version (`ENTITY_VERSION_SUPERSEDED`), or when the current version is not `unpublished` (`ENTITY_NOT_UNPUBLISHED`).

### 3.3 Publish Creates The Table And Locks The Version

Publish targets the current `unpublished` version. It refuses an empty attribute list (`ENTITY_PUBLISH_EMPTY`), a non-unpublished version (`ENTITY_NOT_UNPUBLISHED`), and a deprecated Entity (`ENTITY_DEPRECATED`).

Publish sets the version to `publishing` and enqueues a **Job** (`entity_reconcile`) that creates this version's **Entity Table** (including `row_id`) at the Entity `table_name`. When a previous published version still holds that live name, the same Job first RENAMEs that table to the archive name (§4.3), in one entity-database transaction with the CREATE. While `publishing`, every write is refused: save, publish, open version, identity patch, delete, and deprecate (`ENTITY_PUBLISHING`).

No transaction spans the metadata database and the entity database. Publish makes that visible as the `publishing` status rather than hiding it behind compensation.

- Job success: status becomes `published`. The stored attribute-set snapshot records the created shape. Display identity and this version's attributes are frozen. The only authoring act left on this Entity is **Open new version**, or **Deprecate** the Entity.
- Job failure: status returns to `unpublished`. If the entity-database transaction is still open, it rolls back. If the DDL committed and metadata then failed, the failure path drops the new empty live table and RENAMEs the archived previous table back to `table_name`. The definition is unchanged. The author may save and publish again.

Enqueue is idempotent: an in-flight Job for that version is returned rather than duplicated. Execution takes a per-Entity lock shared with table drop (`entity_table:{entity_id}`), and reuses `JOB_ALREADY_ACTIVE`.

A derived `table_present` flag remains: the snapshot is non-empty. It is not the publish status. An existing deployment whose snapshot is already non-empty is treated as `published` on upgrade.

### 3.4 Open New Version

Opening the next version is permitted only when the current version is `published` and the Entity is not deprecated. Otherwise `ENTITY_NOT_PUBLISHED` or `ENTITY_DEPRECATED`.

The new version starts as a copy of the current version's saved shape and is `unpublished`. Its table does not exist until that version is published. The prior version becomes superseded. The prior version's table and rows are untouched.

While the new version is unpublished, display identity (`name`, `description`) is writable again. `table_name` stays immutable. Publishing the new version freezes display identity once more.

### 3.5 Deprecate

Deprecate is an Entity-level terminal act. Versions do not have a deprecated status; they only iterate.

Deprecate is permitted only when the Entity has been published at least once (`ENTITY_NEVER_PUBLISHED` otherwise). It is refused while any version is `publishing`. It cannot be undone (`ENTITY_ALREADY_DEPRECATED` on a second call).

A deprecated Entity is read-only for authoring: no save, publish, open version, identity patch, or delete. Table drop remains available under §5.

Deprecate is allowed while the current version is still unpublished (for example v2 after a published v1). That unpublished version then cannot be saved or published.

## 4. Entity Table

### 4.1 Where The Table Lives

Entity Tables live in an entity database that refraq owns, declared by its own connection setting separate from the metadata database (`docs/env.md` owns the variable). Keeping the two apart keeps the platform connection budget in `docs/business-metadata.md` honest about metadata volume, and leaves the entity database free to grow with business data.

The connection setting is not required to point at a separate server or a separate database. The product always treats it as a separate engine, a separate pool, and a separate budget line, and never collapses two identical URLs onto one engine. The entity pool exists only in the worker role. API and MCP hold no entity-database connection.

An Entity Table is never created inside a **Source**. A Source is a read-only registered data origin; the only caller SQL refraq sends to one is a single guarded read (**Controlled Query**, **Catalog Sample**).

Entity Tables are not collected as **Catalog Object**s. The Entity definition is already the authoritative statement of their shape.

### 4.2 Publish Is The Create Job

Creating or saving a version has no cross-database side effect. The definition lands first and is immediately readable. The table appears only when Publish succeeds.

The Job creates the live table when absent. It does not ALTER a published table's columns. Publishing a successor RENAMEs the previous live table to its archive name; that is not an ALTER of the new version's shape. A name collision with a table already present in the entity schema fails the Job with `ENTITY_TABLE_NAME_CONFLICT` and is never auto-suffixed around the collision.

Write admission belongs to **Data Channel** and is not implemented here. Being superseded does not freeze Data Channel writes.

### 4.3 Physical Naming And Collision

The Entity has one `table_name` (the stem). Physical names are derived and never stored:

- No table (`table_present` is false, including unpublished versions): the version's reported `table_name` is `null`.
- The latest published version that still has a table occupies the stem (`material`).
- Every earlier published version that still has a table occupies `{table_name}__rfq_v{version}` (`material__rfq_v1`).

Opening a new version does not rename. The prior published version keeps the stem until the successor publish Job succeeds. A later **Data Channel** binds by **Entity Version** id and resolves the physical name at runtime; it must not hard-code the stem onto an archived version.

All DDL is schema-qualified against the configured entity schema (`REFRAQ_ENTITY_DB_SCHEMA`, default `public`). The product uses that schema and never creates it. Emptiness and collision checks are evaluated in that schema so their meaning does not drift with a connection-level `search_path`.

Two Business Entities cannot collide, because `table_name` is unique. A derived archive name, or the stem, may still collide with a table already present in that schema. Publish then fails with `ENTITY_TABLE_NAME_CONFLICT`. refraq does not rename around a collision.

Rename of a superseded table also renames its UNIQUE constraints and indexes so the live stem can reuse product-owned names.

### 4.4 Attribute Type To Physical Type

Each **Normalized Type** maps to one physical type in the entity database engine. That mapping is product-owned and fixed; it is not a maintainable registry and not a **System Parameter**. It differs from **Type Mapping**, which classifies many engines' native types *into* Normalized Type and needs operator gap maintenance because new engines bring new native types. Here there is a single target engine and no business decision for an operator to make.

## 5. Supersession And Disposal

A version is **superseded** when a newer version exists. Supersession is a derived fact — not a stored flag, and not something a user does.

Deleting a definition never drops a table. Deleting a never-published Business Entity removes definition rows only.

Delete is permitted only when the Entity has never been published (`ENTITY_ALREADY_PUBLISHED` otherwise). A never-published Entity has no table; delete removes definition rows only.

Dropping an **Entity Table** is a separate destructive act behind its own **Permission** (§6). It runs as a **Job** (`entity_table_drop`). While the Entity is not deprecated, drop is permitted only on an **archived** version's table (the physical name is not the stem). The live stem table may be dropped only after the Entity is deprecated. Drop of the live table while the Entity is not deprecated is `ENTITY_VERSION_NOT_SUPERSEDED`. Opening a newer unpublished version does not archive the prior table, so that prior version remains undeletable as a table until a successor publish renames it, or the Entity is deprecated. Drop is refused while the table holds rows, rejected with `ENTITY_TABLE_NOT_EMPTY`, and emptiness is checked in the same transaction as the drop. Because refraq owns the entity database, emptiness is a fact it reads rather than a policy it assumes. Emptying a table is the operator's act in the entity database, not a product path.

It is refused while a **Data Channel** references any version, rejected with `ENTITY_IN_USE`.

## 6. Authorization

| Permission | Grants |
| --- | --- |
| `entity:read` | Read Business Entity definitions, versions, and attributes |
| `entity:write` | Create and save unpublished definitions, publish, open versions, deprecate, and delete a never-published definition |
| `entity:drop_table` | Enqueue an **Entity Table** drop (§5) |

`entity:drop_table` is in the Permission catalog and is not seeded onto the `operator` **Role**. It is not implied by `entity:write`.

## 7. Management Console

Business Entity management mounts as Console module `entities` under nav group `entity`. It is not mounted under the `metadata` nav group, which covers Sources, catalog browsing, Business Domains, and Type Mappings.

The Console presents definitions, versions with stored publish status, and attributes. Entity status and version publish status are different facts. Each fact appears once on a screen.

Entity status is derived, not stored. It is **Deprecated** when `deprecated_at` is set. Otherwise it is **In service** when the Entity has ever been published: a live table cannot be dropped until the Entity is deprecated, and opening another version does not remove the table still in service. Otherwise it is **Not in service**, including while the first publish has not succeeded. Deprecate wins, so a deprecated Entity does not also show whether a table remains.

The list shows entity status and the current version's publish status. The page title shows entity status. Each version row shows that version's publish status, including after the Entity is deprecated. The overview shows the publish Job and does not repeat a status.

The Console list filters by entity status. The control opens on **Not in service** and **In service** and sends that selection as `status`. The list API applies an entity-status predicate only when `status` is present.

`entities` is a record authoring surface (`docs/ui-console-record-form.md`). Create, show, and edit share one layout. Identity and attributes are authored on create and, while the current version is unpublished, on edit. Show renders the same fields disabled. Visiting edit when authoring is refused redirects to show.

Page actions:

- Unpublished: Save (definition) on create and edit; Publish on show and edit. Publish is disabled while the form is dirty or the saved shape is empty.
- Published: Open new version and Deprecate.
- Publishing: no write actions.
- Deprecated: no authoring actions; table drop remains for holders of `entity:drop_table`.
- Delete appears only when the Entity has never been published.

Where a **Data Channel** module mounts is out of scope for this document.

## 8. Management Audit

Persist a **Management Audit Event** for: Business Entity create, definition save, version open, publish enqueue, deprecate, definition delete, and table drop enqueue. Each event records actor, **Instant**, resource, action, and result.

## 9. Non-Goals

1. Moving rows into an **Entity Table** — mapping, transform, lineage, cadence, and load runs belong to a **Data Channel**.
2. Any read path for Entity Table contents, including row reads, row counts, and freshness observation.
3. Serving delivery, consumer-facing contracts, and consumer-owned write targets.
4. Composite unique constraints and composite indexes.
5. ALTER of a published **Entity Table**, and any per-Entity schema-evolution policy switch.
6. Dropping a non-empty **Entity Table**, cascading disposal, and reclaiming entity database storage.
7. Consumer-reference graphs and undoing deprecate.
8. Collecting Entity Tables as **Catalog Object**s, or registering the entity database as a **Source**.
9. Creating tables inside a Source, or any write SQL against a Source.
10. Entity-level ACL, per-attribute permissions, and masking.
11. A hierarchy, inheritance, or relationship graph between Business Entities.
12. Exposing Business Entity on the **MCP endpoint**.

## 10. References

- `docs/business-metadata.md`
- `docs/business-jobs.md`
- `docs/business-scheduled-tasks.md`
- `docs/business-login-auth.md`
- `docs/business-management-console.md`
- `docs/conventions-errors.md`
- `docs/conventions-pagination.md`
- `docs/conventions-time.md`
- `docs/env.md`
- `docs/api-contracts-entity.md`
- `docs/ui-console-record-form.md`
- `docs/glossary.md`
