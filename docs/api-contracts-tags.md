# refraq API Contracts: Tags

## 1. Purpose

This document defines the Tag collection HTTP: list, create, read, rename, describe, and delete.

It does not define attaching a Tag to a **Business Entity** or a **Data Channel**, list filters by Tag, bulk edits, usage lists, or **Saved Filter**.

Related boundaries:

- Vocabulary rules: `docs/business-tags.md`
- Errors: `docs/conventions-errors.md`
- Transport: `docs/api-contracts-auth.md` §2
- Permissions: `docs/api-contracts-roles.md` §3

## 2. Shared Shapes

List items:

```json
{
  "id": "tag_0123456789ab",
  "name": "Finance",
  "description": null,
  "created_at": "2026-01-01T00:00:00Z",
  "updated_at": "2026-01-01T00:00:00Z"
}
```

Create, read, and patch return `{ "tag": <detail> }`. Detail is the list item plus `entity_count` and `channel_count`.

`id` is `tag_` plus 12 lowercase hex characters. Any other string is an unknown id, not a validation error.

`entity_count` and `channel_count` count records that carry the Tag. Attaching a Tag is out of scope for this document, so both are `0`. The list omits the counts.

Unknown JSON fields are `422` `REQUEST_INVALID`.

## 3. Name And Description

`name` is required on create. The stored `name` is the precis-i18n `NicknameCasePreserved` enforcement of the input. Uniqueness uses `NicknameCaseMapped` on that same input. The profiles are the ones shipped with the pinned `precis-i18n` release in `backend/requirements.txt`. Callers pass no case mapping.

A raw name longer than 256 code points is `422` `TAG_NAME_INVALID` and is not passed to the profile. Enforcement that fails, an empty result, or a display name longer than 64 code points is the same code. Length is Unicode code points.

`ＦＩＮＡＮＣＥ` stores `FINANCE`. `finance  team` stores `finance team`. `Straße` and `STRASSE` are two Tags.

A create or rename whose comparison form belongs to another Tag is `409` `TAG_NAME_CONFLICT`. The stored display name is unchanged. A rename to another spelling of the same Tag's own comparison form is `200` and updates `name`.

Two creates of one comparison form that overlap yield one `201` and the rest `409`. Neither is `500`.

`description` is optional. It is trimmed at the ends and is not run through the nickname profile. Empty after trim is stored as `null`. A present description is at most 200 code points and contains no Unicode category `Cc`. A raw value longer than 256 code points, or any other violation, is `422` `TAG_DESCRIPTION_INVALID`. The name is not changed by that refusal.

## 4. `GET /tags`

Purpose: list Tags newest first (`created_at` descending, then `id` descending).

- Permission: `tag:read`, or `entity:read`, or `channel:read`. None of those is `403` `AUTH_FORBIDDEN`.

Query: `limit` (default 50, max 200), `offset` (default 0), optional `q`. `limit` above 200 is `422` `REQUEST_INVALID`.

`q` is a case-insensitive literal substring of the stored display name. A blank or whitespace-only `q` is the same as omitting it. `%` and `_` match themselves.

### Response: `200`

```json
{
  "items": [],
  "total": 0,
  "limit": 50,
  "offset": 0
}
```

`total` counts the filtered set.

## 5. `POST /tags`

Purpose: create one Tag.

- Permission: `tag:write`. `tag:read` alone is `403` `AUTH_FORBIDDEN`.

### Request

```json
{ "name": "ＦＩＮＡＮＣＥ", "description": "  Shared word  " }
```

`description` may be omitted.

### Response: `201`

```json
{
  "tag": {
    "id": "tag_0123456789ab",
    "name": "FINANCE",
    "description": "Shared word",
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z",
    "entity_count": 0,
    "channel_count": 0
  }
}
```

A committed create writes one management audit event: resource type `tag`, action `create`, result `success`, detail `{ "name": "<stored display name>" }`.

## 6. `GET /tags/{tag_id}`

Purpose: read one Tag.

- Permission: `tag:read`. `entity:read` or `channel:read` without `tag:read` is `403` `AUTH_FORBIDDEN`.

### Response: `200`

`{ "tag": <detail> }`.

Unknown id: `404` `TAG_NOT_FOUND`.

## 7. `PATCH /tags/{tag_id}`

Purpose: rename a Tag, set its description, or clear its description.

- Permission: `tag:write`.

### Request

Omitted fields stay. `description: null` or a blank string clears the description. `name: null` is `422` `TAG_NAME_INVALID`.

```json
{ "name": "Finance", "description": null }
```

### Response: `200`

`{ "tag": <detail> }`.

`updated_at` changes only when the display name or the description changes. A patch that changes neither returns the same Tag and writes no audit event. A committed change writes one event with action `update` and detail `{ "name": "<stored display name>" }`.

Unknown id: `404` `TAG_NOT_FOUND`. A conflict or an invalid field leaves the stored Tag unchanged and writes no audit event.

## 8. `DELETE /tags/{tag_id}`

Purpose: delete one Tag that nothing carries.

- Permission: `tag:write`.

### Response: `204`

Empty body. A second delete of the same id is `404` `TAG_NOT_FOUND` and writes no further audit event. The successful delete writes one event with action `delete` and detail `{ "name": "<stored display name>" }`.

A refusal while a record carries the Tag is out of scope for this document.

## 9. Non-Goals

1. Attaching a Tag to a Business Entity or a Data Channel.
2. `tag_id` on Entity or Channel lists, bulk add, and bulk remove.
3. A usage list of record names.
4. Saved Filters.
5. A published `tags.api` assignment surface.

## 10. References

- `docs/business-tags.md`
- `docs/conventions-errors.md`
- `docs/api-contracts-auth.md`
- `docs/api-contracts-roles.md`
