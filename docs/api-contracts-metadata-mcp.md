# refraq API Contracts: Metadata MCP Tool Surface

## 1. Purpose

Defines the MCP tool face for the metadata foundation. Tools call the same domain services and **Permission** checks as HTTP APIs.

The product port is MCP revision **2026-07-28 Streamable HTTP** at the Console-origin path `/mcp`. Auth is **User PAT** in the HTTP `Authorization: Bearer` header only. Tool arguments do not include `authorization`. Session cookies are not MCP credentials. There is no OAuth discovery document and no well-known metadata.

`GET /mcp/catalog` on the API process accepts a Session or a User PAT and no extra Permission. It is the cropped Metadata tool list for the Metadata endpoint. The Console surface is `/console/mcp/metadata`. The overview `/console/mcp` only distinguishes the two endpoints. This catalog is not the Entity catalog and is not an MCP connection.

Business rules: `docs/business-metadata.md` §6.1 and §12.

Legacy external `dbmeta` tool names are **reference only**; refraq owns normative names below. Tool arguments that identify Sources, objects, or columns use **locator keys** (not surrogate ids). Clients that still require a 2025-era `initialize` / `Mcp-Session-Id` handshake are out of scope.

## 2. Cross-Cutting Rules

- Tool failures are **not** HTTP Problem Details. Shape: `{ "error": { "code": "<Problem Code>", "message": "..." } }`. Human text stays `message` (not `detail`). JSON-RPC protocol `error.code` is an integer and is not a Problem Code. Shared identity with HTTP: [`docs/conventions-errors.md`](conventions-errors.md)
- Missing, invalid, or cookie-only credentials on `/mcp` → **HTTP 401** (`AUTH_UNAUTHENTICATED`), for every method. The request does not enter `server/discover`, `tools/list`, or `tools/call`
- `/mcp` accepts **POST** only. After authentication, any other method (including GET and DELETE) is **HTTP 405** (`HTTP_METHOD_NOT_ALLOWED`) with `Allow: POST`. The server does not open a listening stream and does not push server-initiated messages
- Authenticated but lacking permission on a tool that was still invoked → tool error mapped from `403` with required permission named when practical
- `tools/list` (and `GET /mcp/catalog`) return only tools the caller's Role can invoke, in catalog order, with `ttlMs` / `cacheScope: "private"` on the protocol list. Input schemas do not contain `authorization`
- Every catalog tool object includes `execution` with value `read` or `write`, beside `name`, `permission`, and `description`. `tools/list` copies that same value onto the tool as `_meta["io.refraq/execution"]`. Absent `_meta`, an absent key, or any other value is not `read`. `readOnlyHint` is not this class. The Metadata writes are `set_object_semantics`, `set_column_semantics`, `upsert_join`, `patch_join`, `reject_join`, `restore_join`, `upsert_joins`, and `delete_join`. Every other Metadata tool is `read`, including `run_sql`. `read` does not mean the tool skips audit
- Mutations write management audit events
- No tool returns Source plaintext secrets or PAT secrets
- Locator formats: `src/{engine|kind}/{source_key}`, `obj/…/{schema}/{object_type}/{name}`, `col/…/column/{column_name}`
- Tools use the PAT User. A locator on a Source the caller has no level on uses the same not-found code as an unknown locator (`SOURCE_NOT_FOUND`, `CATALOG_OBJECT_NOT_FOUND`, `CATALOG_COLUMN_NOT_FOUND`, or `CATALOG_JOIN_NOT_FOUND` for that tool). A level without the tool's key is `AUTH_FORBIDDEN`. `search_sources` requires Role `sources:read` and returns Sources where the caller holds `sources:read`, using the projected Source shape. It does not add identity rows for `sources:access_manage`. `search_objects` and `search_columns` rank only over Sources where the caller holds `metadata:read`. An explicit `source_locator_key` the caller cannot open is `SOURCE_NOT_FOUND` before the page is built. HTTP Catalog Search of an invisible `source_id` is an empty page (`docs/api-contracts-metadata.md` §6)
- Semantics and join writes need a level that allows `metadata:write` (`steward` or `maintainer`) and Role `metadata:write`. `run_sql` needs `viewer` and Role `query:run`. `enrich_semantics` returns the locator header and its static body when the caller cannot read the object. Any other preload failure still includes the exception text in that prompt
- Open-ended join paths stay inside the start Source's graph. The tool calls the visibility check before lookup
- Catalog column payloads omit `normalized_type`. There is no Type Mapping tool. Agents use native `data_type` (ADR 0024).
- **Instants** in tool JSON match HTTP: outbound UTC `Z` via `format_instant`. Actor **Display Timezone** is not applied to MCP Instant strings (Console-only formatting). Agents may read `display_timezone` from Current User / Account profile and format locally if needed.
- Admission for new tools (ADR 0036): Metadata MCP is the agent inquiry and living-registry face. Do not add (1) operations, Job, or Scheduled Task observe/mutate tools, (2) a read-only tool the agent cannot start from locators already on this face, (3) a second aggregate that only renames `get_object`, (4) tools that write ADR 0015-removed fields, or (5) Business Entity tools. Entity data tools and Entity SQL are the Entity MCP endpoint (`docs/api-contracts-entity-mcp.md`). They are not tools on this host. Cheaper projections of `get_object` are admitted.
- Server `instructions` ship on initialize / `server/discover`. Scene `prompts` (`lookup_business`, `analyze_object`, `explore_join_path`, `enrich_semantics`) activate reasoning and do not prescribe tool order. Prompt bodies follow the admitted field set (ADR 0015).

## 3. Structure (read)

| Tool | Permission | Purpose |
| --- | --- | --- |
| `search_sources` | `sources:read` | Search/list Sources the caller can `sources:read` (`query_text`, `limit` default **50** max **200**, `offset`). No identity rows for `sources:access_manage` |
| `get_source` | `sources:read` | Source detail by `source_locator_key` (projected `access`) |
| `list_objects` | `metadata:read` | Catalog Objects under a Source locator (`q`, `object_type`, `business_semantics_ready`, `limit`, `offset`) |
| `get_object` | `metadata:read` | Aggregate: object + columns + DDL + object semantics by `object_locator_key` (columns omit `normalized_type`; **no** `foreign_keys` / `indexes` — structure graph is HTTP detail or join tools) |
| `get_object_semantics` | `metadata:read` | Object-level admitted semantics only (no columns, no DDL) |
| `get_object_columns` | `metadata:read` | Columns + column semantics (no DDL; omit `normalized_type`) |
| `get_object_ddl` | `metadata:read` | Stored `ddl` and `has_definition` |

`list_objects` is the Per-Source object list (same summary projection as HTTP). Optional `q` is a literal substring of schema, technical name, or `business_name`. Optional `business_semantics_ready` is `true` | `false`. This tool has no `include_absent` argument; tombstones are included. Items omit columns, foreign keys, indexes, and DDL.

## 4. Semantics

| Tool | Permission | Purpose |
| --- | --- | --- |
| `set_object_semantics` | `metadata:write` | Incremental object semantics write (`semantic_source=mcp`) |
| `set_column_semantics` | `metadata:write` | Batch column semantics under one object locator |
| `list_semantics_changes` | `metadata:read` | **Semantics Change** Offset Page for an object locator |

Object semantics read is `get_object` or `get_object_semantics`. Write discipline: fill gaps; do not invent; persist `open_questions` when evidence is weak. Applied writes append **Semantics Change**. `list_semantics_changes` pages that ledger for an object locator. `semantic_source` is set to `mcp`. Field-level protection is deferred (ADR 0014). MCP adapters strip `null`, blank strings, and empty collections before calling the shared write service — agents cannot clear existing semantics via MCP in this phase (ADR 0018; HTTP Console/API use present-null to clear). Column batch responses include `skipped_columns` for `invalid_column_name` / `no_changes`. Writable fields match HTTP semantics PATCH (no `field_kind`; no `model_routing_hint` — not delivered this phase; none of the fields removed by ADR 0015 or ADR 0064).

`set_object_semantics` does **not** accept `time_semantics`, `status_semantics`, `relation_summary`, `confidence`, or `business_domain_code`. Agents record time/status meaning on each relevant column via `business_description` (and optional free-text `column_semantics.semantic_type` / `enum_catalog` — closed vocabulary deferred, ADR 0016) instead of electing one primary time or status column, and record object relationships as join edges with evidence. `business_primary_key` names that do not exist on the object are rejected with `SEMANTIC_COLUMN_UNKNOWN`.

`set_column_semantics` request: `{ object_locator_key, columns: [{ column_name, …fields }] }`.
Response: `{ updated_count, requested_count, skipped_columns }`.

## 5. Joins

| Tool | Permission | Purpose |
| --- | --- | --- |
| `list_joins` | `metadata:read` | Joins for an object locator (`limit`, `offset`; **Offset Page**) |
| `upsert_join` | `metadata:write` | Create a single edge (**Join Change** attester `mcp`); duplicate pair refused |
| `upsert_joins` | `metadata:write` | Batch create; asserted known pairs skipped; rejected pairs reported; evidence required |
| `patch_join` | `metadata:write` | Amend evidence/kind/expression; does not change first attester or `created_by_user_id` (delete eligibility unchanged) |
| `reject_join` | `metadata:write` | **Join Rejection** by join id |
| `restore_join` | `metadata:write` | Lift **Join Rejection** |
| `delete_join` | `metadata:write` | Remove a human-created, non-rejected edge by join id; automatic (including rejected automatic) → `JOIN_DELETE_AUTOMATIC` first, then rejected human → `JOIN_REJECTED`; does not stop automatic re-detection (use `reject_join`) |
| `find_join_path` | `metadata:read` | Path lookup from start locator (optional `target_locator_key` or `query_text`) |

`list_joins` args: object locator plus `limit` (default **50**, max **200**) and `offset` (default **0**). Result is the same **Offset Page** as HTTP `GET /objects/{id}/joins`: `{ "items", "total", "limit", "offset" }`. Order: `created_at ASC`, `id ASC`. Rejected rows are included.

`find_join_path` args: `start_locator_key` (required), optional `target_locator_key`, optional `query_text`, `max_hops` (1–5), `top_targets`.
`query_text` ranks objects already reachable from start within `max_hops` (vector complete state or lexical process state on that set). Explicit `target_locator_key` still walks the shortest path and does not rank, and it may point to another Source when the caller can read both ends. Both omitted → graph exploration of the same reachable set (at most `max_hops`), which stays inside the start Source graph.
Returns `paths_found`, per-target `path_summary` / `hops`, `direct_joins` when start is a column and `max_hops=1` (including `query_text` mode), optional `reason` when no usable path is available (e.g. `TARGET_UNREACHABLE`), and `rank_mode` (`vector` | `lexical`) when `query_text` is set and `target_locator_key` is omitted (`null` otherwise). A serving-time embed or neighbor failure is the same Problem Code as Catalog Search. A start that cannot expand is `JOIN_PATH_UNAVAILABLE` in every mode. Rejected rows are omitted.

`upsert_joins` returns `created_count`, `already_known_count`, `rejected_count`, `skipped_count`, `skipped_joins` (missing endpoints), and `items`. Asserted known pairs are skipped, not overwritten. Rejected pairs increment `rejected_count` and appear in `items` with `is_rejected` (including `id`); they are not overwritten and not restored. To re-assert, call `restore_join`; to change evidence after restore, call `patch_join`. Single `upsert_join` on a rejected pair still returns `JOIN_REJECTED`.

## 6. Search (Depth)

| Tool | Permission | Purpose |
| --- | --- | --- |
| `search_objects` | `metadata:read` | Cross-Source object search |
| `search_columns` | `metadata:read` | Cross-Source column search |

Args align with HTTP search: `query_text` **required and non-empty** after strip for both object and column search; optional source/object filters, `limit`/`offset`. Missing, empty, or whitespace-only `query_text` is `CATALOG_SEARCH_QUERY_REQUIRED` (same Problem Code as HTTP `400`). Ranking is the Catalog Search path (vector complete state when an embedding **Model Service** is in use, open, and ready; otherwise lexical process state — ADR 0043 / 0039). SQL executes the lexical ladder (ADR 0041) without changing same-tier order (`COLLATE "C"`). `source_locator_key` and `object_type` bind both paths. The tool payload is a **Top-K Read**: `items` / `limit` / `offset` / `rank_mode` (`vector` or `lexical`) / `truncated`. No `total`. If the query embedding call fails or exceeds the model API timeout, the tool error is `CATALOG_SEARCH_EMBED_FAILED`. Neighbor-score failure other than platform time is `CATALOG_SEARCH_NEIGHBOR_FAILED`. An empty neighbor list is a successful empty vector page. A platform `statement_timeout` during neighbor SQL is `PLATFORM_TIMEOUT`, not a lexical page. Semantic neighbors are `k` store rows, not a process-local full scan.

Tool-error codes for process overload and platform time (same identity as HTTP, ADR 0040 / 0045): `PLATFORM_CAPACITY_EXCEEDED`, `PLATFORM_TIMEOUT`, `ADMISSION_CAPACITY_EXCEEDED`, `ADMISSION_ACTOR_LIMIT_EXCEEDED`. MCP HTTP `503` from the process load-shed is Problem Details on the Streamable HTTP request; an admission reject during `run_sql` or vector Search is the tool-error envelope; a platform `statement_timeout` during a tool is `PLATFORM_TIMEOUT` in the tool-error envelope.

## 7. Controlled Query

| Tool | Permission | Purpose |
| --- | --- | --- |
| `run_sql` | `query:run` | Read-only single statement via `source_locator_key` |

Guards match `docs/api-contracts-metadata.md` §7 (same defaults/caps/timeouts and per-attempt audit). `execution` for this tool is `read`. Tool annotation `readOnlyHint` is advisory only: it does not replace platform guards and it is not the `execution` class. Admission uses the MCP process pool (ADR 0045): `ADMISSION_CAPACITY_EXCEEDED` / `ADMISSION_ACTOR_LIMIT_EXCEEDED` in the tool-error envelope when the pool or this actor's share is full.

There is **no** MCP Catalog Sample tool; agents peek via `run_sql`. HTTP Catalog Sample remains `POST /objects/{id}/sample` (`catalog:sample`).

## 8. HTTP Catalog (`GET /mcp/catalog`)

Purpose: an authenticated caller reads the cropped Metadata tool list and the public path for the Metadata endpoint. The Console surface is `/console/mcp/metadata`. The overview `/console/mcp` only distinguishes the two endpoints. This catalog is not the Entity catalog and is not an MCP connection.

Auth: Session cookie **or** User PAT, same as other protected APIs. No extra Permission beyond authentication.

Success `200`:

```json
{
  "public_path": "/mcp",
  "tools": [
    {
      "name": "search_sources",
      "permission": "sources:read",
      "description": "Search/list Sources (sources:read).",
      "execution": "read"
    }
  ]
}
```

`public_path` is the Console-origin path the operator copies. The browser builds `{origin}{public_path}`. An empty `tools` array is valid.

## 9. Non-Goals

- Identity rows on `search_sources` for `sources:access_manage` (HTTP `GET /sources` is the surface that adds them)
- A PAT `scopes` value that narrows Source access
- A Type Mapping tool, or a Source Mirror tool
- Arbitrary shell / file tools
- Client credential management
- Data Product catalog tools
- Business Entity tools on this Metadata MCP (`list_entities`, `get_entity`, or writes). Entity data tools and Entity SQL are the Entity MCP endpoint (`docs/api-contracts-entity-mcp.md`)
- Dual-read fallback into external `dbmeta`
- Job / Scheduled Task observe or mutate (`get_job`, list, logs, cancel, enqueue)
