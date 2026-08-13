# refraq API Contracts: Metadata MCP Tool Surface

## 1. Purpose

Defines the MCP tool face for the metadata foundation. Tools call the same domain services and **Permission** checks as HTTP APIs.

Auth: **User PAT** Bearer (primary for agents); Session only where the MCP transport supports cookie forwarding.
Business rules: `docs/business-metadata.md`. Locator addressing: `docs/adr/0012-locator-addressing.md`.

Legacy external `dbmeta` tool names are **reference only**; refraq owns normative names below. Tool arguments that identify Sources, objects, or columns use **locator keys** (not surrogate ids).

## 2. Cross-Cutting Rules

- Tool failures are **not** HTTP Problem Details. Shape: `{ "error": { "code": "<Problem Code>", "message": "..." } }`. Human text stays `message` (not `detail`). JSON-RPC protocol `error.code` is an integer and is not a Problem Code. Shared identity with HTTP: [`docs/conventions-errors.md`](conventions-errors.md)
- Missing/invalid auth → tool error mapped from `401`
- Authenticated but lacking permission → mapped from `403` with required permission named when practical
- Mutations write management audit events
- No tool returns Source plaintext secrets or PAT secrets
- Locator formats: `src/{engine|kind}/{source_key}`, `obj/…/{schema}/{object_type}/{name}`, `col/…/column/{column_name}`
- Catalog column payloads omit `normalized_type`. There is no Type Mapping tool. Agents use native `data_type` (ADR 0024).
- **Instants** in tool JSON match HTTP: outbound UTC `Z` via `format_instant`. Actor **Display Timezone** is not applied to MCP Instant strings (Console-only formatting). Agents may read `display_timezone` from Current User / Account profile and format locally if needed.

## 3. Structure (read)

| Tool | Permission | Purpose |
| --- | --- | --- |
| `search_sources` | `sources:read` | Search/list Sources (`query_text`, `limit`, `offset`) |
| `get_source` | `sources:read` | Source detail by `source_locator_key` (projected `access`) |
| `list_objects` | `metadata:read` | Catalog Objects under a Source locator (`q`, `object_type`, `limit`, `offset`) |
| `get_object` | `metadata:read` | Object + columns by `object_locator_key` (includes semantics when present; columns omit `normalized_type`) |
| `get_object_ddl` | `metadata:read` | DDL when present |
| `enqueue_structure_job` | `jobs:run` | Enqueue structure Job for Source locator |
| `get_job` | `jobs:run` | Job by id (status, input, summary, nullable `result`) |

## 4. Semantics

| Tool | Permission | Purpose |
| --- | --- | --- |
| `get_object_semantics` | `metadata:read` | Compact object semantics by locator |
| `inspect_object` | `metadata:read` | Object semantics + columns aggregate |
| `set_object_semantics` | `metadata:write` | Incremental object semantics write (`semantic_source=mcp`) |
| `set_column_semantics` | `metadata:write` | Batch column semantics under one object locator |
| `list_business_domains` | `metadata:read` | List Business Domains |
| `create_business_domain` | `metadata:write` | Create a Business Domain (`code`, `name`, `description?`) |

Write discipline: fill gaps; do not invent; persist `open_questions` when evidence is weak. `semantic_source` is set to `mcp`. Field-level protection is deferred (ADR 0014). MCP adapters strip `null`, blank strings, and empty collections before calling the shared write service — agents cannot clear existing semantics via MCP in this phase (ADR 0018; HTTP Console/API use present-null to clear). Column batch responses include `skipped_columns` for `invalid_column_name` / `no_changes`. Writable fields match HTTP semantics PATCH (no `field_kind`; no `model_routing_hint` — not delivered this phase; none of the fields removed by ADR 0015).

`set_object_semantics` does **not** accept `time_semantics`, `status_semantics`, `relation_summary`, or `confidence`. Agents record time/status meaning on each relevant column via `business_description` (and optional free-text `column_semantics.semantic_type` / `enum_catalog` — closed vocabulary deferred, ADR 0016) instead of electing one primary time or status column, and record object relationships as join edges with evidence. `business_primary_key` names that do not exist on the object are rejected with `SEMANTIC_COLUMN_UNKNOWN`. Object writes accept `business_domain_code`; unknown codes → `BUSINESS_DOMAIN_UNKNOWN`.

Business Domain delete is **Console HTTP only** (not exposed on MCP) so agents do not trigger `BUSINESS_DOMAIN_IN_USE` without an operator surface (ADR 0017).

`set_column_semantics` request: `{ object_locator_key, columns: [{ column_name, …fields }] }`.
Response: `{ updated_count, requested_count, skipped_columns }`.

## 5. Joins

| Tool | Permission | Purpose |
| --- | --- | --- |
| `list_joins` | `metadata:read` | Joins for an object locator |
| `upsert_join` | `metadata:write` | Single edge (`origin=mcp`) |
| `upsert_joins` | `metadata:write` | Batch edges; all same Source; evidence required |
| `delete_join` | `metadata:write` | Remove edge by join id |
| `find_join_path` | `metadata:read` | Path lookup from start locator |

`find_join_path` args: `start_locator_key` (required), optional `target_locator_key`, `max_hops` (1–5), `top_targets`.
Returns `paths_found`, per-target `path_summary` / `hops`, `direct_joins` when start is a column and `max_hops=1`, and optional `reason` when no usable path is available (e.g. `TARGET_UNREACHABLE`).

`upsert_joins` returns `created_count`, `already_known_count`, `skipped_count`, `skipped_joins` (missing endpoints), and `items`.

## 6. Search (Depth)

| Tool | Permission | Purpose |
| --- | --- | --- |
| `search_objects` | `metadata:read` | Cross-Source object search |
| `search_columns` | `metadata:read` | Cross-Source column search |

Args align with HTTP search: `query_text` **required and non-empty** for both object and column search; optional source/object filters, `limit`/`offset`.

## 7. Controlled Query

| Tool | Permission | Purpose |
| --- | --- | --- |
| `run_sql` | `query:run` | Read-only single statement via `source_locator_key` |

Guards match `docs/api-contracts-metadata.md` §7 (same defaults/caps/timeouts and per-attempt audit). Tool annotation `readOnlyHint` is advisory only and does not replace platform guards.

There is **no** MCP Catalog Sample tool; agents peek via `run_sql`. HTTP Catalog Sample remains `POST /objects/{id}/sample` (`catalog:sample`).

## 8. Out Of Scope Tools

- Arbitrary shell / file tools
- Client credential management
- Data Product catalog tools
- Dual-read fallback into external `dbmeta`
