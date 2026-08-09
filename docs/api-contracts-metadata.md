# refraq API Contracts: Catalog, Semantics, Joins, Query

## 1. Purpose

HTTP contracts for collected **Catalog Objects**, semantics, join edges, and controlled query.

Business rules: `docs/business-metadata.md`.
Auth: Session or User PAT.

Slice availability:

| Surface | Slice | Permissions |
| --- | --- | --- |
| Objects / columns / DDL | A | `metadata:read` |
| Semantics R/W | B | read `metadata:read`; write `metadata:write` |
| Joins R/W | C | read `metadata:read`; write `metadata:write` |
| Controlled query | D | `query:run` |

## 2. Catalog Object Shape

```json
{
  "id": "obj_01",
  "source_id": "src_mes_prod",
  "object_type": "table",
  "schema_name": "dbo",
  "name": "WORK_ORDER",
  "business_name": null,
  "business_description": null,
  "columns": [
    {
      "id": "col_01",
      "name": "WO_ID",
      "data_type": "NUMBER",
      "nullable": false,
      "business_name": null,
      "business_description": null
    }
  ],
  "ddl": null,
  "collected_at": "2026-08-05T02:05:00Z"
}
```

Identity is `source_id` (+ object coordinates). `collected_at` is optional provenance only.
Semantics fields are null until slice B writes them.

## 3. Browse Endpoints (A+)

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `GET` | `/sources/{id}/objects` | `metadata:read` | List objects (query: name search) |
| `GET` | `/objects/{id}` | `metadata:read` | Object detail including columns |
| `GET` | `/objects/{id}/ddl` | `metadata:read` | DDL text when stored |

## 4. Semantics Endpoints (B)

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `PATCH` | `/objects/{id}/semantics` | `metadata:write` | Set object business_name / business_description |
| `PATCH` | `/columns/{id}/semantics` | `metadata:write` | Set column semantics |

Response envelopes: object patch → `{ "object": … }` (same shape as `GET /objects/{id}`); column patch → `{ "column": … }`.

Rules: omit fields leave unchanged; explicit clear uses a documented sentinel or dedicated clear endpoint — do not treat JSON `null` as wipe unless the contract for that field says so.

## 5. Join Endpoints (C)

### Join edge shape

```json
{
  "id": "join_01",
  "from_column_id": "col_a",
  "to_column_id": "col_b",
  "evidence": "Verified FK in DDL / successful probe query",
  "created_by_user_id": "user_001",
  "created_at": "2026-08-05T03:00:00Z"
}
```

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `GET` | `/objects/{id}/joins` | `metadata:read` | List joins touching object |
| `PUT` | `/joins` | `metadata:write` | Upsert edge with evidence |
| `DELETE` | `/joins/{id}` | `metadata:write` | Remove edge |

Response envelopes: list → `{ "items": [Join] }`; upsert → `{ "join": Join }`; delete → `204` No Content.

Reject joins that lack evidence with `JOIN_EVIDENCE_REQUIRED`. Cross-Source edges → `JOIN_CROSS_SOURCE`. Self-loop → `JOIN_INVALID`.

## 6. Controlled Query (D)

### `POST /sources/{id}/query`

Permission: `query:run`.

Request:

```json
{
  "sql": "SELECT WO_ID FROM WORK_ORDER WHERE ROWNUM <= 10",
  "max_rows": 100
}
```

Response `200`:

```json
{
  "columns": ["WO_ID"],
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
