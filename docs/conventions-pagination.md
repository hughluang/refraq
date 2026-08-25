# refraq Pagination Conventions

Authoritative list-envelope contract for HTTP and MCP collection reads.
Hard trade-offs: [`docs/adr/0029-offset-page-as-platform-list-envelope.md`](adr/0029-offset-page-as-platform-list-envelope.md).
Domain terms: [`docs/glossary.md`](glossary.md).

## 1. Scope

This document defines how collection reads are paged: the **Offset Page** envelope, total ordering, the **Cursor Page** admission rule, Whole-Set Read exemptions, MCP mirroring, and Console list-footer rules.

It does not define Job/log retention, Catalog Sample row peeks, or Controlled Query row caps.

Related boundaries:

- HTTP failures: `docs/conventions-errors.md`
- Instants: `docs/conventions-time.md`
- Console list chrome: `docs/ui-console-layout.md`
- Per-endpoint defaults and filters: the matching `docs/api-contracts-*.md`

## 2. Offset Page

Every HTTP collection list that pages uses this envelope. The envelope is always complete; omitting `limit` / `offset` applies the endpoint defaults and still returns all four fields.

```json
{
  "items": [],
  "total": 0,
  "limit": 50,
  "offset": 0
}
```

| Field | Rule |
| --- | --- |
| `items` | The page of resources |
| `total` | Count of the **filtered** set (not the unfiltered table) |
| `limit` | Page size actually applied (echo of the request, after defaulting) |
| `offset` | Skip actually applied (echo of the request, after defaulting) |

Query parameters:

| Param | Rule |
| --- | --- |
| `limit` | Integer ≥ 1; endpoint declares default and max |
| `offset` | Integer ≥ 0; default 0 |

The convention owns param names, envelope keys, the ordering guarantee, and the requirement that every Offset Page endpoint declare a max `limit`. Default and max `limit` stay per endpoint and are documented in that endpoint's API contract.

`total` is a real count of the filtered set (`COUNT(*)` on the same predicates, or `len` of the filtered in-memory set). Do not compute `total` by loading every row. Do not rename it `total_count`.

Pagination bounds the **response**. It does not bound the table. A clock-appended stream (Jobs) still grows; retention is a separate mechanism.

An `offset` past the end of the filtered set is still `200`. The envelope returns empty `items` and the same `total`; it is not a `404` and it is not an error.

## 3. Total Ordering

An Offset Page requires a deterministic total order. `offset > 0` is undefined without it.

Newest-first lists order by `created_at DESC, id DESC` (or the equivalent durable primary key). Name-ordered lists include an `id` tiebreaker. Catalog search keeps its documented rank order, then a locator/`id` tiebreaker.

## 4. Cursor Page

A **Cursor Page** is `{ "items": [...], "limit": L, "next_cursor": null | "…" }`. It is admitted only for an immutable, append-only, high-volume event log that has no jump-to-page requirement.

Today that is exactly `GET /audit/events`. New endpoints must not choose a Cursor Page without an ADR that names the admission.

## 5. Whole-Set Read

A Whole-Set Read is not a page. It is a composite configuration document bounded by platform definition, not by data volume. Keys are not `items`:

| Endpoint | Envelope key |
| --- | --- |
| `GET /console/navigation` | `groups` |
| `GET /console/module-identities` | `modules` |
| `GET /permissions` | `items` (fixed Permission catalog) |
| `GET /settings` | `parameters` |

Do not rewrite these as Offset Pages.

## 6. MCP

MCP list tools that correspond to an Offset Page HTTP list use the same fields: `limit`, `offset`, and a result carrying `items`, `total`, `limit`, `offset`. They do not invent a second envelope.

MCP list tools clamp out-of-range `limit` / `offset` to the documented default and max and echo the applied values. HTTP Offset Page lists reject the same inputs with `422 REQUEST_INVALID`.

Catalog Sample and Controlled Query are row peeks, not collection lists. They keep `has_more` (heuristic) and do not add `total`.

## 7. Console

Paged Management Console tables use one footer: `ListPager` (`frontend/src/components/display/ListPager.tsx`), composed by `ListTable` (`docs/ui-console-layout.md`). Count text always renders; page numbers render only when there is more than one page. `ListTable` disables paging while the first page is loading or existing rows are refreshing. Filter controls stay in the content toolbar. Do not hand-roll prev/next buttons for an Offset Page. Catalog Columns uses the same Console module through an in-memory Offset Page adapter over the object payload; it is not an HTTP Offset Page.

Pickers that need a closed option set (role Select, Source Select) fetch one page at that list's documented max `limit`. They are not a second envelope.

## 8. Forbidden

1. A collection list that pages with `{ "items": [...] }` only.
2. Returning `total` / `limit` / `offset` only “when pagination params are used”.
3. A third envelope (`has_more` on a collection list, `total_count`, cursor without §4 admission).
4. Newest-first Offset Pages ordered by `created_at` without an `id` (or equivalent) tiebreaker.
5. Computing Offset Page `total` by materializing every filtered row.
6. A default `limit` with no documented max cap.
7. Treating page bounds as Job/log retention.
8. A new collection list that returns `{items}` only (Whole-Set Reads in §5 are the exception).

## 9. Implementation Entry

- HTTP params and envelope: `backend.core.pagination` (`page_params`, `PageBounds`, `OffsetPage`). Named catalog/source bounds live next to `page_params`; HTTP and MCP import the same names. MCP clamps out of range; HTTP rejects with `422`.
- Console: `frontend/src/lib/pagination.ts`, `frontend/src/lib/paged-list-session.ts`, `frontend/src/lib/list-state.ts`, `frontend/src/hooks/usePagedList.ts`, `frontend/src/hooks/useConsolePagedList.ts` (HTTP lists; binds Refine notification through `onError`), `frontend/src/components/display/ListTable.tsx` (binds the session; composes `ListPager`). A `resetDeps` change reloads from page 1 even when the session is already on page 1 (a local adapter with a stable `fetch` relies on that).
- See [`docs/modules.md`](modules.md) and [`docs/backend-layout.md`](backend-layout.md).

## 10. Non-Goals

- Job or log retention / pruning.
- Catalog Sample and Controlled Query row peeks (`has_more`, `REFRAQ_QUERY_MAX_ROWS`).
- Migrating `GET /audit/events` off Cursor Page.
- A global page-size number imposed on every endpoint.
