# refraq UI: Management Console Content Width

## Purpose

Design-language rules for Management Console page layout: the shared page-header convention, how pages use horizontal space in the AppShell main area, and how paged list tables occupy remaining vertical space.

Related: `docs/business-management-console.md`, `docs/development.md`, `docs/conventions-pagination.md`.

## Page Header

1. **Page title, description, and page-level actions render only through `PageChrome`** (`frontend/src/components/layout/PageChrome.tsx`). Pages must not hand-roll header rows or place page actions inside the content area.
2. **`SectionHeader` is the single title/description/actions layout primitive** (`frontend/src/components/layout/SectionHeader.tsx`). `PageChrome` composes it at heading order 2; embedded page sections (for example User PAT inside Account Center) use it at heading order 4.
3. **Header action buttons use `size="sm"`** so every page header reads the same height. Page-level create (navigate to `/new` or open a create modal) goes through `CreateListAction`. Destructive confirmations go through `ConfirmActionModal` (optional `children` for extra fields such as a cascade checkbox).
4. **Content toolbars hold filter controls only** (source selectors, search inputs, a clear-filters control). Action buttons belong to the header `actions` slot, not to toolbars. A clear-filters control is a filter control: it belongs in the toolbar and is visible only when a filter is off its default.
5. **Paged Offset Page tables use `ListTable`** (`frontend/src/components/display/ListTable.tsx`), which binds a paged-list session to status, retry, and `ListPager` (`frontend/src/components/display/ListPager.tsx`). Count text always renders; page numbers render only when there is more than one page. Do not hand-roll prev/next buttons or a second pager for an **Offset Page**. Pages do not set `Table` appearance props on the list table.
6. **Breadcrumb labels from module `label_key` (Refine `meta.label`) are i18n keys and are translated at display** (`frontend/src/components/layout/PageBreadcrumb.tsx`). The trail landmark uses `layout.breadcrumb`. `href` is a navigation affordance only; it does not decide whether a label is translated. Catalog identity keeps keys; the display layer resolves them.
7. **A breadcrumb trail renders only when it has at least two items and a navigable ancestor** (an item whose `href` comes from a list route). Identity-only pages with no `routes.list` (Account Center) and list pages with a single resource crumb do not show a trail.

## List Tables

Paged **Offset Page** tables render through `ListTable`. `ListTable` owns one visual contract:

1. **Sticky header inside a bounded `Table.ScrollContainer`.** Vertical overflow stays on the table body so column labels stick and `ListPager` remains in view. Horizontal overflow is allowed when columns exceed the main area.
2. **Loading is in-table.** The first fetch with no rows renders row-shaped skeletons inside the real header so column widths do not jump. A later fetch that still has rows dims the body; it does not replace the table. The table body sets `aria-busy` while loading or refreshing; `ListPager` disables page changes for that window and announces the count with `aria-live="polite"`.
3. **Empty, no-match, and error are in-table status rows.** The empty gate reads `total`, not `items.length`. A vacant filter result is a no-match state, distinct from a vacant collection. A fetch error with no rows to keep is an in-table error row with retry; a fetch error that still has rows keeps the table. HTTP Offset Page lists use `useConsolePagedList` (`frontend/src/hooks/useConsolePagedList.ts`), which passes `onError` so Refine toasts a later failure. Local adapters use `usePagedList` without `onError`. Default copy is `common.empty` / `common.noMatch`; a page may override either string.
4. **`ListPager` is composed by `ListTable`.** Count text always renders; page numbers render only when there is more than one page (`docs/conventions-pagination.md`).
5. **Parents own available block size; `ListTable` owns scrolling and pager placement.** Console surfaces are a few stable frames: AppShell header plus a main frame that receives remaining viewport space; `PageChrome` keeps breadcrumb/title/toolbar at intrinsic height and passes leftover space to content; `ListTable` is a flex column whose `Table.ScrollContainer` consumes that leftover and whose pager stays outside the scroll region. Remaining-space frames that wrap a list in `FillColumn` (`frontend/src/components/layout/FillColumn.tsx`) so the table fills the region after intrinsic siblings are: full-page Offset Page lists, the catalog Joins tab, the catalog Columns tab, and the schedule-jobs modal body (already a remaining-space column; it does not wrap again). Horizontal `minWidth` is independent of this vertical contract; the schedule-jobs modal passes a narrower value.

**Form surfaces vs remaining-space frames.** Account Center and Platform Settings are form pages: intrinsic sections stack under `PageChrome`, and `PageChrome` `overflow: auto` is the page scroller when content exceeds the viewport. User PAT inside Account Center stays an Offset Page table (`ListTable`) but is a section of that form page — it does not consume leftover viewport height and must not wrap the whole Account page (or the PAT section alone) in `FillColumn`. Do not judge Account success by “pager pinned in the first viewport.” Account Center may reserve a narrow in-page table of contents column beside the form stack. That column sticks inside the `PageChrome` scroller, highlights the job in view, and calls `scrollIntoView` without writing a URL hash or History entry. It is not `PageChrome` `actions` and is not Console Navigation.

`usePagedList` owns fetch generation, reset-to-page-1, and `listPresentationOf` (`frontend/src/lib/list-state.ts`). HTTP Console lists call `useConsolePagedList`, which binds Refine notification through `onError`. Pages keep writing their own header and body cells; `ListTable` is not a column DSL. Feature mutation errors stay in the feature.

**Offset Page callers** (must use `ListTable`): Catalog Browse, Users, Users pending federated identities (Users tab subtable), Roles, Identity Providers, Sources, Jobs, Schedules, Business Domains, Type Mappings, User PAT (Account Center), Source-scoped schedules, Structure Diff list, catalog Joins tab, catalog Columns tab (in-memory Offset Page adapter over the object payload; not an HTTP Offset Page), schedule-jobs modal.

**Not Offset Page collection lists** (do not migrate to `ListTable`): Catalog Sample (row peek), Structure Diff detail (static tables).

## Click Copy

Click-to-copy is a Console platform capability. Surfaces write through `copyText` (`frontend/src/lib/copy-text.ts`). Success and failure toasts use only `common.copy.success` / `common.copy.failed` as the `message` — no surface title, no description, no exception text. Failure means the current environment cannot write to the clipboard; the operator copies the already-visible content by hand. New click-to-copy must not call `navigator.clipboard.writeText` directly and must not invent its own success or failure copy.

## Principles

1. **Section / page content containers are full width** of the main area (`width: 100%` of available content). Do **not** put a section-level or page-level form `max-width` on outer stacks, forms, or settings shells.
2. **Internal width is owned by internal elements** (controls, field groups, tables). Outer layout only handles sectioning and spacing; it does not shrink the whole form for the controls.
3. **Settings surfaces share the same content rail as list pages** (Users, Sources, Jobs, and similar). Avoid a narrow form column with a large empty band on the right.
4. **Vertical size is remaining space from the parent frame**, not a per-table guess of chrome height. A child fills its frame; it does not compute `100vh - N`. The schedule-jobs modal may size its **content frame** with `calc(100dvh - var(--modal-y-offset) * 2)` so the modal body is a determined remaining-space column; that is a frame exception, not a per-table height.

## Applies To

- Account Center (profile, password, embedded User PAT)
- Platform Settings
- Other Console pages under `frontend/src/` that use `PageChrome` in the main shell

## Allowed

- Full-width section stacks and tables in the main area
- Optional `max-width` (or equivalent) on an individual control or field wrapper when that control needs it later
- Horizontal scroll on dense tables when columns exceed the main area
- Bounded vertical scroll on paged tables via `Table.ScrollContainer`, so the header sticks and `ListPager` stays in view
- `ListPager` as the table footer for Offset Page lists, composed by `ListTable`
- `FillColumn` as the remaining-space wrapper for embedded lists (`gap` and an optional `minHeight` floor; not a Flex alias)
- An in-page Account table of contents that sticks inside `PageChrome`, highlights the job in view, and calls `scrollIntoView` without writing a hash (not `PageChrome` `actions`, not Console Navigation)
- Click-to-copy through `copyText` with `common.copy.success` / `common.copy.failed` as the toast `message`

## Forbidden

1. Wrapping an entire Account / Settings page (or form + table together) in a fixed or section-level form `maw` / `max-width`
2. Centering the main content as a narrow marketing-style card band inside the shell
3. Using outer form width to “fix” for missing field-level width rules
4. A second list pager beside `ListPager` on an Offset Page table
5. Replacing a paged table with a page-level skeleton on filter or page changes
6. Setting `Table` appearance props (`striped`, `highlightOnHover`, `withTableBorder`, spacing) on a `ListTable` body
7. Hand-rolling loading / empty / error / pager branches for an Offset Page collection list outside `ListTable`
8. Per-caller `calc(100vh - N)` / `calc(100dvh - N)` **table** heights, named height presets (`page` / `embedded` / `modal`), or a public `maxHeight` escape hatch on `ListTable` (modal **content frame** calc in Principle 4 is allowed)
9. Treating `FillColumn` as a Flex alias (appearance, `direction`, or `flex` overrides)
10. Wrapping an entire Account / Settings form page (or form sections + embedded PAT together) in `FillColumn`
11. Putting Account Center sections (profile, User PAT, Metadata MCP) on the Console navbar, or writing a URL hash / History entry for Account sections
12. Calling `navigator.clipboard.writeText` from a click-to-copy control, or inventing surface-specific copy success/failure strings

## Implementation Notes

- Prefer removing outer `maw` on page roots over introducing a shared form-width constant.
- Mantine inputs default to filling their parent; that is acceptable until a control-level width system exists.
- Do not invent a second page max-width “rail” for settings unless product IA splits settings onto a separate surface.
- `Table.ScrollContainer` uses native overflow (`type="native"`) so `stickyHeader` sticks inside the bounded body. Its height is 100% of the `ListTable` flex region, not a viewport remainder. The outer frame is on that scrollport, not `withTableBorder` on the table, so overflow does not clip the chrome.
- Permission gates (ACL loading / forbidden) stay outside `ListTable`. Surrounding filters, join forms, and page chrome stay outside `ListTable`.
- Flex frames use `min-height: 0` so leftover space can shrink; do not add measurement hooks unless CSS flex sizing fails an observed browser case.
- `FillColumn` locks column direction, `flex: 1`, and a specified `minHeight` (default 0). An optional floor is part of that shrink contract, not a Flex escape hatch.
- On form pages, `PageChrome` may scroll; that is expected. On remaining-space list frames and the Joins and Columns tabs, the table scroller owns vertical overflow and `PageChrome` should not become a second scroller.
