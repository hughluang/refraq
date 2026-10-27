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

`entities`, `dictionaries`, `tags`, `channels`, `webhooks`, and `email-accounts` are in class. Out of class includes `roles`, `catalog`, `settings`, `jobs`, `sources`, `identity-providers`, `type-mappings`, `model-services`, `users`, `branding`, and `account`.

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

Show, missing write permission, an identity key that is immutable after create, and a field that is temporarily not authorable on an otherwise editable form all use the same field component in **display mode** (`editable={false}`). Edit mode (`editable={true}`) is the matching input. Display mode follows the value's shape (plain text, option label, yes/no, or segmented label). It is not a `disabled` or `readOnly` input. There is no third presentation (`locked`, `disabled`, or `readOnly`) for a field the actor cannot change.

Create, show, and edit still share one layout. The branch is inside the field component. Do not replace that layout with a second page tree.

Facts that are not form fields (timestamps, job ids) stay on `DisplayField` (`frontend/README.md`).

### 3.2 Header action clusters

Page-level actions render only in `PageChrome` `actions` through `HeaderActions` (`frontend/src/components/layout/HeaderActions.tsx`). The slot sits on the right of the title row (`docs/ui-console-layout.md`). `HeaderActions` partitions buttons into up to three clusters and separates non-empty clusters with a vertical divider. An empty cluster omits itself and its divider. Every header button uses `size="sm"`. At most one button is the filled primary. Mark it with `HeaderAction` `primary` (that wrapper also sets `size="sm"` and `variant="filled"`). A button that omits `primary` still counts as primary when its variant is omitted or `"filled"`.

1. **Navigation** — back to list, refresh. Chrome, not record CRUD and not domain lifecycle. Present on show and edit. Absent on create: cancel returns to the list.
2. **Domain lifecycle** — publish, open version, deprecate. Present on show and edit when permission and domain lifecycle allow. Absent on create. A channel header Run belongs to this cluster: it is present only on edit, uses `variant="light"`, and is not a second filled primary. Show does not start a run.
3. **Standard record** (rightmost) — cancel, save/create, edit, delete.

The filled primary is Save when the definition form is on screen (create and edit). On edit, Save is that filled primary. On show, Publish is the filled primary when it is shown. Open version and edit are `light`. Delete and deprecate are `light` red. A channel header Run is `variant="light"` in the lifecycle cluster, present only on edit, and is not a second filled primary.

### 3.3 Tag control

A Tag control is not a definition field. On create it submits with the create body. On show and edit it may save with its own button. That save must not dirty the definition form and must not submit with the definition save. On create and on the control's own save, the text in the tag field is part of the submitted set. A definition save does not include it. Show of a deprecated record, and any mode without write permission, renders the control in display mode. This allowance is only the Tag control. Show does not gain a general in-place edit.

## 4. Forbidden

1. A second layout for show versus edit (or create).
2. In-place field writes on show. The Tag control in §3.3 is the one exception, and it is not a definition field.
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
