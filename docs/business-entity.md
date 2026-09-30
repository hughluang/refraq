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

A Business Entity is identified by an immutable `table_name`. That value is the stem view name in the entity database (§4.3) and spans every **Entity Version** of the Entity. It is unique across the platform.

`table_name` is the business name of the Entity and the name of a view in the entity database. It is lowercase ASCII letters, digits, and underscores; it starts with a letter; length at most 63, the identifier limit. It must not match a physical table name: one or more characters, then `__v`, one or more digits, `__`, and 16 lowercase hexadecimal digits (for example `material__v1__0123456789abcdef`). A `table_name` outside those constraints is rejected with `ENTITY_TABLE_NAME_INVALID`. A `table_name` already registered is rejected with `ENTITY_TABLE_NAME_DUP`.

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

A version may declare no attributes while unpublished. Each attribute has one **Attribute Type** and a `config` object for that type. Attributes share one name namespace inside an **Entity Version**. There is no `kind`.

The closed set is `string`, `text`, `integer`, `decimal`, `number`, `boolean`, `date`, `timestamp`, `time`, `json`, `dictionary`, and `reference`. It is not the **Normalized Type** set. Normalized Type stays the catalog column vocabulary assigned by **Type Mapping**. **Semantic Type**, a JSON Schema or OpenAPI format, a unit, a quantity, a multi-value, a file, a localized label, and `array` are not members and are not config keys. A JSON array is a value of `json`, not its own type. A unit or quantity, if added later, is a new type or a composite value, not a key of `decimal` config. A multi-value is not a cardinality on `reference` config. A dictionary is not a constraint on `string` or `integer`.

Every attribute also declares whether it is `required`, whether it is `unique`, whether it is `indexed`, and an optional `description`. `required`, `unique`, and `indexed` default to false. A `number` attribute may be unique or indexed. It is a poor business key: the value is approximate and may be NaN.

`string` requires `config.max_length`, an integer from 1 through 65535. There is no default. 65535 is the product cap for a bounded string, not a ceiling for all text and not the Postgres `VARCHAR` limit. Longer or unbounded text is `text`.

`text`, `integer`, `number`, `boolean`, `date`, `timestamp`, `time`, and `json` require `config` to be `{}`. `timestamp` is one instant. The attribute does not choose a timezone. `json` carries a JSON document, including a JSON array, and does not carry a schema, a path, or a format.

`decimal` requires `config.precision` (an integer from 1 through 1000) and `config.scale` (an integer from 0 through `precision`). There is no default.

`dictionary` is its own type. `config.dictionary_id` is required and is the only config key. It names one **Dictionary** (§2.5). The attribute does not own codes. `entries` on an attribute is `ENTITY_ATTRIBUTE_INVALID`. An integer code is not a second code kind. A later locale map for labels must not change the column type. When a version read includes attributes, a `dictionary` also carries a read-only `dictionary` of `{ id, name, display_name, deprecated }`, or `null` when the id does not resolve, and `behind` (§2.5). Other attribute types omit both. Neither field is stored on the attribute or accepted on write.

`reference` is an **Entity Reference**. `config.target_entity_id` is required and is the only config key. On write it is `self` or the id of an existing Business Entity that is not deprecated. `self` means the entity of the request and is replaced with that entity's id before the shape is stored. A read never returns `self`. The target may still be unpublished. The same entity may be the target. When a version read includes attributes, a `reference` also carries a read-only `target` of `{ entity_id, name, table_name }`, or `null` when the id does not resolve. Other attribute types omit `target`. `target` is not stored and is not accepted on write. `unique` means at most one row of this entity points at a given target `row_id`. The stored integer may not resolve to a live row. The product does not create a foreign key and does not cascade. Resolving the integer belongs to a **Data Channel**.

A config key that belongs to another type, an unknown config key, or a top-level `kind`, `normalized_type`, `precision`, `scale`, `target_table_name`, `enumeration`, or `entries` is `ENTITY_ATTRIBUTE_INVALID`.

**Inbound Reference** is not an attribute. It is derived when a current version, including this entity's own and including an unpublished current version, has an Entity Reference whose `target_entity_id` is this entity's id. Historical versions do not count. The derived fact carries the referring entity's id and `table_name`, and that attribute's `name`; it has no name or description of its own. A many-to-many is an ordinary Business Entity that declares two Entity References, not a third type and not a link table.

Attribute names are unique within an **Entity Version** and follow the same character set as `table_name` (lowercase ASCII letters, digits, and underscores; starts with a letter), because each attribute becomes a physical column. They are not subject to the reserved physical-table-name rule. The name `row_id` is reserved for the platform primary key (§2.4). Violations, including a missing or unknown type, a `string` without `max_length`, a `decimal` without precision or scale, an illegal dictionary, or a `target_entity_id` that is missing, unknown, or names a deprecated entity, are `ENTITY_ATTRIBUTE_INVALID`; Problem `detail` names the concrete rule.

`unique` is a single-column UNIQUE constraint. A unique attribute may leave `required` false; Postgres treats distinct NULLs as non-conflicting. `indexed` is a non-unique btree. When `unique` is true, publish does not also create a non-unique index for that column. Composite unique constraints and composite indexes are out of scope.

**Attribute Type** is the vocabulary an author uses to define an attribute. **Normalized Type** is the vocabulary a catalog column receives once a **Type Mapping** has classified an engine-native type. The two are not one language. Which source column feeds which attribute belongs to a **Data Channel** and is not stored on the definition.

### 2.4 Platform Row Identity

Every **Entity Table** carries a platform column `row_id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY`. It is not an authorable attribute, is not listed on the definition, and is not a **Data Channel** upsert key. Inserts omit it; uniqueness that a writer cares about lives on attributes marked `unique`.

The column is named `row_id` so it does not occupy `id`, which is the usual source-system primary-key name an agent maps onto an attribute. Its values are short integers so a later `RETURNING` or lineage citation is a single token rather than a UUID.

### 2.5 Dictionary

A **Dictionary** is the shared code set a `dictionary` attribute references. It is not an **Enum Catalog**. An Enum Catalog is evidence attached to a catalog column. A Dictionary is authored, and more than one attribute may name the same one.

A Dictionary has an id, an immutable `name`, a `display_name`, an optional `description`, a `revision`, and an optional `deprecated_at`. `name` is unique, uses the `table_name` character set (lowercase ASCII letters, digits, and underscores; starts with a letter), and is at most 63 characters. `revision` starts at 1 and increases only when the set of active codes changes.

Each entry has a required `code`, an optional `label`, and `active`. A code is a non-empty string of at most 64 characters and is case-sensitive, with no further character-set restriction. A label is at most 200 characters and is a single language. Codes are unique on the list. A code is not renamed. A code that has never appeared in a publish snapshot may be removed. A code that has appeared in a snapshot stays on the list and can only be deactivated. Adding, removing, activating, or deactivating a code changes the active set and increments `revision`. Changing a label, `display_name`, `description`, or order does not. A patch that omits entries does not write entry rows. Concurrent patches of one Dictionary commit one at a time: a patch that includes entries replaces the whole set, and a concurrent patch does not fail as an internal error.

Deprecate sets `deprecated_at`. A deprecated Dictionary cannot be selected by a new dictionary attribute, or by an attribute whose `dictionary_id` changes. An unpublished save may keep an attribute that already names it. Deprecate does not change a published CHECK.

Delete is refused while any **Entity Version** attribute names the Dictionary, or any publish snapshot names it, including a historical version and including a version whose table has been dropped (`DICTIONARY_IN_USE`). Problem `detail` names the referring entities and attributes.

Publish acceptance reads each dictionary attribute's Dictionary once and freezes the active codes and whether that Dictionary is already deprecated into the Job input. A Dictionary with no active code, or an unknown `dictionary_id`, refuses acceptance (`ENTITY_ATTRIBUTE_INVALID`) and does not enqueue. Execution requires the same active code set, and refuses a Dictionary that becomes deprecated after acceptance. Either mismatch fails the Job (`ENTITY_ATTRIBUTE_INVALID`): the version returns to `unpublished` and no table is created. The CHECK and the snapshot codes are the frozen codes. The snapshot stores `dictionary_id`, the Dictionary's `revision` at execution, and those codes. A Dictionary already deprecated at acceptance may still publish when the code set is unchanged. A later edit of the Dictionary does not change the snapshot or the CHECK. The snapshot remains after the table is dropped.

`behind` is true on a dictionary attribute when a publish snapshot for that attribute names its Dictionary and the snapshot `revision` is less than the Dictionary's current `revision`. The snapshot compared is the one stored on the version being read, or, when that version has none, the latest published version's snapshot for the same attribute and Dictionary. A label change does not by itself make an attribute behind, because it does not increase `revision`.

The classifier compares code sets. When a published snapshot exists for the attribute, that snapshot's codes are the baseline and the active codes of the Dictionary named by the proposed attribute are the proposal. Adding codes while every snapshotted code remains is `non_breaking`. Removing a code from the active set is `breaking`. An equal set is `unchanged`, including a change that touches only labels and a switch to another Dictionary with the same codes. The change lists the added codes and the removed codes. When no snapshot exists, the baseline is the active codes of the Dictionary named by the saved attribute. The classifier does not gate save or publish.

## 3. Entity Version, Save, And Publish

### 3.1 A Version Is One Published Shape

An **Entity Version** is one shape under a Business Entity `table_name`, and it owns exactly one **Entity Table**. No Entity Table is shared between versions.

A version stores a publish status: `unpublished`, `publishing`, or `published`. Create and **Open new version** start `unpublished`. Publish is the only act that creates that version's table. A version is published at most once. There is no product path that ALTERs a published table.

A read-only classifier still reports `breaking` / `non_breaking` / `unchanged` for a proposed shape (`docs/api-contracts-entity.md` §3.4). That judgment is not a write gate. An unpublished current version may save any valid shape. Changing **Attribute Type** is breaking, including `string` to `text`, `integer` to `number`, and `integer` to `decimal`. Widening `string` `max_length` is `non_breaking` as a classifier signal and is not an ALTER of a published column. Narrowing `max_length` is breaking. Changing decimal precision or scale is breaking. For a dictionary, the classifier compares code sets as in §2.5. Those classes are not an ALTER of the published CHECK. Changing `target_entity_id` is breaking. Adding an attribute is non-breaking when the new attribute is not required, and breaking when it is. Removing an attribute is breaking.

### 3.2 Save Writes Definition Only

Save writes metadata only. `PATCH` Entity identity may include the current unpublished version's `attributes` on the same request. `PATCH` a version's attributes remains valid. Save does not create or alter a table, does not change publish status, and does not enqueue a Job.

Save is refused when the Entity is deprecated (`ENTITY_DEPRECATED`), when any version of it is `publishing` (`ENTITY_PUBLISHING`), when the target version is not the current version (`ENTITY_VERSION_SUPERSEDED`), or when the current version is not `unpublished` (`ENTITY_NOT_UNPUBLISHED`).

### 3.3 Publish Creates The Table And Locks The Version

Publish targets the current `unpublished` version. It refuses an empty attribute list (`ENTITY_PUBLISH_EMPTY`), a non-unpublished version (`ENTITY_NOT_UNPUBLISHED`), and a deprecated Entity (`ENTITY_DEPRECATED`).

The first publish of an Entity, and any publish whose shape is not `unchanged` relative to the latest published shape, applies the attribute write rules. A reference without `target_entity_id` is `ENTITY_ATTRIBUTE_INVALID` and is not enqueued. An `unchanged` successor of an already published shape is enqueued as stored. Publish does not rewrite that stored shape.

Publish sets the version to `publishing` and enqueues a **Job** (`entity_reconcile`) that creates this version's **Entity Table** (including `row_id`) under the physical name in §4.3. The Job then stores `published` and replaces the stem view so it selects that table. The previous physical table is not renamed. While `publishing`, every write is refused: save, publish, open version, identity patch, delete, and deprecate (`ENTITY_PUBLISHING`).

No transaction spans the metadata database and the entity database. Publish makes that visible as the `publishing` status rather than hiding it behind compensation.

- Job success: status becomes `published`. The stored attribute-set snapshot records the created shape. Display identity and this version's attributes are frozen. The only authoring act left on this Entity is **Open new version**, or **Deprecate** the Entity.
- Job failure: status returns to `unpublished`, including when `published` was stored and the stem view then failed to move. The failure path drops the new physical table when it is still empty. A new table that already has rows is left in place, and a later publish of the same version hits `ENTITY_TABLE_NAME_CONFLICT`. The stem view is left as it was when the replacement did not commit. The definition is unchanged. The author may save and publish again.

Enqueue is idempotent: an in-flight Job for that version is returned rather than duplicated. Execution takes a per-Entity lock shared with table drop (`entity_table:{entity_id}`), and reuses `JOB_ALREADY_ACTIVE`.

A derived `table_present` flag remains: the snapshot is non-empty. It is not the publish status. An existing deployment whose snapshot is already non-empty is treated as `published` on upgrade.

### 3.4 Open New Version

Opening the next version is permitted only when the current version is `published` and the Entity is not deprecated. Otherwise `ENTITY_NOT_PUBLISHED` or `ENTITY_DEPRECATED`.

The new version starts as a copy of the current version's saved shape and is `unpublished`. Its table does not exist until that version is published. The prior version becomes superseded. The prior version's table and rows are untouched.

The body may overlay that copy. The overlay is classified against the published shape before any write rule runs. An `unchanged` result, including an omitted `attributes` field, stores a copy of the published attributes and does not re-apply write rules. A changed overlay must satisfy the same write rules as save. A reference without `target_entity_id` on that changed overlay is `ENTITY_ATTRIBUTE_INVALID`.

While the new version is unpublished, display identity (`name`, `description`) is writable again. `table_name` stays immutable. Publishing the new version freezes display identity once more.

### 3.5 Deprecate

Deprecate is an Entity-level terminal act. Versions do not have a deprecated status; they only iterate.

Deprecate is permitted only when the Entity has been published at least once (`ENTITY_NEVER_PUBLISHED` otherwise). It is refused while any version is `publishing`. It is refused when a current version, including this entity's own, has an **Entity Reference** whose target is this entity (`ENTITY_REFERENCED`); a historical version does not count. It cannot be undone (`ENTITY_ALREADY_DEPRECATED` on a second call).

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

The Job creates that version's physical table under the name in §4.3. It does not ALTER a published table's columns. Publishing a successor leaves the previous physical table in place and, after the version is `published`, replaces the stem view so it selects the new table. A name collision with a relation already present in the entity schema fails the Job with `ENTITY_TABLE_NAME_CONFLICT` and is never auto-suffixed around the collision.

The product head is the latest published version that still has a table. That fact is metadata. The stem view is updated after `published` is stored. Until that update commits, SQL against the stem still reads the previous table. Product writes, including a later **Data Channel**, address the head's physical table and do not write a superseded version. Direct SQL against a physical table name is not revoked by this rule. Write admission itself belongs to **Data Channel** and is not implemented here.

### 4.3 Physical Naming And Collision

The Entity has one `table_name` (the stem). That name is a view. Each version's physical table name is derived, never stored, and never renamed. It is the stem, then `__v`, then the version number with no zero-padding, then `__`, then the version id. A version id is 16 lowercase hexadecimal digits and has no prefix. Stem `material`, version `1`, and id `0123456789abcdef` produce `material__v1__0123456789abcdef`.

The application composes that name and keeps it within 63 characters. It does not send a longer identifier to the engine. When the stem and the suffix together exceed 63 characters, the stem is shortened from the right until the name is exactly 63 characters. The suffix stays whole. A version number is a 32-bit integer, at most 10 digits, so the suffix is at most 31 characters and at least 32 characters of the stem remain. When the stem is shortened, publish writes `COMMENT ON TABLE` set to the full stem. When the stem fits, publish writes no comment. An `encv_` prefix is not a version id and is not a physical table name.

Reported names:

- No table (`table_present` is false, including unpublished versions): the version's reported `table_name` is `null`.
- A version that still has a table reports the composed physical name.

Opening a new version does not move the view. The prior published version keeps its physical table until a successor publish marks the new version `published` and then replaces the view. A later **Data Channel** binds by **Entity Version** id and writes only when that version is the head.

All DDL is schema-qualified against the configured entity schema (`REFRAQ_ENTITY_DB_SCHEMA`, default `public`). The product uses that schema and never creates it. Emptiness and collision checks are evaluated in that schema so their meaning does not drift with a connection-level `search_path`.

Two Business Entities cannot collide, because `table_name` is unique. A physical table name, or the stem view, may still collide with a relation already present in that schema. Publish then fails with `ENTITY_TABLE_NAME_CONFLICT`. refraq does not rename around a collision.

Constraints and indexes are named from the physical table, so two versions do not share them. Publish does not rename a superseded table.

### 4.4 Attribute Type To Physical Type

Each **Attribute Type** maps to one physical type in the entity database engine. That mapping is product-owned and fixed; it is not a maintainable registry and not a **System Parameter**. It differs from **Type Mapping**, which classifies many engines' native types *into* **Normalized Type**. Here there is a single target engine and no second type registry for an operator to maintain. `string` is `VARCHAR(max_length)`. `text` is `TEXT`. `integer` is `BIGINT`. `decimal` is `NUMERIC(precision, scale)`. `number` is `DOUBLE PRECISION`. `boolean`, `date`, `timestamp`, and `time` are `BOOLEAN`, `DATE`, `TIMESTAMPTZ`, and `TIME`. `json` is `JSONB`. `dictionary` is `VARCHAR(64)` plus a CHECK that non-null values are members of the codes snapshotted from the **Dictionary** at publish; `required` decides whether the column is `NOT NULL`. It is not a Postgres ENUM. Changing the Dictionary does not `ALTER` that CHECK. An **Entity Reference** is `BIGINT` and is not a foreign key. An **Inbound Reference** creates no column. Publish creates that version's empty physical table, then replaces the stem view after the version is `published`. It does not `ALTER` a published column or CHECK when the classifier reports `non_breaking` for a wider `max_length` or an added code. Publishing a successor does not rewrite `row_id` values already stored in referring tables.

## 5. Supersession And Disposal

A version is **superseded** when a newer version exists. Supersession is a derived fact — not a stored flag, and not something a user does.

Deleting a definition never drops a table. Deleting a never-published Business Entity removes definition rows only.

Delete is permitted only when the Entity has never been published (`ENTITY_ALREADY_PUBLISHED` otherwise) and no current version, including this entity's own, has an **Entity Reference** whose target is this entity (`ENTITY_REFERENCED` otherwise). A historical version does not count. A never-published Entity has no table; delete removes definition rows only.

Dropping an **Entity Table** is a separate destructive act behind its own **Permission** (§6). It runs as a **Job** (`entity_table_drop`). While the Entity is not deprecated, drop is permitted only on a published version that is not the metadata head (the latest published version that still has a table). The head may be dropped only after the Entity is deprecated, and that drop also drops the stem view in the same entity-database transaction. Drop of the table still in service — the metadata head while the Entity is not deprecated — is `ENTITY_TABLE_IN_SERVICE`. Opening a newer unpublished version does not move the head, so the prior version remains undeletable until a successor publish stores `published`, or the Entity is deprecated. Drop is refused while the table holds rows, rejected with `ENTITY_TABLE_NOT_EMPTY`, and emptiness is checked in the same transaction as the drop. Because refraq owns the entity database, emptiness is a fact it reads rather than a policy it assumes. Emptying a table is the operator's act in the entity database, not a product path.

It is refused while a **Data Channel** references any version, rejected with `ENTITY_IN_USE`.

## 6. Authorization

| Permission | Grants |
| --- | --- |
| `entity:read` | Read Business Entity definitions, versions, and attributes, and read **Dictionaries** |
| `entity:write` | Create and save unpublished definitions, publish, open versions, deprecate, and delete a never-published definition; create, update, and delete **Dictionaries** |
| `entity:drop_table` | Enqueue an **Entity Table** drop (§5) |

`entity:drop_table` is in the Permission catalog and is not seeded onto the `operator` **Role**. It is not implied by `entity:write`.

## 7. Management Console

Business Entity management mounts as Console module `entities` under nav group `entity`. **Dictionary** management mounts as Console module `dictionaries` in that same group. Neither is mounted under the `metadata` nav group, which covers Sources, catalog browsing, Business Domains, and Type Mappings.

The Console presents definitions, versions with stored publish status, and attributes. Entity status and version publish status are different facts. Each fact appears once on a screen.

Entity status is derived, not stored. It is **Deprecated** when `deprecated_at` is set. Otherwise it is **In service** when the Entity has ever been published: a live table cannot be dropped until the Entity is deprecated, and opening another version does not remove the table still in service. Otherwise it is **Not in service**, including while the first publish has not succeeded. Deprecate wins, so a deprecated Entity does not also show whether a table remains.

The list shows entity status and the current version's publish status. The page title shows entity status. Each version row shows that version's publish status, attribute count, created time, and latest publish Job, including after the Entity is deprecated. A row action opens a read-only view of that version's saved attributes. The overview shows the current version's publish Job and does not repeat a version status.

The Console list filters by entity status. The control opens on **Not in service** and **In service** and sends that selection as `status`. The list API applies an entity-status predicate only when `status` is present.

The list's table name opens the record. A row offers the same lifecycle and standard verbs as the record header, under the same gates: Publish, Open new version, Deprecate, Edit, and Delete. Open new version from the list asks for confirmation, then opens the edit route. Publish, Deprecate, and Delete ask for confirmation and leave the operator on the list. The record header is unchanged, including Open new version without a confirmation. Drop table stays on the version row.

`entities` is a record authoring surface (`docs/ui-console-record-form.md`). Create, show, and edit share one layout. Identity and attributes are authored on create and, while the current version is unpublished, on edit. Show renders the same fields in display mode. Visiting edit when authoring is refused redirects to show.

Page actions:

- Unpublished: Save (definition) on create and edit; Publish on show and edit. Publish is disabled while the form is dirty or the saved shape is empty.
- Published: Open new version and Deprecate.
- Publishing: no write actions.
- Deprecated: no authoring actions; table drop remains for holders of `entity:drop_table`.
- Delete appears only when the Entity has never been published.

Where a **Data Channel** module mounts is out of scope for this document.

## 8. Management Audit

Persist a **Management Audit Event** for: Business Entity create, definition save, version open, publish enqueue, deprecate, definition delete, and table drop enqueue; and for **Dictionary** create, update, and delete. Each event records actor, **Instant**, resource, action, and result.

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
11. A hierarchy or inheritance between Business Entities. An **Inbound Reference** is not a saved relationship, and a many-to-many is not a link table or a relationship-entity subtype.
12. Exposing Business Entity on the **MCP endpoint**.
13. **Semantic Type**, or a JSON Schema or OpenAPI format, as an **Attribute Type**.
14. A unit or quantity on a `decimal` attribute. A later quantity is a new type or a composite value, not a `decimal` config key.
15. A multi-value attribute, including a cardinality on `reference` config. A many-to-many stays two **Entity Reference**s on an ordinary Business Entity.
16. A dictionary as a constraint on a `string` or `integer` attribute, or an integer code kind.

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
