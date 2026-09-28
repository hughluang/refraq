# refraq API Contracts: Entity

## 1. Purpose

This document defines the HTTP contract for the **Business Entity** surface: request and response shapes, list envelopes, Problem Codes, publish, deprecate, and the enqueue of table-create and table-drop **Job**s.

It does not define how rows reach an **Entity Table**, and it does not define a read path for Entity Table contents. Mapping, transform, lineage, and write admission belong to a **Data Channel**.

Related boundaries:

- Business rules: `docs/business-entity.md`
- Problem Details and Problem Codes: `docs/conventions-errors.md`
- **Offset Page** lists: `docs/conventions-pagination.md`
- **Instant** wire form: `docs/conventions-time.md`
- Platform Job observe (get / logs / cancel): `docs/api-contracts-jobs.md`
- Job kinds `entity_reconcile` and `entity_table_drop`: `docs/business-jobs.md`
- Permissions: `docs/business-login-auth.md` §8
- Entity database connection and pool: `docs/env.md`
- Terminology: `docs/glossary.md`

## 2. Cross-Cutting Rules

### 2.1 Transport

Success responses use `application/json`. Every HTTP failure uses RFC 9457 Problem Details (`application/problem+json`). `type` is derived as `urn:refraq:problem:{CODE}`. First-party clients branch on `code` and never on `type` or `detail`.

Authentication is a Session cookie or a **User PAT** Bearer token. Unauthenticated requests return `401 AUTH_UNAUTHENTICATED`. Authenticated callers lacking the required **Permission** return `403`.

Every response echoes `X-Request-ID`. Success bodies do not include `request_id`.

Instants on the wire are UTC with a `Z` suffix.

### 2.2 Offset Page

Every Entity collection list uses the **Offset Page** envelope `{ "items", "total", "limit", "offset" }`. Newest-first lists order by `created_at DESC`, `id DESC`. Version lists order by `version DESC`, `id DESC`. Name-ordered lists include an `id` tiebreaker.

Each list endpoint declares its default and max `limit`. HTTP rejects out-of-range `limit` or `offset` with `422 REQUEST_INVALID`. An `offset` past the end of the filtered set is `200` with empty `items` and the same `total`.

### 2.3 Identifiers

| Resource | Example | Rule |
| --- | --- | --- |
| Business Entity | `ent_01HZX` | Opaque server-issued id |
| Entity Version | `encv_01HZX` | Opaque server-issued id |
| Job | `job_01HZX` | Platform Job id (`docs/api-contracts-jobs.md`) |

`table_name` is the immutable business identity. It is not an HTTP path substitute for `id`.

## 3. Resource Shapes

### 3.1 Attribute

```json
{
  "name": "sku",
  "type": "string",
  "required": true,
  "unique": true,
  "indexed": false,
  "description": "SKU code",
  "config": { "max_length": 32 }
}
```

```json
{
  "name": "status",
  "type": "enumeration",
  "required": true,
  "unique": false,
  "indexed": false,
  "description": null,
  "config": {
    "entries": [
      { "code": "ACTIVE", "label": "Active" }
    ]
  }
}
```

```json
{
  "name": "supplier",
  "type": "reference",
  "required": false,
  "unique": false,
  "indexed": false,
  "description": "Supplying party",
  "config": { "target_entity_id": "ent_01HZX" },
  "target": {
    "entity_id": "ent_01HZX",
    "name": "Supplier",
    "table_name": "supplier"
  }
}
```

`type` is required and is one **Attribute Type**: `string`, `text`, `integer`, `decimal`, `number`, `boolean`, `date`, `timestamp`, `time`, `json`, `enumeration`, or `reference`. Any other type, including `many2one`, `one2many`, and `array`, is `ENTITY_ATTRIBUTE_INVALID`. `inverse_attribute` is not a field. `kind` is not a field.

`config` is a required object. `string` requires `max_length`, an integer from 1 through 65535, and no other key. `text`, `integer`, `number`, `boolean`, `date`, `timestamp`, `time`, and `json` require `{}`. `json` is a JSON document, including a JSON array, with no schema, path, or format key. The published column is `JSONB`. `decimal` requires `precision` (1–1000) and `scale` (0–`precision`) and no other key. `enumeration` requires `entries`, a non-empty array of `{ "code", "label"? }`, and no other key. A `code` is a non-empty string of at most 64 characters and is case-sensitive. `label`, when present, is at most 200 characters. Codes are unique within the attribute. `reference` requires `target_entity_id` and no other key. On write, `target_entity_id` is `self` or the id of an existing Business Entity that is not deprecated. `self` means the entity of this request. Create allocates that id and replaces `self` before the entity is stored. Save and classify replace `self` with the entity id in the path. The stored value is always that entity's id. A read never returns `self`. The target may be unpublished, and it may be this entity. A version read that includes attributes adds `target` on a `reference` attribute only: `{ "entity_id", "name", "table_name" }` when the id names an entity, otherwise `null`. Other attribute types omit `target`. `target` is not stored and is rejected on write as an extra field. The example above is a read. Writers omit `target` and may send `"target_entity_id": "self"`. The published column is `BIGINT` and stores the target live table's `row_id`. The contract does not create a foreign key. A stored `row_id` may not resolve.

A config key that belongs to another type, an unknown config key, or a top-level `kind`, `normalized_type`, `precision`, `scale`, `target_table_name`, or `enumeration` is `ENTITY_ATTRIBUTE_INVALID`.

`required`, `unique`, and `indexed` default to `false` when omitted. `unique` is a single-column UNIQUE constraint. `indexed` is a non-unique btree; when `unique` is true, publish does not also create a non-unique index for that column. On a reference, `unique` means at most one row points at a given target `row_id`. A `number` attribute may be unique or indexed; it is a poor business key because the value is approximate and may be NaN.

`name` uses the same character set as `table_name` (lowercase ASCII letters, digits, and underscores; starts with a letter) and is at most 63 characters so it can be a physical column name. A name outside those constraints, the reserved name `row_id`, or a duplicate within the version is `ENTITY_ATTRIBUTE_INVALID` (Problem `detail` names the concrete rule). Names are unique within one **Entity Version**. The Entity Table always carries a platform `row_id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY` that is not an attribute. An **Inbound Reference** is not an attribute and is not accepted inside `attributes`.

### 3.2 Entity Version

```json
{
  "id": "encv_01HZX",
  "entity_id": "ent_01HZX",
  "version": 1,
  "publish_status": "unpublished",
  "attributes": [
    {
      "name": "sku",
      "type": "string",
      "required": true,
      "unique": true,
      "indexed": false,
      "description": "SKU code",
      "config": { "max_length": 32 }
    }
  ],
  "table_name": null,
  "alignment": {
    "table_present": false,
    "definition_ahead": true,
    "latest_job_id": null,
    "latest_job_status": null
  },
  "created_at": "2026-09-10T04:00:00Z",
  "updated_at": "2026-09-10T04:00:00Z"
}
```

`version` is a positive integer. The first version is `1`. Each newly opened version is the previous current version plus one.

`publish_status` is stored: `unpublished` | `publishing` | `published`. Create and open-version start `unpublished`. Publish is the only transition to `publishing` and then `published`. A failed publish Job returns the version to `unpublished`.

`table_name` on a version is the current physical table of that version, derived and never stored: `null` when `table_present` is false; the Entity stem when this version is the latest published version that still has a table; `{stem}__rfq_v{version}` for an earlier published version that still has a table. Publishing a successor RENAMEs the previous live table to the archive name.

`alignment` is derived from the stored attribute-set snapshot and the latest create Job:

| Field | Meaning |
| --- | --- |
| `table_present` | The snapshot is non-empty (the table exists) |
| `definition_ahead` | The snapshot is empty, or the snapshot differs from this version's attributes |
| `latest_job_id` | Latest `entity_reconcile` Job for this version, or `null` |
| `latest_job_status` | That Job's `status`, or `null` |

`publish_status` is the product lifecycle. `table_present` is a derived fact used for drop. A version list item may omit `attributes` and send `attribute_count` instead. Version detail always includes `attributes`.

### 3.3 Business Entity

```json
{
  "id": "ent_01HZX",
  "table_name": "material",
  "name": "Material",
  "description": "A stock-keeping material at SKU grain.",
  "deprecated_at": null,
  "ever_published": false,
  "current_version": {
    "id": "encv_01HZX",
    "version": 1,
    "publish_status": "unpublished",
    "table_name": null,
    "alignment": {
      "table_present": false,
      "definition_ahead": true,
      "latest_job_id": null,
      "latest_job_status": null
    }
  },
  "created_at": "2026-09-10T04:00:00Z",
  "updated_at": "2026-09-10T04:00:00Z"
}
```

`deprecated_at` is an **Instant** after Deprecate, otherwise `null`. `ever_published` is `true` when any version is or has been `published`, or when `deprecated_at` is set.

List items use this shape. Entity detail (`GET /entities/{id}`) adds `inbound_references` and no other top-level fields. Callers load versions and attributes from the nested endpoints. List items omit `inbound_references`.

`inbound_references` is a read-only array, ordered by `table_name` then `attribute_name`. Each item is `{ "entity_id", "table_name", "attribute_name" }` for a Business Entity whose **current** version has an **Entity Reference** with `target_entity_id` equal to this entity's id. This entity's own current version counts. An unpublished current version counts. A historical version does not. The field is not accepted on create or patch; a present `inbound_references` is `422 REQUEST_INVALID`.

### 3.4 Classification Result

```json
{
  "class": "non_breaking",
  "changes": [
    {
      "field": "attributes.sku.unique",
      "old_value": false,
      "new_value": true,
      "class": "non_breaking"
    }
  ]
}
```

`class` is the roll-up of `changes`: `breaking` if any change is breaking, else `non_breaking` if any change is non-breaking, else `unchanged`. An empty `changes` array is `unchanged`.

The classifier is a pure function of two attribute sets. It is a read tool. It does not gate save or publish. **Inbound Reference**s are not an input.

Compared as today: adding an attribute is `non_breaking` when the added attribute is not required and `breaking` when it is; removing an attribute is `breaking`; changing `required` from false to true is `breaking` and from true to false is `non_breaking`; `unique` and `indexed` changes are `non_breaking`; a description change is `unchanged`. An **Attribute Type** change is `breaking`, including `string` to `text`, `integer` to `number`, and `integer` to `decimal`. There is no `unknown` promotion.

Widening `config.max_length` on `string` is `non_breaking`. Narrowing it is `breaking`. Those classes are not an `ALTER` of a published column. A change of `precision` or `scale` is `breaking`. Adding enumeration codes while every previous code remains is `non_breaking`. Removing or rewriting a code is `breaking`. A change that touches only `label` values is `unchanged`. Those enumeration classes are not an `ALTER` of a published CHECK. A change of `target_entity_id` is `breaking`.

## 4. Business Entity Endpoints

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `GET` | `/entities` | `entity:read` | List Business Entities (**Offset Page**) |
| `POST` | `/entities` | `entity:write` | Create a Business Entity and unpublished version `1` |
| `GET` | `/entities/{id}` | `entity:read` | Get one Business Entity |
| `PATCH` | `/entities/{id}` | `entity:write` | Patch identity and, optionally, current unpublished attributes |
| `DELETE` | `/entities/{id}` | `entity:write` | Delete a never-published Business Entity |
| `POST` | `/entities/{id}/classify` | `entity:read` | Classify a proposed shape against the current version |
| `POST` | `/entities/{id}/deprecate` | `entity:write` | Deprecate the Entity |

Creating a Business Entity has no cross-database side effect. Version `1` is `unpublished` and readable immediately. Its **Entity Table** does not exist until publish succeeds.

### 4.1 `GET /entities`

**Offset Page** (`created_at DESC`, `id DESC`). Query params: `q` (literal substring of `table_name` or `name`), `status` (repeatable), `limit` (default **50**, max **200**), `offset` (default **0**).

`status` is `not_serving`, `serving`, or `deprecated`. Omit it to apply no entity-status predicate, so deprecated entities stay in the page. Repeat it to keep entities whose derived entity status is any listed value. Derived status is **deprecated** when `deprecated_at` is set; otherwise **serving** when any version is `published`; otherwise **not_serving**. All three values match the omitted predicate. Duplicate values are one value. Any other value is `422 REQUEST_INVALID`. When `q` is also present, an entity must match both.

Response: `{ "items": […], "total": N, "limit": L, "offset": O }`. Items use the Business Entity shape.

### 4.2 `POST /entities`

```json
{
  "table_name": "material",
  "name": "Material",
  "description": "A stock-keeping material.",
  "attributes": [
    {
      "name": "sku",
      "type": "string",
      "required": true,
      "unique": true,
      "indexed": false,
      "description": "SKU code",
      "config": { "max_length": 32 }
    }
  ]
}
```

Required: `table_name`, `name`, `description`, `attributes`. Any other field is `422 REQUEST_INVALID`.

`table_name` is `[a-z][a-z0-9_]*`, at most **48** characters, and must not match `.*__rfq_v[0-9]+$`, so `{table_name}__rfq_v{version}` stays inside the entity-database identifier limit (63 bytes). A `table_name` outside those constraints is `ENTITY_TABLE_NAME_INVALID`. A `table_name` already registered is `ENTITY_TABLE_NAME_DUP`. `table_name` cannot change after create.

`attributes` may be empty. An attribute named `row_id` is `ENTITY_ATTRIBUTE_INVALID`.

Success `201`: `{ "entity": { … } }`.

### 4.3 `GET /entities/{id}`

Success `200`: `{ "entity": { … } }`. Missing id is `404 ENTITY_NOT_FOUND`.

### 4.4 `PATCH /entities/{id}`

Accepted fields: `name`, `description`, `attributes`. Omitted fields stay unchanged. `table_name` and `code` are rejected if present (`422 REQUEST_INVALID`).

`attributes`, when present, is the full replacement set for the current unpublished version. Storage stays on that version; this is not an Entity-level shape field. Version-scoped clients may still `PATCH` §5.4.

Refused when the Entity is deprecated (`ENTITY_DEPRECATED`), when any version is `publishing` (`ENTITY_PUBLISHING`), or when the current version is not `unpublished` (`ENTITY_NOT_UNPUBLISHED`).

An applied change writes one definition-save **Management Audit Event**. Identity-only changes record class `unchanged`. A shape change records the classifier class. No change is a no-op and writes no event.

Success `200`: `{ "entity": { … } }`.

### 4.5 `DELETE /entities/{id}`

Deleting a definition removes definition rows only. It never drops an Entity Table.

Delete is refused when the Entity has ever been published (`409 ENTITY_ALREADY_PUBLISHED`). It is also refused when a current version, including this entity's own, has an **Entity Reference** whose target is this entity (`409 ENTITY_REFERENCED`). A historical version does not count. A never-published Entity has no table.

Success `204` with an empty body.

### 4.6 `POST /entities/{id}/classify`

Classifies a proposed shape against the current version without writing.

```json
{
  "attributes": []
}
```

Omitted shape fields are taken from the current version, so a partial body classifies only the supplied delta. `attributes`, when present, is the full proposed set.

Success `200`: the Classification Result shape. This call does not persist, does not enqueue a Job, and does not write an audit event. Missing entity is `404 ENTITY_NOT_FOUND`.

### 4.7 `POST /entities/{id}/deprecate`

Marks the Entity deprecated. Body is empty.

Refused when the Entity has never been published (`422 ENTITY_NEVER_PUBLISHED`), is already deprecated (`422 ENTITY_ALREADY_DEPRECATED`), any version is `publishing` (`422 ENTITY_PUBLISHING`), or a current version, including this entity's own, has an **Entity Reference** whose target is this entity (`409 ENTITY_REFERENCED`). A historical version does not count. Publishing a new version of a referenced entity is not refused by that reference.

Success `200`: `{ "entity": { … } }` with `deprecated_at` set.

## 5. Entity Version And Attribute Endpoints

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `GET` | `/entities/{id}/versions` | `entity:read` | List versions (**Offset Page**) |
| `POST` | `/entities/{id}/versions` | `entity:write` | Open the next unpublished version |
| `GET` | `/entities/{id}/versions/{version_id}` | `entity:read` | Get one version with attributes |
| `PATCH` | `/entities/{id}/versions/{version_id}` | `entity:write` | Save an unpublished current version's shape |
| `POST` | `/entities/{id}/versions/{version_id}/publish` | `entity:write` | Publish: enqueue table create (`entity_reconcile`) |

### 5.1 `GET /entities/{id}/versions`

**Offset Page** (`version DESC`, `id DESC`). Query params: `limit` (default **50**, max **200**), `offset` (default **0**).

Response items are version summaries (`attributes` omitted; `attribute_count` present). Missing entity is `404 ENTITY_NOT_FOUND`.

### 5.2 `POST /entities/{id}/versions`

Opens the next version under this Entity. The current version must be `published` and the Entity must not be deprecated. Otherwise `ENTITY_NOT_PUBLISHED` or `ENTITY_DEPRECATED`. A `publishing` Entity is `ENTITY_PUBLISHING`.

The new version starts as a copy of the current version's saved shape; the body overlays that copy.

```json
{
  "attributes": [
    {
      "name": "lot_id",
      "type": "string",
      "required": true,
      "unique": true,
      "indexed": false,
      "description": "Lot identifier",
      "config": { "max_length": 32 }
    }
  ]
}
```

The field is optional. An omitted field stays as copied. A body that does not change the shape is still a new unpublished version.

Opening a version has no cross-database side effect. The new version is `unpublished` and readable immediately. Its table does not exist until publish succeeds. The prior version becomes superseded. The prior version's table and rows are untouched.

Success `201`: `{ "version": { … } }`.

### 5.3 `GET /entities/{id}/versions/{version_id}`

Success `200`: `{ "version": { … } }` with full `attributes`. Missing entity or version is `404 ENTITY_NOT_FOUND` or `404 ENTITY_VERSION_NOT_FOUND`. A version id that does not belong to the entity is `404 ENTITY_VERSION_NOT_FOUND`.

### 5.4 `PATCH /entities/{id}/versions/{version_id}`

Saves a shape on the current `unpublished` version. A superseded target is `422 ENTITY_VERSION_SUPERSEDED`. A published or publishing target is `422 ENTITY_NOT_UNPUBLISHED` or `422 ENTITY_PUBLISHING`. A deprecated Entity is `422 ENTITY_DEPRECATED`.

Accepted fields: `attributes`. Omitted fields stay unchanged. `attributes`, when present, is the full replacement set. Any valid shape is accepted, including changes the classifier would call `breaking`.

Success `200`: `{ "version": { … } }`.

### 5.5 `POST /entities/{id}/versions/{version_id}/publish`

Publishes the current `unpublished` version: set `publishing` and enqueue `entity_reconcile` to CREATE the live stem table, RENAMEing the previous live table to `{stem}__rfq_v{previous}` when one exists.

Body is empty.

- Empty `attributes` is `422 ENTITY_PUBLISH_EMPTY`.
- Non-current target is `422 ENTITY_VERSION_SUPERSEDED`.
- Non-unpublished is `422 ENTITY_NOT_UNPUBLISHED`.
- Deprecated Entity is `422 ENTITY_DEPRECATED`.

Enqueue is idempotent:

- An in-flight create or drop Job for this version is returned as `200` with that Job. A second Job is not minted.
- Otherwise the response is `201` `{ "job": { … } }`.

A successful run writes `published`, the attribute-set snapshot, and the Job reference. A failed run returns the version to `unpublished`, rolls back or compensates the entity-database DDL (drop the new live table; rename the archived previous table back), leaves the definition in place, and records failure on the Job.

Success envelope on the Job (`result` only when `succeeded`):

```json
{
  "schema": "entity_reconcile.v1",
  "entity_version_id": "encv_01HZX",
  "table_name": "material",
  "action": "created",
  "columns_added": 1,
  "nullability_relaxed": 0,
  "types_widened": 0,
  "unique_added": 1,
  "unique_dropped": 0,
  "indexes_added": 0,
  "indexes_dropped": 0
}
```

`action` is `created` on the product path. A publish-enqueue audit event is written only when a Job is minted.

## 6. Table Drop

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `POST` | `/entities/{id}/versions/{version_id}/drop-table` | `entity:drop_table` | Enqueue table drop (`entity_table_drop`) |

The body is an empty object. The response is a platform Job in `{ "job": { … } }` using the Job shape in `docs/api-contracts-jobs.md`. Observe, logs, and cancel stay on `/jobs/{id}`. Domain enqueue does not require `jobs:run`.

`input` is `{ "entity_version_id": "encv_01HZX" }`. `trigger_kind` is `user`; `trigger_ref` and `created_by` are the acting User.

Publish create and drop share one execution lock keyed per Entity (`entity_table:{entity_id}`), not per kind and not per version. A runner that cannot take the lock ends that Job `failed` with `JOB_ALREADY_ACTIVE`. The lock is the race backstop; it is not an HTTP 409.

Failures leave Job `result` null and carry `error_code` / `error_message`. Success writes the kind envelope and only then.

The API and MCP processes hold no connection to the entity database. Only the worker opens that pool.

### 6.1 `POST /entities/{id}/versions/{version_id}/drop-table`

Permitted on an archived version's table (physical name is not the Entity stem), or on the live stem table after the Entity is deprecated. The live table while the Entity is not deprecated is `422 ENTITY_VERSION_NOT_SUPERSEDED`.

Enqueue is idempotent with the same in-flight rule as publish (`200` returns the in-flight Job). A version whose snapshot is already empty is `200` `{ "job": null, "version": { … } }`.

Emptiness is checked in the same transaction as the drop. A non-empty table fails the Job with `ENTITY_TABLE_NOT_EMPTY`. The HTTP enqueue does not treat a pre-check as a guarantee.

Success envelope:

```json
{
  "schema": "entity_table_drop.v1",
  "entity_version_id": "encv_01HZX",
  "table_name": "material__rfq_v1"
}
```

A table-drop-enqueue audit event is written only when a Job is minted. Visibility of this action in the Console is limited to callers holding `entity:drop_table`.

## 7. Problem Codes

Kernel codes (`REQUEST_INVALID`, `AUTH_UNAUTHENTICATED`, and the other codes in `docs/conventions-errors.md`) apply as usual. Entity-owned codes:

| Problem Code | HTTP status | When |
| --- | --- | --- |
| `ENTITY_NOT_FOUND` | 404 | Unknown Business Entity id |
| `ENTITY_VERSION_NOT_FOUND` | 404 | Unknown version id, or the version is not under the given entity |
| `ENTITY_TABLE_NAME_INVALID` | 422 | `table_name` charset, length, or reserved archive suffix is outside the rule |
| `ENTITY_TABLE_NAME_DUP` | 409 | `table_name` already registered |
| `ENTITY_ATTRIBUTE_INVALID` | 422 | Attribute `name` charset, length, reserved (`row_id`), or duplicate within the version; `type` missing or outside the **Attribute Type** closed set; `config` missing, carrying another type's key, or an unknown key; `string` `max_length` outside 1–65535; `decimal` precision or scale outside the rule; enumeration shape or code lexical rule; `target_entity_id` missing, unknown, or naming a deprecated entity; or a retired top-level field (`kind`, `normalized_type`, `precision`, `scale`, `target_table_name`, `enumeration`). `detail` names the concrete rule (and the value when safe to show) |
| `ENTITY_NOT_UNPUBLISHED` | 422 | Save or publish targeted a version that is not `unpublished` |
| `ENTITY_NOT_PUBLISHED` | 422 | Open version while the current version is not `published` |
| `ENTITY_PUBLISHING` | 422 | A write while any version is `publishing` |
| `ENTITY_PUBLISH_EMPTY` | 422 | Publish with an empty attribute list |
| `ENTITY_DEPRECATED` | 422 | A write on a deprecated Entity |
| `ENTITY_NEVER_PUBLISHED` | 422 | Deprecate while the Entity has never been published |
| `ENTITY_ALREADY_DEPRECATED` | 422 | Deprecate when already deprecated |
| `ENTITY_ALREADY_PUBLISHED` | 409 | Delete after the Entity has been published |
| `ENTITY_REFERENCED` | 409 | Deprecate, or delete of a never-published definition, while a current version (including this entity's own) has an **Entity Reference** aimed at this entity |
| `ENTITY_VERSION_SUPERSEDED` | 422 | Save or publish targeted a superseded version |
| `ENTITY_VERSION_NOT_SUPERSEDED` | 422 | Table drop targeted the live stem table on a non-deprecated Entity |

Job-terminal codes (successful GET of a failed Job; not Problem Details on the enqueue when the Job was minted):

| Problem Code | When |
| --- | --- |
| `ENTITY_TABLE_NAME_CONFLICT` | Publish found the live stem or archive name already present in `REFRAQ_ENTITY_DB_SCHEMA` |
| `ENTITY_TABLE_NOT_EMPTY` | Drop found rows in the same transaction |
| `JOB_ALREADY_ACTIVE` | Runner could not take `entity_table:{entity_id}` |
| `JOB_WORKER_LOST` | Occupancy stale (`docs/api-contracts-jobs.md`) |
| `JOB_RUNNING_TIMEOUT` | Running-time snapshot exceeded |
| `JOB_EXECUTION_FAILED` | Runner aborted unexpectedly |

## 8. Management Audit

Persist a **Management Audit Event** for: Business Entity create, definition save, version open, publish enqueue, deprecate, definition delete, and table-drop enqueue. Each event records actor, Instant, resource, action, and result.

## 9. Non-Goals

1. Any **Data Channel** contract: mapping, transform, lineage, row movement, cadence, or write admission.
2. Any read path for Entity Table contents, including row counts and freshness.
3. Serving delivery, consumer targets, and consumer-facing contracts.
4. Composite unique constraints, composite indexes, ALTER of a published table, and per-Entity evolution policy switches.
5. Registering the entity database as a **Source**, or collecting Entity Tables as **Catalog Object**s.
6. Entity-level ACL, attribute-level permissions, and masking.
7. Hierarchy or inheritance between Business Entities. An **Inbound Reference** is derived and is not a saved attribute. A many-to-many is not a link table, a relationship-entity subtype, or an extra attribute type. Semantic Type, a unit on `decimal`, a cardinality on `reference`, and an enumeration constraint on `string` or `integer` are not part of this contract.
8. An authorization scope mechanism.
9. A global `POST /jobs` create path.
10. MCP tools for Business Entity.

## 10. References

- `docs/business-entity.md`
- `docs/business-jobs.md`
- `docs/business-login-auth.md`
- `docs/api-contracts-jobs.md`
- `docs/api-contracts-metadata-mcp.md`
- `docs/conventions-errors.md`
- `docs/conventions-pagination.md`
- `docs/conventions-time.md`
- `docs/env.md`
- `docs/glossary.md`
