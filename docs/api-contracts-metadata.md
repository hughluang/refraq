# refraq API Contracts: Catalog, Semantics, Joins, Query

## 1. Purpose

HTTP contracts for collected **Catalog Objects**, semantics, join edges, search, join paths, and controlled query.

Business rules: `docs/business-metadata.md`.
Auth: Session or User PAT.

Slice / permission availability:

| Surface | Phase | Permissions |
| --- | --- | --- |
| Objects / columns / DDL | A | `metadata:read` |
| Semantics R/W | B + Depth | read `metadata:read`; write `metadata:write` |
| Joins R/W | C + Depth | read `metadata:read`; write `metadata:write` |
| Search / join path | Depth | `metadata:read` |
| Controlled query | D | `query:run` |

All Source and catalog responses include `locator_key` (ADR 0012). HTTP path parameters remain surrogate ids.

## 2. Catalog Object Shape

```json
{
  "id": "obj_01",
  "locator_key": "obj/postgresql/demo-src/public/table/orders",
  "source_id": "src_demo",
  "object_type": "table",
  "schema_name": "public",
  "name": "orders",
  "comment": null,
  "primary_key": ["order_id"],
  "business_name": null,
  "business_description": null,
  "object_category": null,
  "grain_description": null,
  "business_primary_key": null,
  "business_domain": null,
  "evidence_summary": null,
  "open_questions": null,
  "semantic_source": null,
  "business_semantics_ready": false,
  "semantics_updated_at": null,
  "columns": [
    {
      "id": "col_01",
      "locator_key": "col/postgresql/demo-src/public/table/orders/column/order_id",
      "name": "order_id",
      "data_type": "integer",
      "nullable": false,
      "default_value": null,
      "comment": null,
      "business_name": null,
      "business_description": null,
      "column_semantics": null,
      "enum_catalog": null,
      "semantic_source": null,
      "field_kind": "column",
      "ordinal": 1,
      "is_present": true
    }
  ],
  "foreign_keys": [
    {
      "name": "fk_orders_customer",
      "columns": ["customer_id"],
      "ref_schema": "public",
      "ref_table": "customers",
      "ref_columns": ["id"],
      "is_present": true
    }
  ],
  "indexes": [
    {
      "name": "ix_orders_customer_id",
      "columns": ["customer_id"],
      "is_unique": false,
      "is_present": true
    }
  ],
  "ddl": null,
  "is_present": true,
  "collected_at": "2026-08-05T02:05:00Z"
}
```

Identity is `source_id` (+ object coordinates). `collected_at` is optional provenance only.
`field_kind` is read-only on semantics writes (structure-held). `model_routing_hint` is not in this phase.
`time_semantics`, `status_semantics`, `relation_summary`, and `confidence` are removed from read and write contracts (ADR 0015); time/status meaning lives on column descriptions (and optional free-text `semantic_type` / `enum_catalog` — closed vocabulary deferred, ADR 0016); object relationships live in join edges.
`business_domain` on read is `{ "id", "code", "name" } | null` (ADR 0017). Object semantics writes accept `business_domain_code` (not the nested object); JSON `null` does not clear (ADR 0014).
`foreign_keys` and `indexes` are included on object detail (`GET /objects/{id}` and semantics write responses); list/search endpoints return empty arrays for these fields.

## 3. Browse Endpoints (A+)

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `GET` | `/sources/{id}/objects` | `metadata:read` | List objects (query: `q`, `object_type`, `include_absent`, `limit`, `offset`) |
| `GET` | `/objects/{id}` | `metadata:read` | Object detail including columns |
| `GET` | `/objects/{id}/ddl` | `metadata:read` | DDL text when stored |

List response: `{ "items": […], "total": N, "limit": L, "offset": O }` when pagination params are used; `limit` default 100, max 500.

## 4. Semantics Endpoints (B + Depth)

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `PATCH` | `/objects/{id}/semantics` | `metadata:write` | Patch object semantics fields (§2 shape) |
| `PATCH` | `/columns/{id}/semantics` | `metadata:write` | Patch column semantics fields |
| `PATCH` | `/objects/{id}/columns/semantics` | `metadata:write` | Batch patch column semantics by `column_name` |

Request bodies accept any subset of the writable semantics fields in §2 (not `field_kind`; not `model_routing_hint`; not the fields removed by ADR 0015). Object writes use `business_domain_code` to attach a Business Domain. Response envelopes: object → `{ "object": … }`; column → `{ "column": … }`. Console writes set `semantic_source=user_input`; MCP writes set `semantic_source=mcp`. JSON `null` does not clear existing values (ADR 0014).

Batch column body:

```json
{
  "columns": [
    {
      "column_name": "status",
      "business_name": "Status",
      "business_description": "Lifecycle state",
      "column_semantics": { "semantic_type": "status", "value_pattern": null, "unit": null },
      "enum_catalog": [{ "code": "OPEN", "label": "Open", "description": null }]
    }
  ]
}
```

Batch response: `{ "object": …, "updated_count": N, "requested_count": M, "skipped_columns": [{ "column_name": "…", "reason": "…" }] }`.

Rules: omit fields leave unchanged; JSON `null` does not wipe; explicit clear deferred.

Validation:

| Code | When |
| --- | --- |
| `SEMANTIC_COLUMN_UNKNOWN` | `business_primary_key` names a column that does not exist on the object |
| `BUSINESS_DOMAIN_UNKNOWN` | `business_domain_code` does not match an existing Business Domain |

`semantic_type` is free text in this phase (ADR 0016); there is no `SEMANTIC_TYPE_INVALID` reject and no derived `semantic_gaps`.

## 4.1 Business Domain Endpoints (ADR 0017)

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `GET` | `/business-domains` | `metadata:read` | List domains (`q`, `limit`, `offset`) |
| `POST` | `/business-domains` | `metadata:write` | Create (`code`, `name`, `description?`) |
| `PATCH` | `/business-domains/{id}` | `metadata:write` | Patch `name` / `description` (`code` immutable) |
| `DELETE` | `/business-domains/{id}` | `metadata:write` | Delete; blocked when referenced (`BUSINESS_DOMAIN_IN_USE`) |

Domain shape: `{ "id", "code", "name", "description", "created_at", "updated_at" }`.
Create conflicts on duplicate `code` → `BUSINESS_DOMAIN_CODE_CONFLICT`. Missing id → `BUSINESS_DOMAIN_NOT_FOUND`.

## 5. Join Endpoints (C + Depth)

### Join edge shape

```json
{
  "id": "join_01",
  "from_column_id": "col_a",
  "to_column_id": "col_b",
  "from_column_locator_key": "col/postgresql/demo-src/public/table/orders/column/order_id",
  "to_column_locator_key": "col/postgresql/demo-src/public/table/order_lines/column/order_id",
  "evidence": "FK fk_order_lines_order",
  "join_kind": "INNER",
  "join_expression": "a.order_id = b.order_id",
  "origin": "foreign_key",
  "created_by_user_id": "user_001",
  "created_at": "2026-08-05T03:00:00Z"
}
```

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `GET` | `/objects/{id}/joins` | `metadata:read` | List joins touching object |
| `PUT` | `/joins` | `metadata:write` | Upsert single edge (`origin=human` when via Console) |
| `PUT` | `/joins:batch` | `metadata:write` | Batch upsert; all edges same Source |
| `DELETE` | `/joins/{id}` | `metadata:write` | Remove edge |
| `GET` | `/joins/path` | `metadata:read` | Join path lookup |

Batch request:

```json
{
  "joins": [
    {
      "from_column_id": "col_a",
      "to_column_id": "col_b",
      "evidence": "…",
      "join_kind": "INNER",
      "join_expression": null
    }
  ]
}
```

Batch response: `{ "created_count": 1, "already_known_count": 0, "items": [Join] }`.

Path query params: `start` (object or column id or locator_key), optional `target`, `max_hops` (1–5, default 1), `top_targets` (default 3).

Path response: `{ "paths_found": N, "paths": […], "direct_joins": […], "reason": null | "…" }`.
`reason` may be set when no usable path is returned (e.g. `TARGET_UNREACHABLE`).

Reject joins that lack evidence with `JOIN_EVIDENCE_REQUIRED`. Cross-Source edges → `JOIN_CROSS_SOURCE`. Self-loop → `JOIN_INVALID`.

## 6. Search Endpoints (Depth)

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `GET` | `/catalog/objects/search` | `metadata:read` | Cross-Source object search |
| `GET` | `/catalog/columns/search` | `metadata:read` | Cross-Source column search |

Query params: `q` (**required**, non-empty for both objects and columns), `source_id`, `object_type`, `limit` (default 20, max 100), `offset`.

Response: `{ "items": […], "total": N, "limit": L, "offset": O }`. Ranking: exact locator/name → prefix → name substring → business name/description substring.

## 7. Controlled Query (D)

### `POST /sources/{id}/query`

Permission: `query:run`.

Request:

```json
{
  "sql": "SELECT order_id FROM orders LIMIT 10",
  "max_rows": 100
}
```

Response `200`:

```json
{
  "columns": ["order_id"],
  "rows": [["1001"]],
  "truncated": false,
  "duration_ms": 12
}
```

Errors:

| code | When |
| --- | --- |
| `QUERY_NOT_READONLY` | DDL/DML/unclassified, parse failure, row locking, blocked functions |
| `QUERY_MULTI_STATEMENT` | More than one statement |
| `QUERY_TIMEOUT` | Exceeded timeout |
| `QUERY_ROW_LIMIT` | Rejected before run if max_rows above platform cap |

Every attempt writes a management audit event (statement summary or hash, never Source secret).

Envelope notes: request `max_rows` defaults to **100** when omitted; values above platform cap `REFRAQ_QUERY_MAX_ROWS` (default **1000**) are rejected with `QUERY_ROW_LIMIT` before connect. Platform timeout is `REFRAQ_QUERY_TIMEOUT_SEC` (default **30**), enforced both at the application boundary and via engine statement/command timeout. L4 SQL guards parse a single statement with a dialect-aware AST (sqlglot) for the Source engine and fail closed on write nodes, `INTO`, row locks, blocked functions, or unparseable SQL. Prefer a read-only database account on the Source as defense in depth; platform SQL guards remain mandatory.
