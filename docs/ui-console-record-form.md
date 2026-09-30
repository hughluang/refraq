# refraq UI: Console Record Form

## 1. Purpose

This document defines the Management Console record-form protocol: which **Console Module**s are record authoring surfaces, the duties of the create / show / edit form states, how field writes are gated, and how definition save, standard record verbs, and domain lifecycle verbs share the page header.

It does not define page chrome geometry, list tables, or content width. It does not define when domain lifecycle verbs are legal; those rules stay in the domain business document.

Related boundaries:

- `docs/ui-console-layout.md`
- `docs/business-management-console.md`
- `docs/api-contracts-console.md`
- `docs/business-entity.md`

## 2. Membership

A Console Module is a **record authoring surface** when its catalog routes register **distinct** `create`, `show`, and `edit` paths, and the resource is created by an operator rather than ingested.

Modules that lack that triple are out of class. That includes list-plus-modal authoring, single-route panels, observe-only lists, ingested-object workbenches, and an edit route with no show route.

`entities` and `dictionaries` are in class. Out of class includes `roles`, `catalog`, `settings`, `jobs`, `sources`, `identity-providers`, `business-domains`, `type-mappings`, `model-services`, `users`, `branding`, and `account`.

Record authoring surfaces keep three paths. They do not collapse show and edit onto one URL.

## 3. Form States

Create, show, and edit render **one** layout component. Mode is taken from the route.

| State | Route | Fields | Definition save | Lifecycle header actions |
| --- | --- | --- | --- | --- |
| create | `routes.create` | Writable, including identity keys that become immutable after create | One create request in the header standard cluster | None |
| show | `routes.show` | All authorable fields in display mode | None | Allowed; header lifecycle cluster; still gated by permission and domain lifecycle |
| edit | `routes.edit` | Writable when the actor has the module write permission and domain lifecycle allows authoring | One definition patch in the header standard cluster | Allowed; same gates as show |

A field is writable only when `mode` is `create` or `edit`, the actor has the module write permission, and domain lifecycle allows authoring. Show never writes fields, including when the actor has write permission and the record is unpublished.

Visiting edit when authoring is refused **redirects to show** (keep an in-page tab query if present). The edit URL does not stay up when authoring is refused.

Create success navigates to that record's edit route (optional tab query). Edit save stays on edit and clears dirty.

A domain lifecycle command that is not a field write (publish, open version, deprecate) may appear in the header lifecycle cluster on show and on edit. Delete of a never-published definition is a standard record action in that same header. The row-scoped verb (drop table) stays on the collection row. Publish is disabled while the definition form is dirty or the saved shape is empty.

### 3.1 Controls

Show, missing write permission, an identity key that is immutable after create, and a field that is temporarily not authorable on an otherwise editable form all use the same field component in **display mode** (`editable={false}`). Edit mode (`editable={true}`) is the matching input. Display mode follows the value's shape (plain text, option label, yes/no, segmented label, or a cron phrase). It is not a `disabled` or `readOnly` input. There is no third presentation (`locked`, `disabled`, or `readOnly`) for a field the actor cannot change.

Create, show, and edit still share one layout. The branch is inside the field component. Do not replace that layout with a second page tree.

Facts that are not form fields (timestamps, job ids) stay on `DisplayField` (`frontend/README.md`).

### 3.2 Header action clusters

Page-level actions render only in `PageChrome` `actions` (`docs/ui-console-layout.md`). They partition into up to three clusters, left-aligned on that dedicated row, separated by a vertical divider when more than one cluster is present. An empty cluster omits itself and its divider.

1. **Navigation** — back to list, refresh. Chrome, not record CRUD and not domain lifecycle. Present on show and edit. Absent on create: cancel returns to the list.
2. **Domain lifecycle** — publish, open version, deprecate. Present on show and edit when permission and domain lifecycle allow. Absent on create.
3. **Standard record** (rightmost) — cancel, save/create, edit, delete.

The filled primary is save/create when the definition form is on screen (create/edit). On show, publish is the filled primary when it is shown. Open version and edit are `light`. Delete and deprecate are `light` red. Header action buttons use `size="sm"`.

## 4. Forbidden

1. A second layout for show versus edit (or create).
2. In-place field writes on show.
3. Treating write permission as edit intent on show.
4. Staying on the edit URL when authoring is refused.
5. Splitting definition save across pages or buttons so identity and body are authored on different layouts.
6. Implementing a non-editable field with a `disabled` or `readOnly` input. Show, missing permission, immutable keys, and in-form temporary locks share display mode.
7. A form-footer Cancel/Save row that duplicates header standard actions.
8. Putting the row-scoped verb (drop table) in the page header.

## 5. Non-Goals

1. Applying this protocol to modules that are out of class.
2. Collapsing show and edit onto one path.
3. Page chrome, list tables, and content width.
4. Domain lifecycle rules; those stay in the domain business document.

## 6. References

- `docs/ui-console-layout.md`
- `docs/business-management-console.md`
- `docs/api-contracts-console.md`
- `docs/business-entity.md`
- `docs/glossary.md`
- `frontend/README.md`
