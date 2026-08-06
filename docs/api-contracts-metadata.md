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
  "collected_from_connection_id": "conn_mes_prod",
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

Identity is `source_id` (+ object coordinates). `collected_from_connection_id` is optional provenance only.
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

Reject joins that lack evidence with `JOIN_EVIDENCE_REQUIRED`.

## 6. Controlled Query (D)

### `POST /connections/{id}/query`

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
| `QUERY_NOT_READONLY` | DDL/DML/unclassified |
| `QUERY_MULTI_STATEMENT` | More than one statement |
| `QUERY_TIMEOUT` | Exceeded timeout |
| `QUERY_ROW_LIMIT` | Rejected before run if max_rows above platform cap |

Every attempt writes a management audit event (statement summary or hash, never Connection secret).
