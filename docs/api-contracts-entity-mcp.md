# refraq API Contracts: Entity MCP

## 1. Purpose

This document defines the **Entity MCP endpoint**: the read-only MCP tool face for **Business Entity** data the caller's **Access Grant**s allow, including read-only SQL over Entity `table_name`s.

The product port is MCP Streamable HTTP at the Console-origin path `/mcp/entity`. Auth is **User PAT** in the HTTP `Authorization: Bearer` header only. Tool arguments do not include `authorization`. Session cookies are not credentials on this path. There is no OAuth discovery document and no well-known metadata.

`GET /mcp/entity/catalog` on the API process accepts a Session or a User PAT and no extra Permission. It is the cropped Entity tool list for the Entity endpoint. The Console surface is `/console/mcp/entity`. The overview `/console/mcp` may link here; it does not serve this catalog as if it were Metadata. This catalog is not the Metadata catalog and is not an MCP connection.

The **Entity Data API** remains the HTTP data plane (`docs/api-contracts-entity-data.md`). `get_row` and `query_rows` call that service. This document defines the tool arguments, the SQL gate, the SQL result, and the Problem Codes of this host. It does not define Business Entity authoring (`docs/api-contracts-entity.md`) or access-management HTTP (`docs/api-contracts-entity-access.md`).

Related boundaries:

- Entity Access Control and the Entity Access Log: `docs/business-entity-access.md`
- Entity Data API shapes that `get_row` and `query_rows` reuse: `docs/api-contracts-entity-data.md`, `docs/api-contracts-entity-access.md` §5
- Metadata MCP, a different host at `/mcp`: `docs/api-contracts-metadata-mcp.md`
- Problem Codes: `docs/conventions-errors.md`
- System Parameters `entity_query_timeout_sec` and `entity_query_max_rows`: `docs/business-system-parameters.md` §5
- Process role, pools, and the signer login: `docs/env.md`
- Terminology: `docs/glossary.md`

## 2. Host

Process role `entity_mcp`. Entry `python -m backend.entity.mcp.http`. Bind `REFRAQ_ENTITY_MCP_HOST` (default `127.0.0.1`) and `REFRAQ_ENTITY_MCP_PORT` (default `8002`). The server is stateless. `tools/list` is cached 30000 ms, scope private.

The process opens the metadata pool and the entity reader pool. It also opens a signer pool of size 1 and overflow 0 on `ENTITY_SIGNER_DATABASE_URL`. That login may execute only `acl.ensure_signing_key()`. The process does not open the entity owner pool and does not read `ENTITY_ADMIN_DATABASE_URL`. `ENTITY_DATABASE_URL` is optional; when it is set, the reader database must be that same database. API and worker still sign access contexts with the owner pool.

Startup, when the store is persistent, refuses a missing reader URL, a reader database equal to the `DATABASE_URL` database, a superuser or `BYPASSRLS` reader login, a missing signer URL, a signer database different from the reader database, and a superuser or `BYPASSRLS` signer login.

The Console proxies `POST /mcp/entity` to `REFRAQ_ENTITY_MCP_UPSTREAM` (default `http://127.0.0.1:8002`) at path `/mcp/entity`. The proxy timeout is 305 seconds. Upstream failure is HTTP 502 `{ "error": "mcp_upstream_unavailable" }`. Compose service `entity-mcp` publishes no port. It has `DATABASE_URL`, `REDIS_URL`, `ENTITY_READER_DATABASE_URL`, and `ENTITY_SIGNER_DATABASE_URL`. It does not have the owner URL or the admin URL. Compose builds the signer URL for role `refraq_signer` by interpolating `ENTITY_SIGNER_PASSWORD`. Bootstrap reads that password from `ENTITY_SIGNER_DATABASE_URL`.

Gate, same as the Metadata MCP endpoint:

- Missing, invalid, or cookie-only credentials → HTTP 401 `AUTH_UNAUTHENTICATED`, for every method, before discovery
- After authentication, any method other than POST → HTTP 405 `HTTP_METHOD_NOT_ALLOWED` with `Allow: POST`

Those two answers are HTTP Problem Details. Tool failures are not. Tool-error envelope:

```json
{ "error": { "code": "ENTITY_NOT_FOUND", "message": "Business Entity with table_name 'orders' was not found" } }
```

`message` is the English `AppError` text. An unexpected exception is `MCP_ERROR`. The envelope has no `sqlstate` member; a SQLSTATE that this host reports is inside `message`.

Server instructions:

```text
Refraq Entity MCP is the read-only face for Business Entity data the current user can read.

Workflow: call list_entities to discover Entities, describe_entity to see the attributes you can use, validate_sql to check a statement, then run_sql to execute it.

Join Entities on the declared references returned by describe_entity. Do not guess join keys from column names.

Masked columns group and filter on masked values, not on the underlying values.

Withheld cells are NULL and are listed in __withheld.

This face does not write Entity data, change definitions, or read the Change Log.
```

`GET /mcp/entity/catalog` is the cropped Entity tool list for the Entity endpoint. The Console surface is `/console/mcp/entity`. It is not the Metadata catalog and not an MCP connection. The overview `/console/mcp` may link here; it does not serve this catalog as if it were Metadata.

### 2.1 `GET /mcp/entity/catalog`

Auth: Session cookie or User PAT. No extra **Permission**.

Success `200`:

```json
{
  "public_path": "/mcp/entity",
  "tools": [
    {
      "name": "list_entities",
      "permission": "entity:data_read",
      "description": "…",
      "execution": "read"
    }
  ]
}
```

`tools` is the caller's cropped catalog, in the order in §4. An empty array is valid. Each tool object includes `execution` beside `name`, `permission`, and `description`. The browser builds `{origin}{public_path}`.

## 3. Authorization

Every tool requires `entity:data_read`. Without it, `tools/list` and `GET /mcp/entity/catalog` are empty. A call that still invokes a tool is `AUTH_FORBIDDEN` with message `Missing permission entity:data_read`.

An Entity is reachable when the caller has at least one effective **Access Grant** with action `read` (directly, through the Role, or through a **User Group**). `entity:write` and `entity:access_manage` do not add Entities or columns. The shape, rows, and cells are the caller's un-narrowed `read` shape, the same shape the Entity Data API uses when `narrow` is omitted. The stored `mcp_query` and `export` actions are not evaluated.

An unregistered `table_name` and a registered `table_name` with no effective `read` grant produce the same `ENTITY_NOT_FOUND` and the same message: `Business Entity with table_name '{name}' was not found`. In SQL, `{name}` is the identifier as written.

Deprecated, not-serving, pending, and combination-limit states use the Entity Data API codes: `ENTITY_DEPRECATED`, `ENTITY_NOT_SERVING`, `ENTITY_ACCESS_PENDING` (retryable), `ENTITY_ACCESS_COMBINATION_LIMIT`. A deprecated or not-serving Entity that still has a `read` grant is a visible SQL name and then fails with its lifecycle code. A successor publish does not block schema or reads.

`describe_entity`, `list_dictionary_codes`, `get_row`, and `query_rows` do not advertise `narrow`. A non-null `narrow` on those tools is `REQUEST_INVALID` with message `narrow is not accepted`, before admission. The other tools have no `narrow` argument.

All eight tools have `execution` `read`, including `run_sql` and `search_entities`. `read` does not mean the tool skips audit or maintenance effects. `tools/list` copies that class onto the tool as `_meta["io.refraq/execution"]`. Absent `_meta`, an absent key, or any other value is not `read`. `readOnlyHint` is advisory and is not this class; it does not replace the gate or the read-only transaction.

## 4. Tool Catalog

Order, Permission `entity:data_read` on every row:

| Tool | Purpose |
| --- | --- |
| `list_entities` | Offset Page of serving Entities the caller can read |
| `describe_entity` | One Entity as the caller can read it |
| `list_dictionary_codes` | Offset Page of one dictionary attribute's codes |
| `get_row` | One row, wrapped as `{ "row": … }` |
| `query_rows` | Entity Data API query envelope |
| `validate_sql` | Gate, bind, and access-check one statement; no execution |
| `run_sql` | Execute that statement on the reader |
| `search_entities` | Cosine rank of serving Entities the caller can read |

`get_row`, `query_rows`, and `run_sql` run inside platform admission (`await_admitted` on the User id). `ADMISSION_CAPACITY_EXCEEDED` and `ADMISSION_ACTOR_LIMIT_EXCEEDED` are the tool-error envelope. A reader-pool checkout timeout is `PLATFORM_CAPACITY_EXCEEDED`. Discovery tools, `validate_sql`, and `search_entities` do not enter admission and do not open an entity connection.

The admission pool does not copy context. `get_row`, `query_rows`, and `run_sql` bind the PAT id and the calling request id inside the admitted callable. A missing request id stays null. The HTTP gate also binds the PAT id, so `describe_entity` and `list_dictionary_codes` record it on the request thread.

## 5. Discovery Tools

### 5.1 `list_entities`

Arguments: `query_text` (optional), `limit` (optional), `offset` (optional).

Result is an **Offset Page** `{ "items", "total", "limit", "offset" }`. `limit` defaults to 50. A supplied value is clamped to the integers 1 through 200, and the clamped value is echoed. `offset` below 0 is 0.

Each item is `{ "table_name", "name", "description", "tags" }`. `tags` is `[{ "id", "name" }]`, the same Tag assignment the Entity HTTP projection uses.

The page includes Entities whose list status is `serving` (a serving head with a publishing successor is `serving`) and on which the caller holds an effective `read` grant. Order is `table_name` ascending.

`query_text` is a case-insensitive substring of `name`, `table_name`, or `description`. A whitespace-only `query_text` is not a filter: the candidate listing strips it and then treats it as absent. `list_dictionary_codes` does not strip; see §5.3.

### 5.2 `describe_entity`

Argument: `table_name`.

The body is the Entity Data API outbound schema for the caller's un-narrowed read shape (`docs/api-contracts-entity-data.md` §5, `docs/api-contracts-entity-access.md` §5.2), then:

- `entity.writable` is omitted
- each attribute omits `writable` and `upsert_key`
- `limits.row_write_max` is omitted
- a dictionary attribute's `codes` are at most 50 objects `{ "code", "label", "active" }`, in snapshot order, where `active` is that schema code's `writable`; `codes_truncated` is true when the snapshot has more than 50 codes, otherwise false
- `references` is `[{ "attribute", "target" }]` for each reference attribute still in the shape; `target` is `{ "table_name", "business_key" }` or `null`
- `inbound_references` is `[{ "table_name", "attribute" }]`

On a reference attribute, `target` is `null` when the caller has no effective `read` grant on the target Entity. `entity:write` and `entity:access_manage` do not make a target visible. A self-reference is visible. When the target is visible, the attribute's `target` object still carries the schema fields (`entity_id`, `name`, `table_name`, `business_key`). `references[].target` keeps only `table_name` and `business_key`. Operators still follow the snapshotted key type.

Inbound references are collected from each Entity's latest published head. A deprecated Entity that still has a published head is included. An unpublished current version is not the source. The caller's effective `read` grant then drops hidden referrers. Of a visible referrer, only attributes in that referrer's un-narrowed read shape are listed. An over-limit combination or an empty shape omits that referrer's attributes. When the serving head cannot be loaded, the attribute name is kept. `entity:write` does not widen this list.

Both this tool and `list_dictionary_codes` call the schema path, so the Entity Access Log verb is `schema`.

### 5.3 `list_dictionary_codes`

Arguments: `table_name`, `attribute`, optional `query_text`, `limit`, `offset`.

The attribute must be a dictionary attribute in the caller's read shape. A missing or hidden attribute is `REQUEST_INVALID` with message `Attribute '{name}' was not found`. A visible attribute that is not a dictionary is `REQUEST_INVALID` with message `Attribute '{name}' is not a dictionary`.

Codes come from the head snapshot only, with current labels. `active` is the schema code's `writable`. `query_text` is a case-insensitive substring of `code` or `label`. A whitespace-only `query_text` is not stripped. It matches a `code` or `label` only when that text contains the same whitespace. `limit` defaults to 50. A supplied value is clamped to the integers 1 through 200, and the clamped value is echoed. `offset` below 0 is 0. The result is an Offset Page of `{ "code", "label", "active" }`.

### 5.4 `search_entities`

Arguments: `query_text` (required), `limit` (optional).

`query_text` is trimmed. Empty or whitespace-only text is `REQUEST_INVALID` with message `query_text is required`. Longer than 2000 characters is `REQUEST_INVALID` with message `query_text must be at most 2000 characters`. `limit` defaults to 10. A supplied value must be an integer from 1 through 50. A boolean, a non-integer, or a value outside that range is `REQUEST_INVALID` with message `limit must be an integer from 1 through 50`. Out-of-range limits are not clamped.

The tool requires the same `entity:data_read` gate and an effective `read` grant as `list_entities`. It ranks only serving Entities. Authoring permission and Super Admin status do not add Entities. Deprecated and not-serving Entities are omitted.

Before ranking, the call requires an in-use embedding service with a URL, an open purpose, and an Entity index that is ready on that service's generation. No in-use service is `MODEL_SERVICE_NOT_IN_USE`. A closed purpose is `MODEL_SERVICE_CLOSED`. A missing URL is `MODEL_SERVICE_ENDPOINT_MISSING`. An index that is not ready, or ready on another generation, is `ENTITY_INDEX_NOT_READY`. Those failures are not an empty `items` list.

When the index is ready and no currently readable Entity has a current projection, the result is `{ "items": [] }` and the embedding endpoint is not called.

Otherwise the result is `{ "items": [ … ] }` ordered by `score` descending, then `table_name` ascending. Each item is `{ "table_name", "name", "description", "tags", "score" }`. `tags` is the same `[{ "id", "name" }]` assignment as §5.1. `score` is cosine similarity. It is not a confidence and not a probability. There is no score cutoff, including no distance cutoff, and there is no `offset`, `total`, or further page. A concurrent grant or definition change may return fewer than `limit` items. The tool does not fill the count with a stale row.

A model call that fails, or that does not return one usable vector, is `ENTITY_SEARCH_EMBED_FAILED`. A generation or control revision that changes during the call is `MODEL_SERVICE_GENERATION_MISMATCH` or `MODEL_SERVICE_CONTROL_REVISION_MISMATCH`. The tool does not fall back to `list_entities` or to a lexical rank. A hit does not authorize `describe_entity`, a row read, or SQL.

## 6. Row Tools

`get_row` and `query_rows` call the Entity Data service. Encodings, filters, and lifecycle errors match that API. `__withheld` is present on the returned row or rows when the shape's `withheld_field` is `"__withheld"`: an array of withheld column names, empty when none of those cells are withheld on that row. A shape that does not withhold leaves the row without that key. Withheld cells are `null`.

### 6.1 `get_row`

Arguments: `table_name`, and exactly one of `row_id` (integer ≥ 1) or `business_key`. Both, or neither, is `REQUEST_INVALID`. A missing row, or a row the caller cannot see, is `ENTITY_ROW_NOT_FOUND`.

Result: `{ "row": <Entity Data API get object> }`.

### 6.2 `query_rows`

Arguments: `table_name`, and the Entity Data API query fields `filters`, `fields`, `limit`, `offset`, `include_total`, `after_row_id`. A null optional field is omitted, so an omitted `after_row_id` stays offset mode. JSON `null` for `after_row_id` is the first keyset page. `after_row_id` together with `offset` or `include_total` is `REQUEST_INVALID`.

`limit` defaults to 50 and must be an integer from 1 through 200. `offset` must be an integer >= 0 and has no maximum. A `limit` outside that range, or an `offset` that is not an integer >= 0, is `REQUEST_INVALID`. These tools do not clamp either value.

The result is the Entity Data envelope unchanged: offset mode `{ "items", "total", "limit", "offset" }`, or keyset mode `{ "items", "limit", "next_after_row_id" }` (`docs/api-contracts-entity-data.md` §7).

## 7. SQL Gate And Name Binding

`validate_sql` and `run_sql` share one prepare step. Dialect is PostgreSQL. The gate runs before any entity connection.

Accepted: exactly one statement; top-level `SELECT`, `UNION`, `INTERSECT`, or `EXCEPT`; CTEs including `WITH RECURSIVE`; joins of any number of Entities; subqueries; `LATERAL`; window functions; aggregates; one trailing semicolon and trailing comments.

Rejected as `ENTITY_SQL_INVALID` with a message that names the construct:

| Condition | Message |
| --- | --- |
| Empty input | `SQL statement is empty` |
| Parse or tokenize failure | `Invalid SQL: …` (one line, no highlighted snippet) |
| More than one statement | `Multiple statements are not allowed` |
| Root is not a read query | `{label} is not allowed` (`EXPLAIN`, `SHOW`, `VACUUM`, `DO`, and any other opaque command use the command word) |
| `SELECT INTO` | `SELECT INTO is not allowed` |
| Locking clause | `Row locking ({clause}) is not allowed` (the clause text, including `FOR SHARE`) |
| `SET`, `RESET`, transaction, `COMMIT`, `ROLLBACK`, write, DDL, or `COPY`, anywhere in the tree, including a data-modifying CTE | `{label} is not allowed` |
| Schema-qualified relation | `Schema-qualified relation {name} is not allowed` |
| Cast to `oid` or a `reg*` type, bare, quoted, or schema-qualified | `Cast to {label} is not allowed` |
| Schema-qualified function call | `Schema-qualified function {schema}.{name} is not allowed` |
| Blocked function | `Function {name} is not allowed` |

Blocked function names: `set_config`, `current_setting`, every name that starts with `pg_` (including `pg_sleep`, `pg_get_viewdef`, `pg_get_functiondef`, and file functions), `has_*_privilege`, `to_reg*`, `lo_*`, `dblink*`, and names that start with `query_to_xml`, `table_to_xml`, `cursor_to_xml`, `schema_to_xml`, or `database_to_xml`. A typed function is matched by its SQL name and by its class name, not only by an anonymous label.

Name matching folds an unquoted identifier to lower case and matches a quoted identifier exactly. Entity `table_name`s are the lower-case stem charset. An unknown name and a name absent from the caller's visible set are the same `ENTITY_NOT_FOUND`, message `Business Entity with table_name '{name}' was not found`, with `{name}` as written. Visible names include deprecated and not-serving Entities that have a `read` grant; those bind, then fail their lifecycle code.

Binding rewrites each unqualified relation that is not a CTE in scope to that caller's **Profile View** for the head (`entity_access.<view>`), aliased to the original name. An alias the statement already has is kept. A CTE name that shadows an Entity name binds to the CTE. Schema-qualified relations are rejected before binding. The bound text is `statement.sql(dialect="postgres")`. Callers echo the submitted text. Bound SQL is never returned and never logged. Physical table names, stem view names, and Profile View names do not appear in a successful result or in an error message.

`partial_columns` lists `{ "table_name", "column" }` for each row-varying column of a referenced Entity that the statement names. An unqualified column is attributed only to Entities of the nearest scope. A bare `*` or `alias.*` includes every row-varying column of the Entities that star selects. `__withheld` is a legal SQL column name. The list is sorted by `table_name`, then `column`. `entities` is the referenced `table_name`s, sorted.

Failure order: gate rejection, then the first unknown or invisible name in scope-walk order, then access decisions in `table_name` order. The first failure wins.

A pending access decision does not write an Entity Access Log record and does not open an entity connection in this process. It can still enqueue the `entity_access_views` Job. `ENTITY_ACCESS_COMBINATION_LIMIT` uses the same message as the Entity Data read path: `access configuration over limit for this subject`.

## 8. `validate_sql`

Argument: `sql` (the submitted text).

Result:

```json
{
  "entities": ["customers", "orders"],
  "partial_columns": [{ "table_name": "orders", "column": "amount" }]
}
```

The tool writes no Entity Access Log record. It does not open an entity connection. A statement that references no Entity (for example `SELECT 1`) returns empty `entities` and empty `partial_columns`.

## 9. `run_sql`

Arguments: `sql`, optional `max_rows`.

Prepare is §7. The signed context expiry is `max(60, timeout_sec + 30)` seconds, where `timeout_sec` is `entity_query_timeout_sec`. One payload covers every referenced Entity. Policies are ordered by `entity_id`. Grants follow that order, then each policy's own grant order, and the first copy of a grant id is kept. Subject Attribute values are the union, with keys sorted. `rev` maps each referenced `entity_id` to its policy revision, in `entity_id` order. Payload key order stays `sub`, `grants`, `attrs`, `rev`, `exp`, `req`, `kid`. A one-policy token matches the single-policy issuer; that issuer is unchanged. There is no cap on how many Entities one statement may reference. Cost is bounded by the statement timeout and by admission.

Omitted `max_rows` uses `entity_query_max_rows`. Any other value is clamped to `[1, cap]` and the applied value is echoed. `cap` is that System Parameter (seed 1000, range 100–10000). `entity_query_timeout_sec` seed is 30, range 5–300. Neither key replaces `query_timeout_sec` or `query_max_rows`.

Execution uses a reader connection inside admission, not the Entity Data read helper:

1. `BEGIN`, then `SET TRANSACTION READ ONLY`
2. `set_config('app.ctx', token, true)` so the context is local to the transaction
3. `SET LOCAL statement_timeout` to `timeout_sec` × 1000 milliseconds
4. `cursor.execute(sql, binary=True)` on the bound text: one extended-protocol statement, no client parameters, so a second statement is rejected and `%` stays literal
5. `fetchmany(max_rows + 1)`
6. `ROLLBACK` on success and on database failure. If rollback fails after a body error, the body error is the one raised

The `pg_catalog.pg_type` lookup that turns column OIDs into type names runs in that same read-only transaction, before rollback. After five identical executions on one pooled connection, psycopg may `PREPARE`. That text can remain in `pg_prepared_statements` until the connection evicts it. The connection-level prepare threshold is unchanged. The SQL gate still rejects catalog reads, so the caller cannot read that text through `run_sql`.

A statement that references no Entity still executes and writes no Entity Access Log record.

### 9.1 Result

```json
{
  "columns": [{ "name": "region", "type": "text" }],
  "rows": [["north"]],
  "row_count": 1,
  "truncated": false,
  "max_rows": 1000,
  "sql": "SELECT region FROM orders",
  "entities": ["orders"],
  "partial_columns": []
}
```

`sql` is the submitted text. `row_count` is the number of rows returned to the caller, after the extra probe row is dropped. `truncated` is true when the fetch returned more than `max_rows` rows. `columns[].type` is the PostgreSQL type name (`pg_type.typname`; arrays use the catalog name with one leading underscore, such as `_int4`). Those type names pass through the same identifier rewrite as error text (§9.2). An OID with no catalog row is `unknown` before that rewrite.

| Type name | JSON cell |
| --- | --- |
| `int2`, `int4`, `int8` | number |
| `numeric` | decimal string, the exact `format(d, "f")` form |
| `float4`, `float8` | number; NaN, `+Inf`, and `-Inf` are `null` |
| `bool` | boolean |
| `timestamptz` | UTC Instant via `format_instant`; microseconds when the value has a non-zero microsecond, otherwise whole seconds |
| `timestamp`, `date`, `time`, `timetz` | ISO 8601 text (`date` is the calendar date) |
| `json`, `jsonb` | decoded JSON |
| array (`_int4` and the other array type names) | JSON array; each element uses the element type |
| anything else | text |

`null` stays `null`. Actor **Display Timezone** is not applied.

### 9.2 Errors From Execution

`SQLSTATE 57014` and a `QueryCanceled` error are `ENTITY_SQL_TIMEOUT` (message `Entity SQL exceeded the platform timeout`). They are not `PLATFORM_TIMEOUT` and not `QUERY_TIMEOUT`.

`SQLSTATE 53300`, `08001`, and `08004`, and an error whose type is `ConnectionTimeout` or `TooManyConnections`, stay `PLATFORM_CAPACITY_EXCEEDED`. A reader or signer pool checkout timeout stays that same code.

Any other database error is `ENTITY_SQL_FAILED`. The message is the driver's primary message only, then ` (SQLSTATE {state})` when a SQLSTATE is present. Before that suffix, every Profile View identifier and every physical table name is replaced by its Entity `table_name`: bare, quoted, and schema-qualified forms, longer identifiers first. A single leading `_` is an array-type prefix and is kept (`_view` becomes `_table_name`). `name9`, `x_name`, and `__name` do not match a shorter name.

`PLATFORM_CAPACITY_EXCEEDED`, `ADMISSION_CAPACITY_EXCEEDED`, and `ADMISSION_ACTOR_LIMIT_EXCEEDED` write no `sql` log row. A gate rejection and an unknown or invisible name write no log row. No Management Audit Event is written for these reads.

## 10. Problem Codes

Tool failures use §2's envelope. HTTP status below is the `AppError` status; the Streamable HTTP call itself stays successful when the tool returns the envelope. The 401 and 405 gate answers are Problem Details on the HTTP response.

| Problem Code | HTTP status | When |
| --- | --- | --- |
| `ENTITY_SQL_INVALID` | 400 | Gate rejection; `message` is the gate text |
| `ENTITY_SQL_TIMEOUT` | 504 | `run_sql` canceled by `statement_timeout` (`57014`) |
| `ENTITY_SQL_FAILED` | 502 | Database error during `run_sql` that is not a timeout and not `PLATFORM_CAPACITY_EXCEEDED`; `message` includes the SQLSTATE when one is present |
| `ENTITY_NOT_FOUND` | 404 | Unknown or invisible `table_name`, same message |
| `ENTITY_DEPRECATED` | 422 | Deprecated Entity |
| `ENTITY_NOT_SERVING` | 422 | No serving head |
| `ENTITY_ACCESS_PENDING` | 503 | Views do not match the policy revision, or the combination view is still being generated |
| `ENTITY_ACCESS_COMBINATION_LIMIT` | 409 | Combination above `max_profile_combinations` |
| `ENTITY_ROW_NOT_FOUND` | 404 | `get_row` row missing or not visible |
| `REQUEST_INVALID` | 422 | `narrow`, query bounds, dictionary attribute, `search_entities` input, or other request-shape failures shared with the Entity Data API |
| `ENTITY_INDEX_NOT_READY` | 409 | `search_entities` while the Entity index is not ready on the current generation |
| `ENTITY_SEARCH_EMBED_FAILED` | 503 | `search_entities` query embed failed or returned no usable vector; the message names no provider body |
| `MODEL_SERVICE_NOT_IN_USE` | 409 | `search_entities` with no in-use embedding service |
| `MODEL_SERVICE_CLOSED` | 409 | `search_entities` while the embedding purpose is closed |
| `MODEL_SERVICE_ENDPOINT_MISSING` | 409 | `search_entities` while the in-use service has no URL |
| `MODEL_SERVICE_GENERATION_MISMATCH` | 409 | Embedding generation changed during `search_entities` |
| `MODEL_SERVICE_CONTROL_REVISION_MISMATCH` | 409 | Embedding control revision changed during `search_entities` |
| `AUTH_FORBIDDEN` | 403 | Authenticated caller lacks `entity:data_read` |
| `AUTH_UNAUTHENTICATED` | 401 | HTTP gate only |
| `HTTP_METHOD_NOT_ALLOWED` | 405 | HTTP gate only, after authentication |
| `PLATFORM_CAPACITY_EXCEEDED` | 503 | Reader or signer pool checkout timeout, or SQLSTATE `53300`, `08001`, or `08004`, or `ConnectionTimeout` / `TooManyConnections`; no `sql` log row |
| `ADMISSION_CAPACITY_EXCEEDED` | 503 | Admission pool full; no `sql` log row |
| `ADMISSION_ACTOR_LIMIT_EXCEEDED` | 429 | This User's admission share is full; no `sql` log row |
| `MCP_ERROR` | — | Exception that is not an `AppError` |

`ENTITY_SQL_TIMEOUT` is only this host's `run_sql` cancel. Entity Data API statement cancel remains `PLATFORM_TIMEOUT`. Source Controlled Query and Metadata MCP `run_sql` timeout remain `QUERY_TIMEOUT`.

## 11. Audit

`describe_entity` and `list_dictionary_codes` append one Entity Access Log record with verb `schema`, the same record the Entity Data schema verb writes, including the PAT id.

`get_row` and `query_rows` append one record with verb `get` or `query`. The record carries the PAT id and the calling request id.

`run_sql` appends one record per referenced Entity, all with the same `request_id`, the same PAT id, verb `sql`, that Entity's effective grant ids, Profile View name, and policy revision, the statement's returned `row_count` (null when the statement failed), the outcome code (`ok` or the Problem Code), the duration, `sql_sha256` (SHA-256 hex of the UTF-8 bytes of the submitted SQL), and `statement_summary` (the submitted SQL truncated to 200 characters). Non-SQL verbs store null in both SQL columns.

`validate_sql` writes nothing. A gate rejection, an unknown or invisible name, a statement that references no Entity, `PLATFORM_CAPACITY_EXCEEDED`, and an admission rejection write no `sql` record. `list_entities` and `search_entities` write no Entity Access Log record. Reads do not write a Management Audit Event.

## 12. Non-Goals

1. Entity writes, Business Entity authoring, versions, access management, and Dictionary management on this host.
2. The entity Change Log on this host.
3. An HTTP endpoint for Entity SQL, and a Console SQL workbench.
4. A semantic layer, metric definitions, saved queries, or natural-language SQL inside the platform. The caller writes the SQL. `search_entities` ranks definition text; it does not produce SQL.
5. `EXPLAIN` or any other query plan. The gate rejects the command.
6. `narrow` on these tools.
7. Evaluating the `mcp_query` or `export` grant actions. Reachability is an effective `read` grant.
8. A User PAT scope that narrows Entity access.
9. Reading a superseded Entity Version. Only the head has a Profile View.
10. Resolving reference display labels across Entities.
11. Returning or logging bound SQL, Profile View names, or physical table names.

## 13. References

- `docs/business-entity-access.md`
- `docs/business-entity.md`
- `docs/api-contracts-entity-data.md`
- `docs/api-contracts-entity-access.md`
- `docs/api-contracts-entity.md`
- `docs/api-contracts-metadata-mcp.md`
- `docs/business-system-parameters.md`
- `docs/conventions-errors.md`
- `docs/env.md`
- `docs/glossary.md`
