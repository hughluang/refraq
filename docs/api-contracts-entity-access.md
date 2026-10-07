# refraq API Contracts: Entity Access

## 1. Purpose

This document defines the HTTP contract for managing **Entity Access Control** on a **Business Entity** — presentation ladders, **Access Profile**s, **Access Grant**s, **Access Restriction**s, profile copy, and preview as a subject — and the behavior that access control adds to the **Entity Data API** and to Business Entity definition reads: shapes compiled from policy, hidden-column errors, visibility answers, conflicts, the `__withheld` marker, narrowing, and new Problem Codes.

User Groups and Subject Attributes are managed through `docs/api-contracts-users.md`. Business rules live in `docs/business-entity-access.md`.

Related boundaries:

- Access rules: `docs/business-entity-access.md`
- Definition API: `docs/api-contracts-entity.md`
- Entity Data API: `docs/api-contracts-entity-data.md`
- User Groups and Subject Attributes: `docs/api-contracts-users.md`
- Problem Details: `docs/conventions-errors.md`
- **Instant** wire form: `docs/conventions-time.md`
- Terminology: `docs/glossary.md`

## 2. Cross-Cutting Rules

### 2.1 Transport And Permission

Transport, authentication, Problem Details, and `X-Request-ID` follow `docs/api-contracts-entity.md` §2.1. Every endpoint in §4 requires `entity:access_manage`. A caller without it receives `403 AUTH_FORBIDDEN` before the Entity id is resolved. Unknown Entity id is `404 ENTITY_NOT_FOUND`.

### 2.2 Addressing

Management paths address the Entity by opaque `id` under `/entities/{id}/access`. `access` is a definition subresource and belongs to the definition reserved set that is disjoint from the Entity Data API verbs (`docs/api-contracts-entity-data.md` §3.2).

### 2.3 Identifiers

| Resource | Example | Rule |
| --- | --- | --- |
| Attribute | `att_01HZX` | `attribute_id`, stable across versions while the attribute keeps its name |
| Access Profile | `eap_01HZX` | Opaque server-issued id |
| Access Grant | `eag_01HZX` | Opaque server-issued id |
| Access Restriction | `ear_01HZX` | Opaque server-issued id |

### 2.4 Revision

Every successful write in §4 increments the Entity's `policy_revision` in the same transaction and enqueues the view regeneration **Job** (`docs/business-jobs.md`). Responses carry the new `policy_revision`. Data requests on the Entity answer `503 ENTITY_ACCESS_PENDING` until regeneration completes.

### 2.5 Audit

Every successful write in §4 writes one **Management Audit Event** naming the Entity, the resource, and the action. Reads and preview without rows write none.

## 3. Resource Shapes

### 3.1 Subject

```json
{ "type": "role", "id": "role_01HZX", "display_name": "Sales rep", "missing": false }
```

`type` is `user`, `role`, or `group`. Writers send `type` and `id` only. `display_name` and `missing` are read-only; `missing` is true when the subject no longer exists. `type: "user"` names a User id, `type: "role"` a Role id, and `type: "group"` a User Group id. An unknown id on write is `422 ENTITY_ACCESS_INVALID`.

### 3.2 Presentation Ladder

```json
{
  "attribute_id": "att_01HZX",
  "attribute_name": "id_card_no",
  "type": "string",
  "levels": [
    { "key": "clear", "mode": "clear" },
    { "key": "last4", "mode": { "type": "partial", "keep_first": 0, "keep_last": 4 } },
    { "key": "none", "mode": { "type": "null" } }
  ]
}
```

`levels` is ordered most revealing first. The first level is always `{ "key": "clear", "mode": "clear" }`. Level `key` is `[a-z][a-z0-9_]*`, at most 63 characters, unique within the ladder. `mode` is `"clear"` or a mask object `{ "type", …params }` with types and parameters from `docs/business-entity-access.md` §4. A mask the attribute's type does not accept, unknown parameters, or out-of-range parameters are `422 ENTITY_ACCESS_INVALID`. Every head attribute has a ladder; an attribute without authored masks reads as `[clear]`.

### 3.3 Access Profile

```json
{
  "id": "eap_01HZX",
  "entity_id": "ent_01HZX",
  "key": "finance",
  "name": "Finance",
  "description": null,
  "columns": [
    { "attribute_id": "att_01HZA", "attribute_name": "name", "level": "clear" },
    { "attribute_id": "att_01HZB", "attribute_name": "id_card_no", "level": "last4" }
  ],
  "broken": false,
  "broken_reasons": [],
  "created_at": "2026-10-07T00:00:00Z",
  "updated_at": "2026-10-07T00:00:00Z"
}
```

`key` follows the level key rule and is unique within the Entity. `columns` lists head attributes; `attribute_name` is read-only. An `attribute_id` that is not in the head, a duplicate `attribute_id`, or a `level` not in that attribute's ladder is `422 ENTITY_ACCESS_INVALID`. `row_id` is implicit and is not listed. `broken` and `broken_reasons` are derived (`docs/business-entity-access.md` §9.9).

### 3.4 Row Rule

A row rule is the JSON tree in `docs/business-entity-access.md` §8, or `null` for every row. Leaves name attributes by `attribute_id`.

```json
{ "and": [
  { "in": { "attr": "att_01HZC", "subject_attr": "regions" } },
  { "gte": { "attr": "att_01HZD", "value": 50000 } }
] }
```

A rule that fails type checking, names an unknown attribute or Subject Attribute, or exceeds 20 leaves or depth 8 is `422 ENTITY_ACCESS_INVALID`; `detail` names the leaf path and rule.

### 3.5 Access Grant

```json
{
  "id": "eag_01HZX",
  "entity_id": "ent_01HZX",
  "subject": { "type": "role", "id": "role_01HZX", "display_name": "Sales rep", "missing": false },
  "profile_id": "eap_01HZX",
  "row_rule": { "in": { "attr": "att_01HZC", "subject_attr": "regions" } },
  "actions": ["read", "write"],
  "status": "active",
  "valid_until": null,
  "broken": false,
  "broken_reasons": [],
  "warnings": [],
  "created_at": "2026-10-07T00:00:00Z",
  "updated_at": "2026-10-07T00:00:00Z"
}
```

`actions` is a non-empty subset of `read`, `write`, `export`, `mcp_query`; duplicates are one value; `write` without `read` is `422 ENTITY_ACCESS_INVALID`. `status` is `active` or `disabled`. `valid_until` is an **Instant** or `null`. `warnings` is read-only and lists rule leaves that name an attribute outside the grant's profile. `broken`, `broken_reasons`, and `warnings` are not accepted on write.

### 3.6 Access Restriction

```json
{
  "id": "ear_01HZX",
  "entity_id": "ent_01HZX",
  "applies_to": { "mode": "all", "subjects": [] },
  "row_rule": { "ne": { "attr": "att_01HZC", "value": "TEST" } },
  "deny_columns": ["att_01HZE"],
  "ceilings": [{ "attribute_id": "att_01HZB", "level": "last4" }],
  "actions": ["read", "write", "export", "mcp_query"],
  "broken": false,
  "broken_reasons": [],
  "created_at": "2026-10-07T00:00:00Z",
  "updated_at": "2026-10-07T00:00:00Z"
}
```

`applies_to.mode` is `all` (`subjects` empty), `only`, or `except` (`subjects` non-empty, each a §3.1 subject). At least one of `row_rule`, `deny_columns`, or `ceilings` is non-empty. A ceiling level must exist in that attribute's ladder.

### 3.7 Access Summary

```json
{
  "entity_id": "ent_01HZX",
  "head_version_id": "0123456789abcdef",
  "policy_revision": 42,
  "views": {
    "state": "ready",
    "revision": 42,
    "single_profile_views": 3,
    "combinations": 2,
    "combination_limit": 64,
    "subjects_over_limit": 0,
    "latest_job_id": "job_01HZX"
  },
  "ladders": [],
  "profiles": [],
  "grants": [],
  "restrictions": []
}
```

`views.state` is `ready` (views match `policy_revision`), `pending` (regeneration queued or running), or `failed` (the latest regeneration Job failed; data requests stay pending). `head_version_id` is `null` and the lists may still be edited when the Entity has no serving head; ladders and profiles then reference the attributes of the latest published version.

## 4. Management Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/entities/{id}/access` | Access Summary |
| `GET` | `/entities/{id}/access/ladders` | List ladders, head attribute order |
| `PUT` | `/entities/{id}/access/ladders/{attribute_id}` | Replace one ladder |
| `GET` | `/entities/{id}/access/profiles` | List profiles (`key ASC`, `id ASC`) |
| `POST` | `/entities/{id}/access/profiles` | Create a profile |
| `POST` | `/entities/{id}/access/profiles/copy` | Copy a profile from another Entity |
| `GET` | `/entities/{id}/access/profiles/{profile_id}` | Get one profile |
| `PATCH` | `/entities/{id}/access/profiles/{profile_id}` | Update `name`, `description`, `columns` |
| `DELETE` | `/entities/{id}/access/profiles/{profile_id}` | Delete an unreferenced profile |
| `GET` | `/entities/{id}/access/grants` | List grants (`created_at DESC`, `id DESC`; **Offset Page**) |
| `POST` | `/entities/{id}/access/grants` | Create a grant |
| `GET` / `PATCH` / `DELETE` | `/entities/{id}/access/grants/{grant_id}` | Read, update, delete a grant |
| `GET` | `/entities/{id}/access/restrictions` | List restrictions (`created_at DESC`, `id DESC`) |
| `POST` | `/entities/{id}/access/restrictions` | Create a restriction |
| `GET` / `PATCH` / `DELETE` | `/entities/{id}/access/restrictions/{restriction_id}` | Read, update, delete a restriction |
| `POST` | `/entities/{id}/access/preview` | Preview the shape (and optionally rows) a subject would get |

Wrapped single-resource responses use the resource name as key (`{ "ladder": … }`, `{ "profile": … }`, `{ "grant": … }`, `{ "restriction": … }`) plus `policy_revision` on writes. Unknown sub-resource ids, or an id that belongs to another Entity, are `404` with the matching `*_NOT_FOUND` code. Unknown body fields are `422 REQUEST_INVALID`.

### 4.1 Ladders

`PUT /entities/{id}/access/ladders/{attribute_id}` body is `{ "levels": [ … ] }`. Removing a level that a profile column or a restriction ceiling names is `409 ENTITY_ACCESS_IN_USE`; `detail` names the referrers. Success `200` `{ "ladder": …, "policy_revision": N }`.

### 4.2 Profiles

`POST` body: `{ "key", "name", "description"?, "columns" }`. `key` already used on this Entity is `409 ENTITY_ACCESS_KEY_DUP`. `key` cannot change. Success `201`.

`POST …/profiles/copy` body: `{ "source_entity_id", "source_profile_id", "key", "name" }`. Columns are matched by attribute name, compatible **Attribute Type**, and level key (`docs/business-entity-access.md` §5). Success `201` `{ "profile": …, "dropped_columns": [{ "attribute_name", "reason" }], "policy_revision": N }`. Unknown source Entity or profile is `404`.

`DELETE` of a profile that a grant references is `409 ENTITY_ACCESS_IN_USE`. Success `204`.

### 4.3 Grants And Restrictions

`POST` bodies carry every writable field of §3.5 or §3.6; `status` defaults to `active`, `valid_until` to `null`, restriction `actions` to all four. `PATCH` accepts any subset of writable fields except `subject` on a grant, which is immutable. Success `201` / `200` with the resource and `policy_revision`; `DELETE` is `204`.

### 4.4 Preview

`POST /entities/{id}/access/preview` body:

```json
{ "subject": { "type": "user", "id": "user_01HZX" }, "narrow": null, "include_rows": false, "filters": null, "limit": 50, "offset": 0 }
```

`subject.type` must be `user`. `narrow` follows the Entity Data API narrowing shape (§5.6) and must name an identity of that User. Response:

```json
{
  "policy_revision": 42,
  "effective_grants": ["eag_01HZX"],
  "schema": { "attributes": [], "withheld_field": "__withheld" },
  "rows": null
}
```

`schema` is the Entity Data API schema the subject would receive (§5.2). `include_rows: true` additionally requires `entity:data_read` and returns `rows` as an **Offset Page** of that subject's rows, each row adding `__sources`: per column, the grant ids that contributed the presented level. A preview with rows appends an Entity Access Log record naming the caller and the subject. Filters and limits follow the Entity Data API query rules.

## 5. Entity Data API Behavior Under Access Control

### 5.1 Visibility

After authentication and the master-switch Permission check, a `table_name` whose Entity gives the caller no effective grant for the verb's action answers `404 ENTITY_NOT_FOUND`, identical to an unregistered `table_name`, including `detail`. A row the caller cannot see answers `404 ENTITY_ROW_NOT_FOUND`, identical to a missing row, whether addressed by `row_id` or by `business_key`.

### 5.2 Schema

`attributes` lists only shape columns, in head attribute order. Each attribute adds:

```json
{
  "attribute_id": "att_01HZB",
  "presentation": {
    "row_varying": true,
    "levels": [
      { "key": "clear", "mode": "clear" },
      { "key": "last4", "mode": { "type": "partial", "keep_first": 0, "keep_last": 4 } }
    ],
    "may_be_withheld": true
  },
  "writable": false
}
```

`presentation.levels` are the levels that may appear in this column for the caller, most revealing first; one level when `row_varying` is false. `may_be_withheld` is true when some rows may withhold the column. `writable` is true when some effective `write` grant can attribute a write of this column (`docs/business-entity-access.md` §10.1). `upsert_key` is true only when it would otherwise be true and `writable` is true.

The top level adds `"withheld_field": "__withheld"` when the shape carries the withheld marker, otherwise `null`, and `"access": { "policy_revision": N, "narrowed": false }`.

For a `reference` attribute, `target` is `null` when the target Entity is not visible to the caller; `operators` still follow the snapshotted key type.

### 5.3 Rows, Fields, And Filters

- Rows carry only shape columns. When the shape carries the marker, every row carries `"__withheld": [names]`, including on writes and get. `__withheld` cannot appear in `fields`, `filters`, `values`, or `set`.
- Masked cells carry the masked value under the attribute's wire type; withheld cells carry `null`.
- `fields`, filter `field`, `values`, and `set` naming a column outside the shape answer exactly as for an unknown attribute name: the same Problem Code and the same `detail` form.
- Filters evaluate on presented values (`docs/business-entity-access.md` §9.7).

### 5.4 Writes

- Writes are attributed to one grant (`docs/business-entity-access.md` §10.1). When the target rows are visible but no single `write` grant attributes the request, the answer is `403 ENTITY_ACCESS_WRITE_DENIED`; `detail` does not list other subjects' grants. Nothing is written.
- `values` or `set` naming a shape column that is not clear in the attributing grant is the same refusal.
- Write responses and get return the row through the caller's read shape.
- A unique conflict is `409 ENTITY_ROW_CONFLICT`. `detail` may name the attribute the caller supplied and never names the other row's `row_id` or values. Upsert matches only visible rows; a key held by an invisible row is that conflict.
- Narrowing is not accepted on write verbs (`422 REQUEST_INVALID`).

### 5.5 Configuration States

| Situation | HTTP | Code |
| --- | --- | --- |
| Policy committed but views not regenerated, or the caller's combination view is being generated | 503 + `Retry-After` | `ENTITY_ACCESS_PENDING` |
| The caller's combination exceeds `entity_access.max_profile_combinations` | 409 | `ENTITY_ACCESS_COMBINATION_LIMIT` |

Both are reported only to callers that have an effective grant on the Entity; other callers receive `404 ENTITY_NOT_FOUND`.

### 5.6 Narrowing

`schema`, `get`, and `query` accept an optional top-level `narrow`:

```json
{ "narrow": { "type": "role", "id": "role_01HZX" } }
```

`type` is `user` (no `id`; the caller's direct grants), `role` (the caller's Role id), or `group` (a User Group id the caller belongs to). An identity the caller does not hold is `422 REQUEST_INVALID`. An identity that contributes no grant on the Entity answers `404 ENTITY_NOT_FOUND`. `narrow: null` is the same as omitting it.

### 5.7 Evaluation Order

Route → authentication → master-switch Permission → `table_name` resolution and visibility (both `404 ENTITY_NOT_FOUND`) → configuration state (§5.5) → deprecated → publishing write refusal → serving head → request structure, including `narrow` → semantics, including shape membership → in-batch uniqueness → row existence among visible rows → write attribution → conflict. `docs/api-contracts-entity-data.md` §10 carries the same order.

## 6. Definition Reads Under Access Control

`GET /entities`, `GET /entities/{id}`, `GET /entities/{id}/versions`, and `GET /entities/{id}/versions/{version_id}` apply `docs/business-entity-access.md` §12:

- A caller holding neither `entity:write` nor `entity:access_manage` lists only Entities with an effective `read` grant; `total` counts only those. Other Entity ids answer `404 ENTITY_NOT_FOUND`. Version `attributes` list only that caller's `read` shape columns; `attribute_count` counts them.
- Version `table_name` is `null` unless the caller holds `entity:write`.
- `inbound_references` lists only referring Entities visible to the caller.
- `POST /entities/{id}/classify` stays under `entity:read` and classifies only against attributes visible to the caller.

The first successful publish of an Entity that has no published version creates one Access Grant for the publishing User: subject type `user`, null row rule, profile `all_clear` (every head attribute at `clear`), actions `read`, `export`, and `write`. The grant is returned by the grant APIs and can be revoked. No grant is created for `super_admin` or for every `entity:write` holder.

## 7. Problem Codes

| Problem Code | HTTP status | When |
| --- | --- | --- |
| `ENTITY_ACCESS_INVALID` | 422 | Ladder, profile, grant, restriction, rule, subject, or preview body breaks a rule; `detail` names it |
| `ENTITY_ACCESS_PROFILE_NOT_FOUND` | 404 | Unknown profile id on this Entity, or unknown copy source |
| `ENTITY_ACCESS_GRANT_NOT_FOUND` | 404 | Unknown grant id on this Entity |
| `ENTITY_ACCESS_RESTRICTION_NOT_FOUND` | 404 | Unknown restriction id on this Entity |
| `ENTITY_ACCESS_KEY_DUP` | 409 | Profile `key` already used on this Entity |
| `ENTITY_ACCESS_IN_USE` | 409 | Delete a profile a grant references, or remove a ladder level a profile or ceiling names |
| `ENTITY_ACCESS_PENDING` | 503 + `Retry-After` | Data request while views do not match the policy revision or the caller's combination view is being generated |
| `ENTITY_ACCESS_COMBINATION_LIMIT` | 409 | Data request whose combination exceeds the cap |
| `ENTITY_ACCESS_WRITE_DENIED` | 403 | No single `write` grant attributes the write |

## 8. Non-Goals

1. Entity SQL over MCP and its tools.
2. HTTP reads of the Entity Access Log.
3. Bulk import or export of policy documents.
4. Optimistic-concurrency tokens on policy writes; concurrent writes serialize per Entity and each bumps `policy_revision`.
5. Previewing a Role or User Group as a subject.

## 9. References

- `docs/business-entity-access.md`
- `docs/api-contracts-entity.md`
- `docs/api-contracts-entity-data.md`
- `docs/api-contracts-users.md`
- `docs/business-jobs.md`
- `docs/conventions-errors.md`
- `docs/conventions-time.md`
- `docs/glossary.md`
