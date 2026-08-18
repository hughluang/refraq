# refraq UI: Management Console Content Width

## Purpose

Design-language rules for Management Console page layout: the shared page-header convention and how pages use horizontal space in the AppShell main area.

Related: `docs/business-management-console.md`, `docs/development.md`, `docs/conventions-pagination.md`.

## Page Header

1. **Page title, description, and page-level actions render only through `PageChrome`** (`frontend/src/components/layout/PageChrome.tsx`). Pages must not hand-roll header rows or place page actions inside the content area.
2. **`SectionHeader` is the single title/description/actions layout primitive** (`frontend/src/components/layout/SectionHeader.tsx`). `PageChrome` composes it at heading order 2; embedded page sections (for example User PAT inside Account Center) use it at heading order 4.
3. **Header action buttons use `size="sm"`** so every page header reads the same height.
4. **Content toolbars hold filter controls only** (source selectors, search inputs). Action buttons belong to the header `actions` slot, not to toolbars.
5. **Paged tables use `ListPager`** (`frontend/src/components/display/ListPager.tsx`). Count text always renders; page numbers render only when there is more than one page. Do not hand-roll prev/next buttons or a second pager for an **Offset Page**.

## Principles

1. **Section / page content containers are full width** of the main area (`width: 100%` of available content). Do **not** put a section-level or page-level form `max-width` on outer stacks, forms, or settings shells.
2. **Internal width is owned by internal elements** (controls, field groups, tables). Outer layout only handles sectioning and spacing; it does not shrink the whole form for the controls.
3. **Settings surfaces share the same content rail as list pages** (Users, Sources, Jobs, and similar). Avoid a narrow form column with a large empty band on the right.

## Applies To

- Account Center (profile, password, embedded User PAT)
- Platform Settings
- Other Console pages under `frontend/src/` that use `PageChrome` in the main shell

## Allowed

- Full-width section stacks and tables in the main area
- Optional `max-width` (or equivalent) on an individual control or field wrapper when that control needs it later
- Horizontal scroll on dense tables when columns exceed the main area
- `ListPager` as the table footer for Offset Page lists

## Forbidden

- Wrapping an entire Account / Settings page (or form + table together) in a fixed or section-level form `maw` / `max-width`
- Centering the main content as a narrow marketing-style card band inside the shell
- Using outer form width to “fix” for missing field-level width rules
- A second list pager beside `ListPager` on an Offset Page table

## Implementation Notes

- Prefer removing outer `maw` on page roots over introducing a shared form-width constant.
- Mantine inputs default to filling their parent; that is acceptable until a control-level width system exists.
- Do not invent a second page max-width “rail” for settings unless product IA splits settings onto a separate surface.
