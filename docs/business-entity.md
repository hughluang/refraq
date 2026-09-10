# refraq Business Rules: Entity

## 1. Scope

This document defines the **Business Entity** surface: how a reusable business thing is declared, what meaning its declaration must carry, how its shape may change, how refraq materializes an empty **Entity Table** for it, and how a definition is retired or disposed of. It defines the authorization, Console, and audit rules for that surface.

It does not define how rows reach an Entity Table. Mapping a source column onto an attribute, transforming values, moving rows, and recording lineage belong to a **Data Channel**, which is a separate domain. It also does not define a read path for Entity Table contents.

Related boundaries:

- Sources, catalog, **Object Semantics**, **Normalized Type**, and read-only **Controlled Query**: `docs/business-metadata.md`. Sources stay read-only registered data origins; refraq does not create tables inside one.
- Platform **Job**: `docs/business-jobs.md`. Platform **Scheduled Task**: `docs/business-scheduled-tasks.md`. Materialization uses the Job mechanism and does not make Entity a scheduling domain.
- **Permission**, role grants, and authorization scopes: `docs/business-login-auth.md`.
- Console shell and module registration: `docs/business-management-console.md`.
- Problem Codes and error envelope: `docs/conventions-errors.md`. List envelopes: `docs/conventions-pagination.md`. **Instant** handling: `docs/conventions-time.md`.
- Connection settings and variable ownership: `docs/env.md`.
- Terminology: `docs/glossary.md`.

## 2. Business Entity Definition

### 2.1 Identity

A Business Entity is identified by an immutable `code`. The `code` names the business thing and spans every **Entity Version** of it. It is unique across the platform.

`code` is constrained because it is also the stem of a physical table name (§4.3): lowercase ASCII letters, digits, and underscores; it starts with a letter; and its length leaves room for the version suffix within the entity database engine's identifier limit. A `code` outside those constraints is rejected with `ENTITY_CODE_INVALID`. A `code` already registered is rejected with `ENTITY_CODE_CONFLICT`.

A Business Entity is not scoped to a **Source**. It may describe a business thing whose rows will later be assembled from several Sources.

### 2.2 Required Meaning

A Business Entity exists only because a person authored it, so the product requires meaning at declaration time rather than accepting a bare shape. These fields are required:

| Field | Rule |
| --- | --- |
| `code` | §2.1 |
| `name` | Short display name |
| `description` | Natural-language statement of what the business thing is |
| `category` | The same closed set as `object_category` on **Object Semantics**: `transaction_fact`, `master_data`, `dimension`, `reference`, `event` |
| `grain_description` | Prefer “one row means …” |
| `business_key` | §2.4 |
| `attributes` | At least one; §2.3 |

An optional **Business Domain** reference (`business_domain_code`) attaches the Entity to a business area, resolved and reported as the nested `{ id, code, name }` shape used elsewhere; an unknown code is rejected with `BUSINESS_DOMAIN_UNKNOWN`. It is optional because a Domain must exist before it can be attached, and Entity authoring does not depend on Domain setup.

The definition carries no source binding, extract SQL, transform, dependency graph, or lineage. Those are **Data Channel** concerns and are out of scope for this document.

### 2.3 Attributes

An attribute declares a `name`, a type from the **Normalized Type** closed set (`string`, `integer`, `number`, `boolean`, `date`, `timestamp`, `time`, `interval`, `binary`, `json`, `array`, `unknown`), whether it is nullable, and an optional `description`.

Attribute names are unique within an **Entity Version** and follow the same character constraints as `code`, because each becomes a physical column.

The Normalized Type set is the platform's portable type vocabulary: it is what a catalog column carries once a **Type Mapping** has classified its engine-native type. Using it on Entity attributes means one type language spans the catalog a modeller reads and the Entity they declare, whatever engines the rows will later come from.

### 2.4 Business Key

`business_key` is a list of the Entity's own attribute names, in the same shape `business_primary_key` takes on a Catalog Object. A name that is not an attribute of this version is rejected with `ENTITY_ATTRIBUTE_UNKNOWN`.

The product admits exactly one element; a longer list is rejected with `ENTITY_KEY_CARDINALITY`. Admitting a composite key later relaxes this rule without changing the field's shape.

A business key attribute is required, never nullable.

## 3. Entity Version And Shape Change

### 3.1 A Version Is A Compatible Shape Family

An **Entity Version** is one compatible shape family under a Business Entity `code`, and it owns exactly one **Entity Table**. No Entity Table is shared between versions. A downstream reader that pins a version can rely on its shape only growing in ways that keep existing rows and existing queries valid.

### 3.2 Additive Growth Within A Version

Within one version the permitted changes are:

1. Add a nullable attribute.
2. Promote an attribute from `unknown` to any type.
3. Promote an attribute from `integer` to `number`.
4. Relax a required attribute to nullable.

That is the whole set. `unknown` carries no type commitment; `integer` to `number` is the only widening the Normalized Type vocabulary can express, because that vocabulary has no width, precision, or scale; and relaxing nullability leaves every existing row valid.

An added attribute cannot join the business key on the same version, because additions are nullable and a business key change is breaking.

### 3.3 Breaking Change Opens The Next Version

These changes are breaking:

1. Rename an attribute.
2. Drop an attribute.
3. Change an attribute type outside §3.2.
4. Tighten a nullable attribute to required.
5. Change `grain_description`.
6. Change `business_key`.

A breaking change is never applied to an existing version. It opens the next version, which materializes its own empty Entity Table (§4). The prior version, its table, and its rows are untouched. An attempt to apply one in place is rejected with `ENTITY_BREAKING_CHANGE`.

Change classification uses the platform vocabulary `breaking` / `non_breaking` / `unchanged`, the same three values a **Structure Diff** carries. Entity does not introduce a second language for the same judgment.

A non-breaking change may be applied to the current version or may open the next one. That choice belongs to the author.

Whether a change is breaking is a product rule, not a per-Entity setting. There is no per-Entity policy switch, because refraq does not own the rows and cannot verify that a lossy conversion is safe.

### 3.4 Entity Definition Ledger

Every applied definition change appends to the **Entity Definition Ledger**: field name, old value, new value, actor, **Instant**, and the §3.3 class. In-place non-breaking changes and version-opening changes both append.

The ledger is append-only. It is not a **Management Audit Event**, not a **Structure Diff**, not a record of row content or load runs, and not a restore path.

## 4. Entity Table Materialization

### 4.1 Where The Table Lives

Entity Tables live in an entity database that refraq owns, declared by its own connection setting separate from the metadata database (`docs/env.md` owns the variable). Keeping the two apart keeps the platform connection budget in `docs/business-metadata.md` honest about metadata volume, and leaves the entity database free to grow with business data.

An Entity Table is never created inside a **Source**. A Source is a read-only registered data origin; the only caller SQL refraq sends to one is a single guarded read (**Controlled Query**, **Catalog Sample**).

Entity Tables are not collected as **Catalog Object**s. The Entity definition is already the authoritative statement of their shape.

### 4.2 Materialization Is A Job

Creating a version's table is a **Job**. The definition lands first and is immediately readable; the table follows.

No transaction spans the metadata database and the entity database, so the two acts cannot commit together. The product makes that visible rather than hiding it behind compensation: an **Entity Version** carries a materialization state reporting whether its table exists, and a failed materialization leaves the definition in place with that state and the Job's failure detail.

A version whose table does not yet exist accepts no **Data Channel** writes.

### 4.3 Physical Naming And Collision

A version's table name is derived as `{code}_v{version}`. The name is readable because people, **Data Channel** authors, and later consumer-facing tools address it directly. Derivation is safe because `code` is immutable, so the physical name never has to change.

Two Business Entities cannot collide, because `code` is unique. A derived name may still collide with a table already present in the entity database. Materialization then fails with `ENTITY_TABLE_NAME_CONFLICT`. refraq does not rename around a collision: an auto-suffixed name would break the link between `code` and the physical table, which is the only reason to derive the name at all.

### 4.4 Attribute Type To Physical Type

Each **Normalized Type** maps to one physical type in the entity database engine. That mapping is product-owned and fixed; it is not a maintainable registry and not a **System Parameter**. It differs from **Type Mapping**, which classifies many engines' native types *into* Normalized Type and needs operator gap maintenance because new engines bring new native types. Here there is a single target engine and no business decision for an operator to make.

## 5. Retirement And Disposal

Retiring an **Entity Version** is a definition act. A retired version accepts no **Data Channel** writes. Its shape, its ledger, and its table are otherwise unchanged.

Deleting a definition never drops a table. Deleting an Entity Version, or a Business Entity, removes definition rows only. A table left behind is an orphan for an operator to dispose of; the product does not destroy rows it did not produce and cannot reconstruct.

Dropping an **Entity Table** is a separate destructive act behind its own **Permission** (§6). It is refused while the table holds rows, rejected with `ENTITY_TABLE_NOT_EMPTY`. Because refraq owns the entity database, emptiness is a fact it reads rather than a policy it assumes. Emptying a table is the operator's act in the entity database, not a product path.

Deleting a Business Entity requires every version retired first. It is refused while a **Data Channel** references any version, rejected with `ENTITY_IN_USE`.

## 6. Authorization

| Permission | Grants |
| --- | --- |
| `entity:read` | Read Business Entity definitions, versions, attributes, and the **Entity Definition Ledger** |
| `entity:write` | Create and change definitions, open versions, retire versions, delete definitions, and enqueue materialization |
| `entity:drop_table` | Drop an **Entity Table** (§5) |

All three declare `platform` as the lowest authorization scope at which they may be granted. A Business Entity is not owned by a **Source**, so `source` scope cannot express access to one.

`entity:drop_table` is in the Permission catalog and is not seeded onto the `operator` **Role**. It is not implied by `entity:write`.

## 7. Management Console

Business Entity management mounts as Console module `entities` under nav group `entity`. It is not mounted under the `metadata` nav group, which covers Sources, catalog browsing, Business Domains, and Type Mappings.

The Console presents definitions, versions with their materialization state, attributes, and the **Entity Definition Ledger**. It presents the §3.3 classification before a change is applied, so an author sees that a change opens a version rather than discovering it afterwards. Dropping a table is presented as a destructive action, available only to a caller holding `entity:drop_table`.

Where a **Data Channel** module mounts is out of scope for this document.

## 8. MCP Exposure

The **MCP endpoint** exposes Business Entity reads: list entities, read one entity with its versions and attributes. Reads require `entity:read` on the calling **User PAT**.

Authoring and changing definitions, retiring versions, and dropping tables are not MCP tools. Declaring a business thing is a modelling judgment with a human author of record, and the destructive path is deliberately narrow.

## 9. Management Audit

Persist a **Management Audit Event** for: Business Entity create, definition change (with the §3.3 class), version open, version retire, definition delete, materialization enqueue, and table drop. Each event records actor, **Instant**, resource, action, and result. The **Entity Definition Ledger** is a separate record with a different purpose (§3.4) and does not replace these events.

## 10. Non-Goals

1. Moving rows into an **Entity Table** — mapping, transform, lineage, cadence, and load runs belong to a **Data Channel**.
2. Any read path for Entity Table contents, including row reads, row counts, and freshness observation.
3. Serving delivery, consumer-facing contracts, and consumer-owned write targets.
4. Composite business keys.
5. Type narrowing, attribute rename in place, and any per-Entity schema-evolution policy switch.
6. Dropping a non-empty **Entity Table**, cascading disposal, and reclaiming entity database storage.
7. Deprecation dates and consumer-reference graphs.
8. Collecting Entity Tables as **Catalog Object**s, or registering the entity database as a **Source**.
9. Creating tables inside a Source, or any write SQL against a Source.
10. Entity-level ACL, per-attribute permissions, and masking.
11. A hierarchy, inheritance, or relationship graph between Business Entities.

## 11. References

- `docs/business-metadata.md`
- `docs/business-jobs.md`
- `docs/business-scheduled-tasks.md`
- `docs/business-login-auth.md`
- `docs/business-management-console.md`
- `docs/conventions-errors.md`
- `docs/conventions-pagination.md`
- `docs/conventions-time.md`
- `docs/env.md`
- `docs/glossary.md`
