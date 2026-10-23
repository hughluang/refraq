# refraq UI: Management Console Content Width

## Purpose

Design-language rules for Management Console page layout: the shared page-header convention, how pages use horizontal space in the AppShell main area, and how paged list tables occupy remaining vertical space.

Related: `docs/business-management-console.md`, `docs/development.md`, `docs/conventions-pagination.md`, `docs/ui-console-record-form.md`, `docs/ui-console-interaction.md`.

## Page Header

1. **`PageChrome` has two regions** (`frontend/src/components/layout/PageChrome.tsx`). The header region does not scroll. It contains the breadcrumb (when the trail renders), a title row, an optional description, an optional `toolbar` slot, and an optional `tabs` slot. The title row places the title, optional `titleSlot`, and `titleExtra` on the left and page actions on the right. Actions wrap below the title when the row runs out of space. An empty `actions` slot omits that side. Title extras are compact status chips beside the heading, not a second header row or a page-level Alert. Pages must not hand-roll header rows or place page actions inside the content area. Save and Cancel for a page-level form sit in that header slot, not in a form footer. On a record authoring surface, cluster membership is `docs/ui-console-record-form.md`.
2. **The content region is the only page scroller when `fill` is false.** When `fill` is true the content region does not scroll, and the table scroller owns overflow. `data-page-scroll` marks the content region.
3. **The page title is the page's only `h1`.** Visual size stays the h2 heading token (`Title` `size="h2"`), not heading order. `data-page-heading` and `tabIndex={-1}` stay on that title. An empty `title` uses the matched module's translated `label_key`, then `fallbackTitle` when the route has no module. The document title on a list route is `{module label} · {brand}`. On a show, edit, or create route, or when `recordTitle` is set, it is `{record title} · {module label} · {brand}`. `recordTitle` is that record title; otherwise a page `title` that differs from the module label is the record title. Brand comes from Site Branding. `SectionHeader` (`frontend/src/components/layout/SectionHeader.tsx`) remains the title layout for the page heading and the actions layout for **embedded** sections. Embedded sections use a lower heading level (order 4) with actions beside the title. Optional `titleExtra` sits beside the title. An optional `titleSlot` replaces the heading element when a page edits that title in place; `title` stays the fallback heading, and `titleExtra` remains in the same row.
4. **`status` selects `ready`, `loading`, `error`, `forbidden`, or `notFound`.** `ready` is the default. Non-ready states render in the content region and the header stays. Loading uses `PageBodySkeleton`. Error uses `PageError` and accepts `onRetry`, `errorMessage`, and `requestId`. Forbidden accepts `forbiddenReason` and reuses `ForbiddenState`. Not-found reuses `NotFoundState`. Permission gates pass this status on the page frame. Shell-level identity failure and console-access refusal stay outside the frame.
5. **The tabs slot is URL-backed through the `tab` query.** Pass `PageTabs` (`frontend/src/components/layout/consoleTabs.tsx`) or a `tabs` array of `{ value, label, panel }`. `useConsoleTab` reads the query from Next search params and writes it with `history.replaceState` (no history entry). An unknown value shows the first tab. Each panel mounts on first visit and stays mounted. A show or edit route records a recent visit for the command palette and the console home. The stored href is the current path and query unless the page sets `recent.href`.
6. **Header action buttons use `size="sm"`** so every page header reads the same height. `HeaderActions` (`frontend/src/components/layout/HeaderActions.tsx`) groups `navigation`, `lifecycle`, and `standard` slots, drops empty clusters, and separates the rest with a vertical divider. At most one button is the filled primary. Designate it with `HeaderAction` `primary`. A button that omits `primary` still counts as primary when its variant is omitted or `"filled"`. Page-level create (navigate to `/new` or open a create modal) goes through `CreateListAction`. State-changing verbs declare a safety class and run through `useConsoleMutation` (`docs/ui-console-interaction.md`). A confirm dialog that must collect an extra field, such as a cascade checkbox or a password, may compose `ConfirmActionModal` directly.
7. **Content toolbars hold filter controls only** (source selectors, search inputs, a clear-filters control) and render in the `toolbar` slot. Action buttons belong to the header `actions` slot, not to toolbars. A clear-filters control is a filter control: it belongs in the toolbar and is visible only when search or a filter is off its default. `ListToolbar` (`frontend/src/components/display/ListToolbar.tsx`) is that toolbar for an **Offset Page** list bound to `useListQuery`. Search applies 300 ms after typing pauses, immediately on Enter, and clears on Escape. Select and multi-select options show translated labels. `/` focuses the search when focus is outside an editable field and outside the channel canvas (a `.react-flow` ancestor of the focused element).
8. **Paged Offset Page tables use `ListTable`** (`frontend/src/components/display/ListTable.tsx`), which binds a paged-list session to status, retry, and `ListPager` (`frontend/src/components/display/ListPager.tsx`). Count text always renders; page numbers render only when there is more than one page. Do not hand-roll prev/next buttons or a second pager for an **Offset Page**. Pages do not set `Table` appearance props on the list table.
9. **Breadcrumb labels from module `label_key` (Refine `meta.label`) are i18n keys and are translated at display** (`frontend/src/components/layout/PageBreadcrumb.tsx`). The trail landmark uses `layout.breadcrumb`. `href` is a navigation affordance only; it does not decide whether a label is translated. Catalog identity keeps keys; the display layer resolves them.
10. **A breadcrumb trail renders only when it has at least two items and a navigable ancestor** (an item whose `href` comes from a list route). Identity-only pages with no `routes.list` (Account Center) and list pages with a single resource crumb do not show a trail. Breadcrumb links are console links.

## Console Shell

The shell wraps every authenticated `/console/*` visit. Page content scrolls inside the main region; the shell itself does not.

1. **Side navigation has two desktop widths.** Expanded shows the module icon, the translated label, and group labels. Rail shows the icon only, separates groups with dividers, and shows the module label in a tooltip. A toggle at the bottom of the navigation, and the `[` key when focus is not in an editable field, switch the width. The choice is stored in the browser.
2. **The navigation list is its own scroll region.** The shell header and the width toggle stay fixed.
3. **The active item is the module whose list route is the longest prefix of the current path.** That item carries `aria-current="page"`. A clicked item shows a pending state until the route commits.
4. **Below the `sm` breakpoint the navigation is an overlay.** It closes when the pathname changes and when the operator presses Escape. Escape returns focus to the menu button.
5. **Header order is menu button (narrow only), brand mark, command palette trigger, color scheme, language, then the account menu.** The brand mark follows Site Branding and sits on the surface in both schemes. A skip-to-content link is the first focusable control and targets the main region.
6. **A console navigation that stays pending for more than 150 ms shows a top progress bar** until that navigation commits.
7. **The console segment loading boundary renders a page-frame skeleton inside the shell.** A render error keeps the shell and offers retry plus a link to the module list (or the console home when the path has no list route). An unregistered `/console/*` path renders a page-not-found state inside the shell. That state is not a permission refusal. A permission refusal names the missing access and stays a separate state. Neither is a framework 404.
8. **After a pathname change, focus moves to the page heading** (`data-page-heading` on the `PageChrome` title) and the page content scrolls to the top. A query-only change does not move focus or scroll.
9. **Browser Back and Forward are not intercepted.** The App Router exposes no cancellable event for them.

## List Tables

Paged **Offset Page** tables render through `ListTable`. `ListTable` owns one visual contract:

1. **Sticky header inside a bounded `Table.ScrollContainer`.** Vertical overflow stays on the table body so column labels stick and `ListPager` remains in view. Horizontal overflow is allowed when columns exceed the main area.
2. **Loading is in-table.** The first fetch with no rows renders row-shaped skeletons inside the real header so column widths do not jump. A later fetch that still has rows keeps those rows. The body dims (`opacity` 0.6) only after the refresh has lasted 200 ms (`FEEDBACK_DELAY_MS` in `frontend/src/theme/tokens.ts`). A refresh that finishes sooner does not dim. The table body sets `aria-busy` while loading or refreshing; `ListPager` disables page changes for that window and announces the count with `aria-live="polite"`.
3. **Empty, no-match, and error are in-table status rows.** The empty gate reads `total`, not `items.length`. A vacant filter result is a no-match state, distinct from a vacant collection. A fetch error with no rows to keep is an in-table error row with retry; a fetch error that still has rows keeps the table. HTTP Offset Page lists use `useConsolePagedList` (`frontend/src/hooks/useConsolePagedList.ts`), which passes `onError` so Refine toasts a later failure. Local adapters use `usePagedList` without `onError`. Default copy is `common.empty` / `common.noMatch`; a page may override either string. `EmptyState` shows an icon, that one next-step sentence, and an optional primary action (the module `CreateListAction` when create is permitted), passed as `emptyAction`. A no-match row offers Clear filters when `onClearFilters` is set.
4. **`ListPager` is composed by `ListTable`.** Count text always renders; page numbers render only when there is more than one page (`docs/conventions-pagination.md`).
5. **Parents own available block size; `ListTable` owns scrolling and pager placement.** Console surfaces are a few stable frames: AppShell header plus a main frame that receives remaining viewport space; `PageChrome` keeps breadcrumb/actions/title/toolbar at intrinsic height and passes leftover space to content; `ListTable` is a flex column whose `Table.ScrollContainer` consumes that leftover and whose pager stays outside the scroll region. Remaining-space frames that wrap a list in `FillColumn` (`frontend/src/components/layout/FillColumn.tsx`) so the table fills the region after intrinsic siblings are: full-page Offset Page lists, the catalog Joins tab, the catalog Columns tab, and the schedule-jobs modal body (already a remaining-space column; it does not wrap again). Horizontal `minWidth` is independent of this vertical contract; the schedule-jobs modal passes a narrower value.
6. **Search, filters, and page live in the URL.** `useListQuery` (`frontend/src/hooks/useListQuery.ts`) reads them from `useSearchParams` and writes them with `history.replaceState`, so a change does not add a history entry. Defaults are omitted. Changing search or a filter resets the page to 1. Reload and a shared link restore the view. `usePagedList` takes an optional `page` and `onPageChange`; when they are set, the pager reads and writes that URL page. Lists that omit them keep an internal page.
7. **Row actions use `RowActions`.** Up to two verbs render inline at a fixed size and light variant; a destructive verb sets the danger color. Further verbs sit in an overflow menu whose trigger is named "More actions for {record}". Each verb declares a safety class (`docs/ui-console-interaction.md`). Missing permission hides the verb. A verb that is present but unavailable in the record's current state stays visible, disabled, with a tooltip that states the reason. The record's primary cell is a `ConsoleLink` to show or edit. The row is not a click target.
8. **Secondary collections use the same status rows.** A collection inside a drawer, tab, or section renders through `ListTable`: **Channel Run** history, **Channel Version** lists, **Entity Version** lists, **Business Entity** access tables, **Dictionary** usages, and **User Group** members. Static display tables stay outside `ListTable`: Catalog Sample (source-row peek), Structure Diff detail (change breakdown), the attribute editor and the entity version attribute snapshot (definition grids), dictionary entry fields, the MCP tool catalog, and the access preview sample. The Business Entity data browser keeps its keyset pager and uses the same empty, no-match, and error rows.

**Form surfaces vs remaining-space frames.** Account Center and Platform Settings are form pages: intrinsic sections stack in the `PageChrome` content region, and that region is the page scroller when content exceeds the viewport. The header region does not scroll. User PAT inside Account Center stays an Offset Page table (`ListTable`) but is a section of that form page — it does not consume leftover viewport height and must not wrap the whole Account page (or the PAT section alone) in `FillColumn`. Do not judge Account success by “pager pinned in the first viewport.” Account Center may reserve a narrow in-page table of contents column beside the form stack. That column sticks inside the content scroller, highlights the job in view, and calls `scrollIntoView` without writing a URL hash or History entry. It is not `PageChrome` `actions` and is not Console Navigation.

`usePagedList` owns fetch generation, reset-to-page-1, and `listPresentationOf` (`frontend/src/lib/list-state.ts`). When `page` and `onPageChange` are set, reset-to-page-1 notifies that callback and the page value is the URL page. HTTP Console lists call `useConsolePagedList`, which binds Refine notification through `onError`. Pages keep writing their own header and body cells; `ListTable` is not a column DSL. Feature mutation errors stay in the feature.

**Offset Page callers** (must use `ListTable`): Catalog Browse, Users, Users pending federated identities (Users tab subtable), Roles, Identity Providers, Sources, Jobs, Schedules, Type Mappings, User PAT (Account Center), Source-scoped schedules, Structure Diff list, catalog Joins tab, catalog Columns tab (in-memory Offset Page adapter over the object payload; not an HTTP Offset Page), schedule-jobs modal.

**Not Offset Page collection lists** (do not migrate to `ListTable`): Catalog Sample (row peek), Structure Diff detail (static tables), the attribute editor, the entity version attribute snapshot, dictionary entry fields, the MCP tool catalog, and the access preview sample.

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
13. A history entry for a list search, filter, or page change (`pushState` or a router push of that query)
14. Navigating by clicking the table row instead of the record's primary link

## Implementation Notes

- Prefer removing outer `maw` on page roots over introducing a shared form-width constant.
- Mantine inputs default to filling their parent; that is acceptable until a control-level width system exists.
- Do not invent a second page max-width “rail” for settings unless product IA splits settings onto a separate surface.
- `Table.ScrollContainer` uses native overflow (`type="native"`) so `stickyHeader` sticks inside the bounded body. Its height is 100% of the `ListTable` flex region, not a viewport remainder. The outer frame is on that scrollport, not `withTableBorder` on the table, so overflow does not clip the chrome.
- Permission gates (ACL loading / forbidden) stay outside `ListTable`. Surrounding filters, join forms, and page chrome stay outside `ListTable`.
- Flex frames use `min-height: 0` so leftover space can shrink; do not add measurement hooks unless CSS flex sizing fails an observed browser case.
- `FillColumn` locks column direction, `flex: 1`, and a specified `minHeight` (default 0). An optional floor is part of that shrink contract, not a Flex escape hatch.
- On form pages, the `PageChrome` content region may scroll; that is expected. On remaining-space list frames and the Joins and Columns tabs, the table scroller owns vertical overflow and the content region does not scroll (`fill`).
