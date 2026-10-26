# refraq Business Rules: Tags

## 1. Scope

This document defines the platform **Tag** vocabulary: one shared record for a word, the display-name rule, the Tag **Console Module**, authorization, and the audit of vocabulary changes.

It does not define attaching a Tag to a **Business Entity** or a **Data Channel**, list filters, bulk edits, usage lists, or **Saved Filter**.

Related boundaries:

- HTTP: `docs/api-contracts-tags.md`
- Terminology: `docs/glossary.md`
- Console record form: `docs/ui-console-record-form.md`
- Permissions: `docs/business-login-auth.md` §8
- Navigation: `docs/business-management-console.md` §3.2 and §3.5

## 2. Vocabulary

A **Tag** is a platform-scoped vocabulary record. It is not a **Business Entity**, not a **Dictionary**, not a **User Group**, and not a Catalog Object category.

One word is one Tag. The name lives only on the Tag. Renaming that record changes the name everywhere the record is shown.

A Tag has an opaque id (`tag_` plus 12 lowercase hex characters), a display name, an optional description, and creation and update instants. It has no color, owner, folder, or certificate.

`updated_at` changes when the display name or the description changes.

## 3. Names And Descriptions

The display name stored and shown is the precis-i18n `NicknameCasePreserved` enforcement of the operator's input. Uniqueness is the `NicknameCaseMapped` enforcement of that same input. The comparison form is not a response field. Both profiles are used as shipped: callers pass no case mapping, and the browser and SQL do not carry a second copy of the profile.

`precis-i18n` is declared with `==` in `backend/requirements.txt`. Changing that pin can merge or split existing names, so the pin is part of the rule.

Enforcement that fails, a result of zero code points, or a display name longer than 64 code points is rejected. A raw name longer than 256 code points is rejected and is not passed to enforcement. Length is counted in Unicode code points.

Creating or renaming from the Tag module when another Tag already holds the comparison form is refused. The stored display name is unchanged. Renaming a Tag to a different spelling of its own comparison form succeeds and updates the display name.

Two creates of the same comparison form that overlap result in one Tag. The create that loses is refused. Neither response is an internal error.

Names the profile accepts are accepted, including Han characters, mixed script, hyphens, internal spaces, and emoji the profile allows. No second character whitelist is added. Strings that differ under this profile stay different Tags, including `Straße` and `STRASSE`.

Description is a single-line plain string. It is trimmed at the ends, not run through the nickname profile, and not unique. Empty after trim means absent. Present, it is at most 200 code points and contains no character in Unicode category `Cc`. A raw value longer than 256 code points, or any other violation, is rejected.

## 4. Tag Module

The Console Module id is `tags`. Its navigation group id is `tags`, and it is that group's only module. `group_order` is 26 and `module_order` is 25, so the group renders between the Entity group and the Channel group. A caller who cannot list Tags sees the Entity group followed by the Channel group.

Routes are `/console/tags`, `/console/tags/new`, `/console/tags/:id`, and `/console/tags/:id/edit`. The module is a record authoring surface (`docs/ui-console-record-form.md`). The icon key is `tag`.

The list is newest first (`created_at` descending, then `id` descending) and can be searched by the stored display name. Show and edit record a recent visit the same way other record modules do. The command palette lists at most five Tags, and only for a caller who may open the module.

Detail reports `entity_count` and `channel_count`. The list omits those counts. Attaching a Tag is out of scope for this document, so a Tag that nothing carries reports 0 and 0. Deleting that Tag succeeds.

The browser blocks a name that is empty after trim. It does not copy the nickname profile or the length caps. The server remains authoritative.

## 5. Authorization

The permission catalog includes `tag:read` and `tag:write`. They are not implied by `entity:read`, `entity:write`, `channel:read`, or `channel:write`. The seeded `operator` role does not receive them. A custom role stores the keys it is given. The system role `super_admin` has them by identity, as it has every catalog key.

The module lists and shows with `tag:read` and creates, edits, and deletes with `tag:write`. `GET /tags` is also allowed for `entity:read` or `channel:read`. Detail, create, rename, and delete are not included in that allowance.

## 6. Audit

A management audit event is written for a committed Tag create, update, or delete. The event uses resource type `tag`, action `create`, `update`, or `delete`, and result `success`. Detail carries the stored display name. A patch that changes nothing writes no event. A refused create, rename, description, or delete writes no event.

## 7. Non-Goals

1. Attaching Tags to a Business Entity or a Data Channel, including inline create and a delete refusal while a Tag is in use.
2. List filters, bulk add, and bulk remove.
3. Usage lists that name records.
4. Saved Filters.
5. Seeding `tag:read` or `tag:write` onto the operator role.
6. MCP tools, Entity Data API fields, and Channel run-context fields.

## 8. References

- `docs/api-contracts-tags.md`
- `docs/glossary.md`
- `docs/ui-console-record-form.md`
- `docs/business-login-auth.md`
- `docs/business-management-console.md`
