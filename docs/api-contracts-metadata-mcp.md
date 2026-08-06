# refraq API Contracts: Metadata MCP Tool Surface

## 1. Purpose

Defines the MCP tool face for the metadata foundation. Tools call the same domain services and **Permission** checks as HTTP APIs.

Auth: **User PAT** Bearer (primary for agents); Session only where the MCP transport supports cookie forwarding.
Business rules: `docs/business-metadata.md`.

Legacy external `dbmeta` tool names are **reference only**; refraq owns normative names below.

## 2. Cross-Cutting Rules

- Missing/invalid auth → tool error mapped from `401`
- Authenticated but lacking permission → mapped from `403` with required permission named when practical
- Mutations write management audit events
- No tool returns Connection plaintext secrets or PAT secrets

## 3. Slice A — Structure (read)

| Tool | Permission | Purpose |
| --- | --- | --- |
| `search_sources` | `sources:read` | Search/list Sources |
| `get_source` | `sources:read` | Source detail |
| `list_connections` | `sources:read` | The Source's Connection if any (0 or 1; no secrets) |
| `list_objects` | `metadata:read` | Catalog Objects under a Source |
| `get_object` | `metadata:read` | Object + columns |
| `get_object_ddl` | `metadata:read` | DDL when present |
| `enqueue_structure_job` | `jobs:run` | Enqueue structure Job (Source facade) |
| `get_job` | `jobs:run` | Job status |

## 4. Slice B — Semantics

| Tool | Permission | Purpose |
| --- | --- | --- |
| `get_object_semantics` | `metadata:read` | Read object/column business fields |
| `set_object_semantics` | `metadata:write` | Write object business fields |
| `set_column_semantics` | `metadata:write` | Write column business fields |

Write discipline: fill gaps; do not invent; use open_questions when evidence is weak (payload field optional).

## 5. Slice C — Joins

| Tool | Permission | Purpose |
| --- | --- | --- |
| `list_joins` | `metadata:read` | Joins for an object |
| `upsert_join` | `metadata:write` | Upsert edge with evidence |
| `delete_join` | `metadata:write` | Remove edge |

## 6. Slice D — Controlled Query

| Tool | Permission | Purpose |
| --- | --- | --- |
| `run_sql` | `query:run` | Read-only single statement via Connection id |

Guards match `docs/api-contracts-metadata.md` §6.

## 7. Out Of Scope Tools

- Arbitrary shell / file tools
- Client credential management
- Data Product catalog tools
- Dual-read fallback into external `dbmeta`
