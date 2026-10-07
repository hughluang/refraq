# refraq API Contracts: Entity Data

## 1. Purpose

This document defines the **Entity Data API**: the HTTP data plane for a published **Business Entity**'s metadata head. Callers discover an outbound schema and read or write head-table rows under Session or **User PAT** authentication, addressed by immutable `table_name`.

It does not define Business Entity authoring, publish, deprecate, or table-drop Jobs (`docs/api-contracts-entity.md`). It is not a **Data Channel**, not ISC `/v1/serving`, and not an MCP tool surface. Every verb is subject to **Entity Access Control**: what a caller sees and may write is compiled from its **Access Grant**s (`docs/business-entity-access.md`); the access-specific shapes, codes, and narrowing are `docs/api-contracts-entity-access.md` §5.

Related boundaries:

- Business Entity definition and lifecycle: `docs/business-entity.md`, `docs/api-contracts-entity.md`
- Problem Details and Problem Codes: `docs/conventions-errors.md`
- **Offset Page** and keyset admission: `docs/conventions-pagination.md`
- **Instant** wire form: `docs/conventions-time.md`
- Permissions: `docs/business-login-auth.md` §8
- Entity Access Control: `docs/business-entity-access.md`, `docs/api-contracts-entity-access.md`
- User PAT: `docs/business-user-tokens.md`
- Entity database connection and pool: `docs/env.md`
- Terminology: `docs/glossary.md`

## 2. Positioning And Scale

### 2.1 What This Surface Is

- An online synchronous data plane around a self-owned Business Entity: schema discovery plus head-table row create, read, update, delete, query, conditional write, and upsert.
- Callers are external integrators holding an existing User Session cookie or User PAT Bearer. No new **Client** principal. `console:access` is not required.
- Transport is synchronous HTTP. Work does not run as a **Job** or **Scheduled Task**.

### 2.2 What This Surface Is Not

1. Not the Console definition / authoring API (that surface addresses by opaque Entity `id`).
2. Not a **Data Channel**. Channel responsibility is not narrowed. Dual-write of the same head table is allowed; the platform does not tag row provenance; unique constraints arbitrate.
3. Not an ISC serving drop-in: no opaque `cursor` / `next_cursor`, no `rows:by-keys`, no message queue. Walks use explicit `after_row_id`. Errors use 422 Problem Details, not serving's 400.
4. Not an MCP tool surface. The Metadata MCP does not expose definition, schema, or row verbs and does not open an entity pool. Entity SQL over MCP is a planned, separate surface that reads through the same Profile Views.
5. Not an authoring surface. The Console data page calls this API to browse rows; Console authoring does not call this API's schema verb.
6. Not an external entity directory. Integrators learn `table_name` by agreement. Browsing definitions uses `GET /entities?status=serving` and requires `entity:read`; it lists only Entities visible to the caller.

### 2.3 Scale Layering

A single Entity Table may reach on the order of 10 million rows. This API is the online synchronous plane: point get, selective Offset pages, `after_row_id` keyset walks, and writes of at most 1000 rows per request. First-load of tens of millions of rows, full refresh, and cross-source assembly belong to a **Data Channel**. Looping `create-many` to load millions is legal and not recommended.

### 2.4 Visibility And Lifecycle

- Only the metadata **head** (latest published version that still has a table) is visible. After a successor publish, schema and row verbs move to the new empty table; prior rows are not migrated.
- Path `{table_name}` is the Entity stem. The service resolves head metadata and the caller's compiled shape. Reads select from the caller's **Profile View** of the head; writes address the head physical table. Neither goes through the stem view.
- Platform `row_id` is server-issued. Clients must not submit it on create. An **Entity Reference** stores the target **Business Key** value without existence checks, foreign keys, or cascades. Encoding follows the reference snapshot frozen at publish.
- Dictionary codes: writable = head snapshot ∩ Dictionary active set; filterable = full snapshot codes. Schema exposes `codes[].writable`.
- Deprecated Entity → `422 ENTITY_DEPRECATED`. No head table, or a head whose reference attributes lack a reference snapshot, → `422 ENTITY_NOT_SERVING`. While any version is `publishing`, schema and reads succeed with `entity.writable=false`; writes → `422 ENTITY_PUBLISHING`.

### 2.5 Explicit Non-Goals (Surface)

No soft delete, aggregates, partial success / 207, top-level array bodies, client-chosen sort, composite unique keys, serving opaque cursor / by-keys / MQ, a separate `query-capabilities` verb, kebab `table_name` aliases, Job-backed load or full export, row-level **Management Audit Event**, ETag, Idempotency-Key, or a single batch larger than 1000. Calls on this API (including via PAT) do not produce Management Audit Events; each call that reaches the access decision appends one Entity Access Log record (`docs/business-entity-access.md` §16). Point get by the head **Business Key** is in scope (§6).

## 3. Cross-Cutting Rules

### 3.1 Transport

Every verb is `POST` with `Content-Type: application/json` and a JSON object body. Success responses use `application/json` except `204` delete. Every HTTP failure uses RFC 9457 Problem Details (`application/problem+json`). `type` is `urn:refraq:problem:{CODE}`. First-party clients branch on `code`.

Authentication is a Session cookie or a User PAT Bearer. Unauthenticated → `401 AUTH_UNAUTHENTICATED` (or `AUTH_PAT_INVALID` for an invalid PAT). Missing **Permission** → `403 AUTH_FORBIDDEN`.

Every response echoes `X-Request-ID`. Success bodies do not include `request_id`. Instants on the wire follow `docs/conventions-time.md`.

Missing body, non-JSON, non-object body, or unknown top-level keys (including `cursor`, `sort`, `keys`) → `422 REQUEST_INVALID`. `schema`, `get`, and `query` also accept top-level `narrow` (`docs/api-contracts-entity-access.md` §5.6); write verbs reject it. The service validates in the order in §10 so the framework does not reject before authentication.

### 3.2 Addressing And Coexistence With Definition API

| Surface | Path identity | Rule |
| --- | --- | --- |
| Definition API | `/entities/{id}` (two segments) and definition subresources | Opaque Entity id only; never falls back to `table_name` |
| Entity Data API | `/entities/{table_name}/{verb}` (three segments) | Immutable `table_name` only; never falls back to id or physical table name |

- Two path segments under `/entities/{x}` are always the definition surface.
- Three segments: if the third segment is one of the ten data verbs below, the second segment is `table_name` and the request is this contract. If the third segment is a definition subresource (`classify`, `deprecate`, `versions`, …), the second segment is Entity `id`. The two reserved sets are disjoint; routing tests guard the partition.
- Unregistered `table_name` (including a value that looks like an id, a physical table name, or characters outside the stem charset), and a registered `table_name` whose Entity gives the caller no effective grant for the verb's action → `404 ENTITY_NOT_FOUND` with the same `detail` (states lookup by `table_name`). Unknown third segment → `404 HTTP_NOT_FOUND` before authentication. Non-`POST` → `405 HTTP_METHOD_NOT_ALLOWED`.
- Do not confuse `DELETE /entities/{id}` (delete a never-published definition) with `POST /entities/{table_name}/delete` (delete one row).

### 3.3 Permissions

| Permission | Covers |
| --- | --- |
| `entity:data_read` | `schema`, `get`, `query` |
| `entity:data_write` | Write verbs additionally require this key |

Write verbs require both `entity:data_read` and `entity:data_write`. Neither is implied by `entity:read` / `entity:write` / `entity:drop_table` / `entity:access_manage`, and the reverse is also false. There is no any-of combination across definition and data keys. Only `super_admin` holds the data keys by default; they are **not** seeded onto `operator`. Other Roles receive them by explicit grant.

The data keys are master switches. Beyond them, a read needs an effective **Access Grant** with `read`, and a write needs one effective grant with `write` that attributes the whole request (`docs/business-entity-access.md` §9–§10). Holding every key, including `super_admin`, does not bypass grants.

Withdrawn names that must not appear as product Permission keys: `entity:consume`, `entity:consume_write`, `entity:read_rows`, `entity:write_rows`, `entity:access`, `entity:access_write`.

### 3.4 Entity Database

Persistent API opens process-local entity owner and reader pools separate from the metadata pool (`docs/env.md`). Reads run on the reader connection against the caller's **Profile View** with the signed access context set for the transaction; writes run on the owner connection in one transaction with the attribution check. The Metadata MCP process and Beat do not open those pools. `schema` uses only the metadata engine and the compiled policy. Memory store mode: `schema` succeeds; row verbs that need the entity database return `503 PLATFORM_CAPACITY_EXCEEDED`. Missing `ENTITY_DATABASE_URL` or `ENTITY_READER_DATABASE_URL` on persistent API fails fast at startup. `/readyz` does not probe the entity database.

## 4. Verb Table

Core logic lives under `backend/entity/data/` (capabilities, head, schema, values, filters, paging, sql, service). HTTP adapters are `backend/entity/routers/data.py`; request shapes are `backend/entity/schemas/data.py` — same `routers/` / `schemas/` layer as definition, with published surface still `backend.entity.routers.*`. There is no REST `/rows` collection. Reads use `POST` (single-method data plane; no GET cache contract).

| Verb | Path | Request body | Success | Permission | Entity DB |
| --- | --- | --- | --- | --- | --- |
| schema | `POST /entities/{table_name}/schema` | `{}` | `200` schema document | `entity:data_read` | no |
| create | `POST /entities/{table_name}/create` | `{ "values": {…} }` | `201 { "row": {…} }` | data_read + data_write | yes |
| create-many | `POST /entities/{table_name}/create-many` | `{ "items": [ { "values": {…} }, … ] }` length 1–1000 | `201 { "rows": […] }` same order as `items` | data_read + data_write | yes |
| get | `POST /entities/{table_name}/get` | `{ "row_id": N }` or `{ "business_key": v }` | `200 { "row": {…} }` | `entity:data_read` | yes |
| update | `POST /entities/{table_name}/update` | `{ "row_id": N, "values": {…} }` or `{ "business_key": v, "values": {…} }` | `200 { "row": {…} }` | data_read + data_write | yes |
| delete | `POST /entities/{table_name}/delete` | `{ "row_id": N }` or `{ "business_key": v }` | `204` empty body | data_read + data_write | yes |
| query | `POST /entities/{table_name}/query` | Offset or keyset (§7) | `200` Offset Page or Entity Data Keyset Page | `entity:data_read` | yes |
| update-where | `POST /entities/{table_name}/update-where` | `{ "filters": …, "set": {…} }` | `200 { "affected": N }` | data_read + data_write | yes |
| delete-where | `POST /entities/{table_name}/delete-where` | `{ "filters": … }` | `200 { "affected": N }` | data_read + data_write | yes |
| upsert | `POST /entities/{table_name}/upsert` | `{ "key"?: "…", "values": {…} }` | insert `201` / update `200` `{ "row": {…} }` | data_read + data_write | yes |

Verb names are lowercase kebab. Qualifiers use a base verb plus a suffix (`-where`, `-many`). Keep `create-many` (not `batch-create` / `bulk-create`): same style as `*-where`, and it does not imply Job or ETL.

Body key mutual exclusion → `422 REQUEST_INVALID`: `update` with `filters`; `create` with `items`; `create-many` with top-level `values`.

## 5. Outbound Schema

`POST /entities/{table_name}/schema` requires body `{}`.

The attribute set is the caller's shape on the head: only attributes in the caller's compiled shape, never the full head when access control removes columns. It omits draft shapes, a publishing successor, superseded versions, and authoring fields (alignment, Job, physical table name, `inbound_references`, `behind`, and similar). Access additions (`attribute_id`, `presentation`, `writable`, `withheld_field`, `access`) are `docs/api-contracts-entity-access.md` §5.2.

Lifecycle matches reads: schema `200` if and only if get/query are available; deprecated or missing head → `422`; publishing → `200` with `entity.writable=false`.

Schema is read-only metadata plus Dictionary; it does not open an entity-database connection. Cache key is `head.version_id` plus `access.policy_revision` and the caller's effective grant set. `operators`, `upsert_key`, and `limits` share the same constants as the filter compiler, pagination, and upsert.

### 5.1 Response Shape

```json
{
  "entity": {
    "id": "ent_01HZX",
    "table_name": "material",
    "name": "Material",
    "description": "…",
    "writable": true
  },
  "head": {
    "version_id": "0123456789abcdef",
    "version": 1
  },
  "row_id": {
    "type": "integer",
    "operators": ["eq", "ne", "in", "gt", "gte", "lt", "lte", "is_null"]
  },
  "business_key": "sku",
  "attributes": [
    {
      "name": "sku",
      "type": "string",
      "required": true,
      "unique": true,
      "indexed": false,
      "business_key": true,
      "description": "SKU code",
      "config": { "max_length": 32 },
      "operators": ["eq", "ne", "in", "contains", "is_null"],
      "upsert_key": true
    }
  ],
  "limits": {
    "page_limit_default": 50,
    "page_limit_max": 200,
    "offset_max": 10000,
    "filter_leaves_max": 20,
    "filter_depth_max": 8,
    "filter_in_values_max": 1000,
    "row_write_max": 1000
  }
}
```

Rules:

- `entity.id` is for correlation, not the routing entry. Path addressing stays `table_name`.
- `head` does not expose the physical table name.
- `row_id` is separate from `attributes`.
- Top-level `business_key` is the head attribute name marked `business_key`, or `null` when the head has none.
- Attribute objects keep the definition attribute keys (`docs/api-contracts-entity.md` §3.1): `name`, `type`, `required`, `unique`, `indexed`, `business_key`, `description`, `config`.
- Additional keys: `operators`; `upsert_key` (true when `unique` and type is not `number` or `json`, **including** `boolean`); for `dictionary`, `dictionary` plus `codes` as `[{ "code", "label", "writable" }]`; for `reference`, `target` as on definition reads except that `target.business_key` is the attribute name stored in the head reference snapshot, `target` is `null` when the target Entity is not visible to the caller, and `operators` are the operators of the snapshotted target Business Key type (`string` or `integer`).
- `limits.row_write_max` is 1000 and is shared by `create-many` and conditional writes.

## 6. Row Write And Read Bodies

- `values` / `set` keys are attribute names in the caller's shape. Present `row_id`, `__withheld`, or a name outside the shape (unknown or hidden alike) → `422 ENTITY_ROW_INVALID`. `update` with `values: {}` or empty `set` → `422`.
- `get` / `update` / `delete` address one row by exactly one of `row_id` or `business_key`. Both, or neither, → `422 REQUEST_INVALID`. `business_key` when the head has no Business Key, a value that does not match the Business Key type, or a blank or whitespace-only string, → `422 REQUEST_INVALID`. Malformed `row_id` → `422 REQUEST_INVALID`. Missing row, or a row the caller cannot see → `404 ENTITY_ROW_NOT_FOUND`.
- `update` and `update-where` must not change the Business Key attribute. A present key for that attribute, including a value equal to the current one, → `422 ENTITY_ROW_INVALID`.
- Every write is attributed to one **Access Grant** and may write only columns that grant presents in `clear`; otherwise `403 ENTITY_ACCESS_WRITE_DENIED` (`docs/api-contracts-entity-access.md` §5.4).
- `fields` is query-only and may include `row_id`. Empty `fields` → `422`. Write responses and get always return the full row of the caller's shape, including `__withheld` when the shape carries it.
- Write responses do not carry `head.version_id`. Callers that need drift detection call schema again.

### 6.1 create-many

- Body `{ "items": [ { "values": {…} }, … ] }`. Length 1–1000. Each element matches single-row create.
- Success `201 { "rows": […] }` with `rows[i]` corresponding to `items[i]`, full rows. Contiguous `row_id` values are not promised.
- One transaction: all succeed or none. Structural errors may list multiple `details`. Semantic failures pick the lowest index. Duplicate unique values inside the batch → `409 ENTITY_ROW_CONFLICT` before SQL when both indices are known; conflict with an existing row → `409` naming the attribute and never the other row's `row_id` or values.
- Empty `items` or length above 1000 → `422 REQUEST_INVALID` (not `ENTITY_ROW_LIMIT_EXCEEDED`).

### 6.2 update And delete By Locator

- `update`: omitted attribute keys keep prior values; explicit JSON `null` clears to SQL NULL. The Business Key attribute cannot appear in `values`. Unique conflict → `409 ENTITY_ROW_CONFLICT`.
- `delete`: `204` with empty body.

### 6.3 upsert

- `key`, when present, must name an attribute with `upsert_key: true` on schema. When omitted, `key` is the head Business Key. Omitted `key` when the head has no Business Key → `422 REQUEST_INVALID`. `values[key]` is required and non-null. The key column is not changeable on update: `values` must not repeat it except as the match value already required by `values[key]`. Concurrent same-key upserts settle to one insert and the rest updates; same-key concurrency does not produce `409`. Upsert matches only rows visible to the caller; a key held by an invisible row, and other-column unique conflicts, → `409 ENTITY_ROW_CONFLICT`.
- Implementation uses row lock plus `INSERT … ON CONFLICT DO NOTHING` then `SELECT`, not `ON CONFLICT DO UPDATE`.

### 6.4 Conditional Writes

- `update-where` / `delete-where`: empty filters, `[]`, or a tree with no leaf → `422 ENTITY_ROW_INVALID`. `set` must not name the Business Key attribute (`422 ENTITY_ROW_INVALID`).
- Filters match rows of the caller's shape on presented values. Match with `SELECT … LIMIT 1001 FOR UPDATE`. Hitting 1001 → `409 ENTITY_ROW_LIMIT_EXCEEDED`. Otherwise mutate by the locked id list. Share `ROW_WRITE_LIMIT = 1000` with `create-many`. Batch update/delete/upsert of arbitrary id lists is out of scope.

## 7. Query

Stable order is `row_id ASC`. Mode is decided by whether the body contains the top-level key `after_row_id` (including JSON `null`). `after_row_id` together with `offset` or `include_total` → `422 REQUEST_INVALID`. Top-level `cursor` → `422 REQUEST_INVALID`.

| Mode | Request | Response |
| --- | --- | --- |
| Offset (no `after_row_id` key) | `filters?`, `fields?`, `limit?`, `offset?`, `include_total?` | **Offset Page** `{ "items", "total", "limit", "offset" }`. `include_total` defaults to **true**. `false` → `total: null` and skip `COUNT` |
| Keyset (key `after_row_id` present) | `filters?`, `fields?`, `limit?`, `after_row_id` (`null` = first page; integer = exclusive lower bound) | **Entity Data Keyset Page** `{ "items", "limit", "next_after_row_id" }`. Implementation fetches `limit + 1` to probe |

Bulkheads: `limit` default 50, max 200; `offset` max 10000. Empty `filters` is allowed. Wide filters with exact `total`, or `contains`, may hit `504 PLATFORM_TIMEOUT` on large tables. Offset cannot walk an entire 10M-row table. Entity Data Keyset Page is not the platform **Cursor Page** and not a serving opaque cursor (`docs/conventions-pagination.md`).

## 8. Filters

Top-level `filters` with leaf triples `field` / `op` / `value`, and groups `all` / `any` (non-empty arrays). `field` is `row_id` or an attribute in the caller's shape; a hidden attribute answers exactly as an unknown one. Leaves compare presented values: masked cells by their masked value, withheld cells as NULL. This contract is self-contained: it does not wrap Action `query.filters` and does not reuse Catalog Sample.

Operators: `eq`, `ne`, `in`, `contains`, `gt`, `gte`, `lt`, `lte`, `is_null`. Caps: 20 leaves, depth 8, total `in` values 1000 (same as schema `filter_*` limits).

Type whitelist (`operators` is the sole source of truth):

| Types | Operators |
| --- | --- |
| string, text | eq, ne, in, contains, is_null |
| integer, number, decimal, date, timestamp, time, row_id | eq, ne, in, gt, gte, lt, lte, is_null |
| reference | operators of the snapshotted target Business Key type (`string` or `integer`) |
| boolean | eq, ne, is_null |
| dictionary, user | eq, ne, in, is_null |
| json | eq, ne, is_null |

`ne` is SQL `IS DISTINCT FROM`. `contains` is `ILIKE` after escaping `\` then `%` and `_`, with explicit `ESCAPE '\'`. Empty `in` or empty `contains` → `422`.

## 9. Value Encoding

| Attribute Type | Inbound | Outbound |
| --- | --- | --- |
| string | string ≤ `max_length` | string |
| text | string | string |
| integer | JSON integer (reject bool, fractional, out of BIGINT) | number |
| reference | the snapshotted target Business Key type: `string` rules or `integer` rules | same as that type |
| row_id | filter and single-row bodies; integer ≥ 1 | number |
| business_key | single-row bodies and the default upsert key; encoded as the head Business Key attribute. A string value must not be blank or whitespace-only | not a column; the attribute value is returned under that attribute's name |
| decimal | number or decimal string; over precision/scale → 422 | decimal string |
| number | JSON number (reject bool, NaN, Inf) | number; NaN/Inf on read → null |
| boolean | only `true` / `false` | boolean |
| date | `YYYY-MM-DD` | same |
| timestamp | RFC 3339 with offset | UTC `Z` |
| time | `HH:MM[:SS[.ffffff]]` without offset | `HH:MM:SS[.ffffff]` |
| json | any non-null JSON | same JSON |
| dictionary | writable code string | string |
| user | id of an existing User (string, at most 64 characters) | string |

JSON `null` is SQL NULL. A masked cell keeps its attribute's outbound wire type; a withheld cell is `null`. `\u0000` is refused. Database `23502` / `23514` / `22xxx` map to `ENTITY_ROW_INVALID`.

## 10. Evaluation Order And Problem Codes

Order: route (unknown segment / method) → authentication → permission → `table_name` resolution and access visibility → access configuration state → deprecated → publishing write refuse → serving head table → request structure → semantics (including shape membership) → in-batch uniqueness (`create-many`) → row existence (visible rows only) → write attribution → conflict. Authentication and permission run before the body is parsed. Missing permission must not reveal whether `table_name` is registered, and missing access must not reveal it either. Schema stops after request structure.

| Situation | HTTP | Code |
| --- | --- | --- |
| No credentials / invalid PAT | 401 | `AUTH_UNAUTHENTICATED` / `AUTH_PAT_INVALID` |
| Missing Permission | 403 | `AUTH_FORBIDDEN` |
| `table_name` not registered, or no effective grant for the action | 404 | `ENTITY_NOT_FOUND` |
| Views do not match the policy revision, or the caller's combination view is being generated | 503 + `Retry-After` | `ENTITY_ACCESS_PENDING` |
| The caller's profile combination exceeds the cap | 409 | `ENTITY_ACCESS_COMBINATION_LIMIT` |
| No single `write` grant attributes the write | 403 | `ENTITY_ACCESS_WRITE_DENIED` |
| Unknown third segment | 404 | `HTTP_NOT_FOUND` |
| Non-POST | 405 | `HTTP_METHOD_NOT_ALLOWED` |
| Deprecated / publishing write / no head table / missing reference snapshot | 422 | `ENTITY_DEPRECATED` / `ENTITY_PUBLISHING` / `ENTITY_NOT_SERVING` |
| Body structure / bounds / mutually exclusive keys / unknown top-level keys / blank `business_key` locator | 422 | `REQUEST_INVALID` |
| Attribute / filter / code / blank Business Key value / empty conditional filters | 422 | `ENTITY_ROW_INVALID` |
| Unknown or invisible `row_id` or `business_key` | 404 | `ENTITY_ROW_NOT_FOUND` |
| Unique conflict (including in-batch) | 409 | `ENTITY_ROW_CONFLICT` |
| Conditional write matched more than 1000 rows | 409 | `ENTITY_ROW_LIMIT_EXCEEDED` |
| Entity pool checkout timeout / memory-mode row verb | 503 + `Retry-After` | `PLATFORM_CAPACITY_EXCEEDED` |
| `statement_timeout` | 504 | `PLATFORM_TIMEOUT` |

During execution, missing relation `42P01` → `ENTITY_NOT_SERVING`. `23505` → `ENTITY_ROW_CONFLICT`. Do not add `ENTITY_ROW_HEAD_CHANGED`. Do not reuse `ENTITY_NOT_PUBLISHED`. These verbs do not pass platform admission.

## 11. Non-Goals

1. Replacing or narrowing **Data Channel** responsibility.
2. ISC serving wire compatibility (opaque cursor, by-keys, MQ, 400 error style, x-api-key).
3. Metadata MCP tools or a Metadata MCP entity pool for this surface. Entity SQL over MCP is a planned, separate surface outside this contract.
4. Console authoring calling this schema.
5. An external entity directory or kebab `table_name` aliases.
6. Soft delete, aggregates, partial success, client sort, composite uniqueness.
7. Row-level Management Audit Events, ETag, Idempotency-Key.
8. Job-backed bulk load, full export, or batches larger than 1000.

## 12. References

- `docs/business-entity.md`
- `docs/api-contracts-entity.md`
- `docs/business-entity-access.md`
- `docs/api-contracts-entity-access.md`
- `docs/business-login-auth.md`
- `docs/business-user-tokens.md`
- `docs/conventions-errors.md`
- `docs/conventions-pagination.md`
- `docs/conventions-time.md`
- `docs/env.md`
- `docs/glossary.md`
