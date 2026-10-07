# refraq Business Rules: Entity Access

## 1. Scope

This document defines **Entity Access Control**: which rows of a published **Business Entity** a person may read or write, which attributes that person sees, and how each visible cell is presented. It defines the subjects that receive access (User, **Role**, **User Group**) and their **Subject Attribute**s, the `user` **Attribute Type**, the per-attribute **Presentation Ladder**, the per-Entity **Access Profile**, the **Access Grant** and **Access Restriction** that bind subjects to profiles and rows, the evaluation and write-attribution rules, definition visibility, residual leakage, audit, upgrade seeding, and the permissions that manage all of it. It also states the enforcement placement inside the entity database that every Entity data surface shares.

It does not define the Business Entity authoring lifecycle (`docs/business-entity.md`), the HTTP shapes (`docs/api-contracts-entity-access.md`, `docs/api-contracts-entity-data.md`, `docs/api-contracts-users.md`), or an Entity SQL surface on MCP.

Related boundaries:

- Business Entity definition, versions, publish, and the entity database: `docs/business-entity.md`
- Access management HTTP and the data-plane behavior that depends on access: `docs/api-contracts-entity-access.md`
- Entity Data API: `docs/api-contracts-entity-data.md`
- User, Role, and Permission catalog: `docs/business-login-auth.md`; User Group and Subject Attribute HTTP: `docs/api-contracts-users.md`
- User PAT: `docs/business-user-tokens.md`
- System Parameters: `docs/business-system-parameters.md`
- Platform Job: `docs/business-jobs.md`
- Connection settings and runtime database roles: `docs/env.md`
- Terminology: `docs/glossary.md`

## 2. Subjects

### 2.1 Subject Kinds

An **Access Grant** names exactly one subject:

| Subject type | Identity | Contributes |
| --- | --- | --- |
| `user` | `users.id` | Grants that name the User directly |
| `role` | `roles.id` | Grants that name the User's Role (`users.role_id`; at most one Role per User) |
| `group` | `user_groups.id` | Grants that name any **User Group** the User belongs to |

The global functional Role stays single-valued. A **User Group** is a named set of Users with no Permission of its own. It exists so that access can be granted to a population that does not match a Role. Membership is many-to-many. A User Group has an id, an immutable `key` (lowercase ASCII letters, digits, and underscores; starts with a letter; at most 63 characters; unique), a `name`, and an optional `description`.

A disabled User keeps its memberships and attribute values but cannot authenticate, so it reaches no Entity data. A grant whose subject no longer exists grants nothing and is reported as subject-missing on the management surface.

### 2.2 Subject Attributes

A **Subject Attribute** is a centrally defined, typed fact about a subject that row rules compare against Entity attributes (for example the regions a sales representative covers).

A definition has an immutable `key` (same character rule as a User Group key; unique), a `name`, an optional `description`, an immutable `value_type`, and `multi_value`:

| `value_type` | Value | Extra rule |
| --- | --- | --- |
| `string` | String of at most 256 characters | — |
| `integer` | 64-bit integer | — |
| `date` | `YYYY-MM-DD` | — |
| `dictionary` | A code of the bound **Dictionary** | `dictionary_id` is required and immutable. A written value must be an active code of that Dictionary |
| `user` | `users.id` | A written value must name an existing User |

`multi_value` false allows at most one value per subject row. It may change from false to true and not back.

Values are stored on Users and on User Groups. A Role carries no Subject Attribute values. The **effective value set** of a User for a key is the union of the User's own values and the values of every User Group the User belongs to. Rules treat every Subject Attribute as a set, including a single-valued one, because the union may hold more than one value. An empty effective set matches nothing.

A deprecated or deactivated Dictionary code already stored as a value stays stored and keeps matching. Deleting a definition deletes its values. A row rule that names a deleted definition makes its grant or restriction broken (§9.9).

Subject Attributes are platform data stored in the metadata database and owned by the Management Foundation. Entity access reads them; it does not own them.

### 2.3 Administration Permission

User Groups, group membership, Subject Attribute definitions, and Subject Attribute values on Users and Groups are managed under the existing user-management keys: `users:read` lists and reads them; `users:write` creates, updates, and deletes them and sets membership and values. No new Permission key is added for subject administration.

Reason: `users:write` already assigns a User's Role, which is the strongest access-shaping act in the Foundation, and is already a granting Permission that an Identity Provider auto-provisioning default Role may not hold. Group membership and Subject Attribute values shape Entity data access the same way, so splitting them under a weaker key would let a holder widen data access without holding the key that already governs that power.

## 3. The `user` Attribute Type

`user` is an **Attribute Type** whose value is the id of one User. It is single-valued. `config` is `{}`. The physical column is `VARCHAR(64)`. It may be `required`, `unique`, or `indexed`. It is not a valid **Business Key**.

A row write must name an existing User; a disabled User is accepted. Values stay stored after the referenced User is disabled. Outbound values are the User id. Display surfaces resolve the id to the User's account and display name.

Filters accept `eq`, `ne`, `in`, and `is_null`. Row rules may compare a `user` attribute with the caller's own User id (`subject_id`) or with a Subject Attribute whose `value_type` is `user`.

## 4. Presentation Ladder

Every attribute of a published head has one **Presentation Ladder**: a totally ordered list of presentation levels, most revealing first. Each level has a `key` unique within the ladder and a `mode`. The first level is always `clear` (the stored value). Later levels are masks.

A ladder with no authored masks is `[clear]`. The ladder is keyed by the attribute's stable `attribute_id` and therefore carries across **Entity Version**s while the attribute keeps its name.

Mask types and the Attribute Types they accept:

| Mask | Parameters | Accepted types | Output |
| --- | --- | --- | --- |
| `partial` | `keep_first`, `keep_last` (0–64 each) | `string`, `text` | Kept characters, other characters replaced by a fixed mask character |
| `email` | — | `string`, `text` | First character of the local part, then the mask, then `@` and the domain |
| `hash` | — | `string`, `text`, `dictionary`, `user`, `reference` with a `string` key | Keyed hash of the value, hexadecimal; stable within a site so equal inputs stay equal |
| `truncate_date` | `unit` (`year` \| `month` \| `day`) | `date`, `timestamp` | Value truncated to the unit |
| `bucket` | `width` (positive) | `integer`, `decimal`, `number` | Value floored to a multiple of `width` |
| `redact` | — | `string`, `text`, `dictionary`, `user`, `reference` with a `string` key | A fixed constant |
| `null` | — | every type | NULL |

A mask never raises an error on any stored value and never changes the column's wire type. A NULL input stays NULL.

The ladder order is the merge order (§9.5). Reordering a ladder changes which level wins and bumps the Entity's policy revision. A level that an **Access Profile** or an **Access Restriction** ceiling still names cannot be removed.

## 5. Access Profile

An **Access Profile** is a fixed set of columns of one Business Entity and one presentation level per column. It carries no row scope. A profile has an id, a `key` unique within the Entity, a `name`, an optional `description`, and `columns`: a list of `{ attribute_id, level }`. An attribute not listed is not in the profile. `row_id` is in every profile and is always `clear`.

A profile belongs to one Entity. A profile can be copied from another Entity: each source column is matched to the target head attribute of the same name and a compatible Attribute Type, and to the target ladder level of the same key. Unmatched columns are dropped and reported. The copy is a new profile with no link to the source.

An attribute added by a new version is in no profile until an author adds it. An attribute renamed by a new version is a new attribute with a new `attribute_id`.

## 6. Access Grant

An **Access Grant** is permissive. It binds:

| Field | Rule |
| --- | --- |
| `subject` | One subject (§2.1) |
| `profile_id` | One Access Profile of the same Entity |
| `row_rule` | A row rule (§8), or null for every row |
| `actions` | Non-empty subset of `read`, `write`, `export`, `mcp_query`. `write` requires `read` in the same grant |
| `status` | `active` or `disabled` |
| `valid_until` | Optional **Instant**; the grant is not effective at or after it |

`export` and `mcp_query` are stored and validated. No surface defined by this document evaluates them; the Entity Data API evaluates `read` and `write` only.

## 7. Access Restriction

An **Access Restriction** is restrictive and overrides grants (deny overrides). It binds:

| Field | Rule |
| --- | --- |
| `applies_to` | `all` subjects, `only` a subject list, or `all` `except` a subject list. A subject list names Users, Roles, and User Groups |
| `row_rule` | Optional row rule that every visible row must also satisfy |
| `deny_columns` | Attributes removed from every shape of the subjects it applies to |
| `ceilings` | Per attribute, the most revealing ladder level allowed |
| `actions` | Non-empty subset of the four actions; the restriction applies only to requests of those actions |

## 8. Row Rule Language

A row rule is a JSON tree. Authors never write SQL.

- Groups: `and` (non-empty list), `or` (non-empty list), `not` (one rule).
- Leaves: `{ "<op>": { "attr": "<attribute_id>", <operand> } }` with `op` one of `eq`, `ne`, `lt`, `lte`, `gt`, `gte`, `in`, `is_null`, `contains`.
- Operands: `value` (a literal, or a non-empty list for `in`); `subject_attr` (a Subject Attribute key, `in` only); `subject_id` (`true`; `eq` / `ne` only, `user` attributes only); `rel_time` (an ISO 8601 duration relative to statement time, for example `-P30D`; `lt` / `lte` / `gt` / `gte` only, `date` / `timestamp` only). `is_null` takes `true` or `false` as its operand.
- Type checking uses the attribute's physical type: operators follow the Entity Data API filter whitelist for that type; a literal must encode under that type; a `subject_attr` operand must have a compatible `value_type`, and a `dictionary` attribute requires a `dictionary` Subject Attribute bound to the same `dictionary_id`.
- Caps: 20 leaves and depth 8.
- A leaf that evaluates to SQL NULL is false. `ne` is `IS DISTINCT FROM`.

When a grant's row rule names an attribute that is not in that grant's profile, the management surface warns that row visibility discloses that the hidden value satisfies the rule. The rule is still accepted.

## 9. Evaluation

### 9.1 Default Deny And Master Switches

A request reaches Entity data only when both hold:

1. The caller holds the master-switch Permission: `entity:data_read` for reads; `entity:data_read` and `entity:data_write` for writes.
2. The caller has at least one effective grant for the request's action on that Entity (§9.2).

Without an effective grant, the Entity does not exist for that caller: every data verb answers exactly as for an unregistered `table_name`. Holding every Permission key, including the locked `super_admin` Role, does not bypass this rule.

### 9.2 Effective Grants

The effective grants of a request are the grants on the Entity whose subject is the caller (directly, through the caller's Role, or through a User Group the caller belongs to), whose `actions` include the request's action, whose `status` is `active`, whose `valid_until` is unset or later than the request Instant, and that are not broken. Narrowing (§9.8) then removes grants.

### 9.3 Rows

Let `G` be the effective grants and `R` the restrictions that apply to the caller and the action. A row is visible when every row rule in `R` holds on it and at least one grant in `G` has a row rule that holds on it (a null rule holds on every row).

### 9.4 Shape

The shape is the union of the columns of the profiles referenced by `G`, minus every `deny_columns` attribute in `R`. `row_id` is always in the shape. A column outside the shape does not exist for the caller on every surface: schema, field lists, filters, values, and errors.

### 9.5 Cells: Coupled Union

For a visible row and a shape column, the covering levels are the levels that column has in the profile of every grant in `G` whose row rule holds on that row and whose profile contains that column.

- No covering level: the cell is **withheld**. Its value is NULL.
- Otherwise: the cell takes the most revealing covering level by the column's ladder order, then is lowered to the most revealing level any applicable ceiling in `R` allows.

Normative definition: the result equals the full outer join on `row_id` of the results each effective grant would produce on its own, taking per cell the most revealing level by ladder order, then applying ceilings. A cell never reveals more than one single grant reveals for it, and adding a grant never shows less. Conformance tests use this definition as the oracle.

A shape column is **row-varying** when, across the profiles in the shape, it is missing from at least one profile or appears at more than one level. A single-profile shape has no row-varying column.

### 9.6 Withheld Marker

A shape that has at least one row-varying column carries the platform field `__withheld`: per row, the names of the columns withheld on that row, empty when none. A shape without row-varying columns does not carry it. The marker discloses which columns are withheld, never their values. Discovery surfaces state which columns are row-varying.

### 9.7 Filters, Ordering, And Aggregates Work On Output

Filters, ordering, grouping, and joins operate on the shape's output values: a hidden column cannot be named; a withheld cell is NULL; a masked cell is its masked value. Filtering a masked column therefore yields only what the mask already shows. Any SQL aggregate is evaluated over those same output values; the platform does not forbid an aggregate because some cells are withheld or masked.

### 9.8 Narrowing

A caller may narrow a read to one of its own identities: its direct User grants, its Role, or one of its User Groups. Narrowing keeps only the effective grants contributed by that identity. It never adds a grant, a column, or a row. Naming an identity the caller does not hold is a request error. The Management Console offers narrowing as "view as".

### 9.9 Broken Policy

A grant or restriction is **broken** when it names an attribute that is not in the current head, a ladder level that does not exist, a Subject Attribute key that is not defined, or a type combination that no longer checks. A broken grant grants nothing. A broken restriction makes the Entity invisible to every subject it applies to, for its actions. Publish re-evaluates brokenness for the new head.

## 10. Writes

### 10.1 Single-Grant Attribution

Every write request is attributed to exactly one effective grant with the `write` action. The request is allowed only when one such grant satisfies all of:

1. Every column the request writes is in the grant's profile at level `clear`, is not in any applicable `deny_columns`, and is not capped below `clear` by an applicable ceiling.
2. For update and delete: every target row, as stored before the change, satisfies the grant's row rule and every applicable restriction row rule.
3. For create and update: every row, as stored after the change, satisfies the grant's row rule and every applicable restriction row rule.

A request that writes several rows (`create-many`, `update-where`, `delete-where`) is attributed to one grant for all of its rows. Rows a write targets are located only among rows visible to the caller. A request that no single grant attributes is refused whole, and nothing is written.

A write may set only clear columns. A masked or withheld column cannot be written. A column outside the attributing grant's profile keeps its stored value on update and is NULL on create.

### 10.2 Write Responses

A write response returns the row through the caller's read shape. The attributing grant includes `read` and its row rule holds on the written row, so the row is visible.

## 11. Profile Views, Combinations, And Revisions

### 11.1 Profile Views

Each distinct set of profiles that occurs as a shape is one **Profile View** of the head. A view exists for every single profile of the Entity, and for every multi-profile combination that occurs as the effective grant set of some User, either un-narrowed or narrowed to one of that User's identities.

### 11.2 Combination Cap

The number of multi-profile combinations per Entity is capped by the System Parameter `entity_access.max_profile_combinations` (seed 64, range 1–1024). Single-profile views do not count. When a new combination would exceed the cap, its view is not generated; a request whose shape needs it is refused with an access-configuration-over-limit error, and the Console warns access managers with the affected subject count.

### 11.3 Revision Fence

Each Entity has a policy revision that increases on every change to its ladders, profiles, grants, or restrictions. Views are regenerated for the current head and the new revision by a platform **Job** in one entity-database transaction. Publish regenerates them in the same entity-database transaction that creates the table and moves the stem view; a failure rolls the publish back.

A view answers only requests that carry the revision it was compiled for. Between a policy commit and the completed regeneration, and while a needed combination view is being generated, requests on that Entity are refused with a retryable access-configuration-pending error. They are never answered with a stale policy or another shape. Subject Attribute value changes and grant expiry take effect on the next request without regeneration. A membership change regenerates only when it creates a combination that has no view.

## 12. Definition Visibility

| Caller | Business Entity definitions (`entity:read`) |
| --- | --- |
| Holds `entity:write` | Every Entity and every attribute; physical table names |
| Holds `entity:access_manage` without `entity:write` | Every Entity and every attribute; no physical table names |
| Holds neither | Only Entities where the caller has an effective `read` grant; only the attributes in the caller's un-narrowed `read` shape; no physical table names |

**Inbound Reference**s list only referring Entities visible to the caller under the same rule. **Dictionaries** stay globally visible to `entity:read` holders. The access management surface is visible only to `entity:access_manage` holders.

## 13. References To Rows The Caller Cannot See

An **Entity Reference** column is presented like any other column: its stored target Business Key appears according to the profile level. Wherever the product resolves a reference to a display label, it resolves the label only when the target row is visible to the caller through the caller's own shape of the target Entity; otherwise the label is "inaccessible record". Discovery surfaces name the target Entity only when the target Entity is visible to the caller.

## 14. Existence Leakage

Unique constraints, including the Business Key, are global to the table. The platform accepts this residual risk and narrows it:

- A unique conflict is a generic conflict. It may name the attribute the caller supplied, and never names the other row's `row_id` or values.
- Reading, updating, or deleting by Business Key a row the caller cannot see answers exactly as for a missing row.
- Upsert matches only visible rows. A key held by a row the caller cannot see is a generic conflict.

Other known inference channels are properties of the grants the caller already holds: a visible row discloses that it satisfies a row rule, including one over a column the caller cannot see (§8), and a withheld pattern discloses which grants cover a row.

## 15. Enforcement In The Entity Database

Access is enforced by PostgreSQL, not by predicates the application assembles per surface:

1. The entity database is a separate database from the metadata database. Runtime connections never use a superuser.
2. Physical **Entity Table**s and stem views live in a private schema that the runtime reader role cannot read. Each table has row-level security enabled and forced, with policies that admit only the profile-view owner and the write path.
3. Each Profile View is a `security_barrier` view owned by a dedicated non-login role. Its column list is the shape; its predicates and per-cell guards are compiled from the policy and check, for each grant, whether that grant is active in the request's signed access context.
4. The application computes the effective grants and the Subject Attribute values the rules need, signs them with the policy revisions and an expiry, and sets the signed context for the transaction. Validation functions in a private schema verify the signature. A forged, expired, or mismatched context makes every guard false and every view empty.
5. The Entity Data API and the Console read through the same Profile Views with the same signed context. Writes run in the same transaction as the attribution check, on the owner connection, using the same compiled policy.
6. A superseded version has no Profile View. Only the head is readable by the runtime reader.

Querying a Profile View other than the one the caller's shape selects never reveals more: guards accept only the caller's own grants, so extra columns are withheld and no extra rows appear.

## 16. Audit

Every Entity Data API request that reaches the access decision appends one record to the **Entity Access Log** in the metadata database: Instant, User id, User PAT id when present, request id, Entity id, verb, effective grant ids, narrowing identity, Profile View, policy revision, rows returned or affected, and outcome code. Records older than the System Parameter `entity_access.access_log_retention_days` (seed 90, range 7–3650) are deleted by the platform. The log is not a **Management Audit Event** stream.

A **Management Audit Event** is written for every create, update, delete, and copy of ladders, profiles, grants, and restrictions, and for every create, update, and delete of User Groups, membership, Subject Attribute definitions, and Subject Attribute values. A preview that returns rows also appends an Entity Access Log record naming both the caller and the previewed subject.

## 17. Upgrade Seeding

When access-control storage is first created on a site, upgrade seeds access so that existing readers keep their current data:

- For every existing Business Entity with a published head: a profile `all_clear` containing every head attribute at `clear`.
- For every Role that effectively holds `entity:data_read`, including `super_admin`: on each such Entity, one grant of `all_clear` to that Role with null row rule and actions `read`, plus `write` when the Role effectively holds `entity:data_write`.

Seeding is an Alembic data migration on the metadata database. It runs once per site. Profile Views for that seed are created by a startup reconciliation Job, not by a Foundation Upgrade call. A Business Entity created afterwards has no Role grant. Its first successful publish adds one grant for the publishing User: all rows, the `all_clear` profile, actions `read`, `export`, and `write`. That grant is an ordinary Access Grant and can be revoked. `super_admin` and holders of `entity:write` do not receive it automatically. Until a grant exists, the Entity's data is visible to nobody.

## 18. Permissions

| Permission | Grants |
| --- | --- |
| `entity:access_manage` | Read and change ladders, profiles, grants, and restrictions on every Entity; copy profiles; preview a subject's shape; see full definitions (§12) |
| `entity:data_read` | Master switch for Entity data reads; access additionally requires an effective `read` grant |
| `entity:data_write` | Master switch for Entity data writes, always together with `entity:data_read`; access additionally requires an attributing `write` grant |
| `users:read` / `users:write` | User Groups, membership, Subject Attribute definitions, and values (§2.3) |

`entity:access_manage` is not seeded onto `operator`, is not implied by `entity:write`, and does not imply data access. It is a granting Permission: an Identity Provider auto-provisioning default Role must not contain it.

## 19. Management Console

- The Business Entity record has an access control tab for `entity:access_manage` holders: presentation ladders, the profile matrix (attributes by profiles), grants (subject picker, visual row-rule editor, actions, validity), restrictions, copy profile from another Entity, the combination count against the cap with over-limit warnings, and preview by subject with a per-cell source hint.
- The Business Entity record has a data page for `entity:data_read` holders that calls the Entity Data API, offers "view as" narrowing, shows withheld cells as "no access", marks masked columns, and marks row-varying columns as present on some rows only.
- Administration adds modules User Groups (`user-groups`) and Subject Attributes (`subject-attributes`) under `users:read` / `users:write`. The User record edits that User's groups and Subject Attribute values.

## 20. Non-Goals

1. Entity SQL over MCP — the SQL gate, extended-protocol execution, token-bound identity subsets, and database-level statement audit. It is a planned surface with its own contract; the enforcement in §15 is the layer it reads through.
2. Tag-driven default masks, aggregate-only Entities, and differential privacy.
3. Per-User views, explicit grant priority ordering, and any data-access bypass for administrators.
4. A Grant × scope control plane for platform Permissions; `users.role_id` remains the single functional Role.
5. Synchronizing User Groups or Subject Attributes from an Identity Provider.
6. PAT scopes that narrow Entity access.
7. An HTTP read surface for the Entity Access Log.
8. Profiles shared across Entities by reference, and hiding column names from direct database catalog reads.

## 21. References

- `docs/business-entity.md`
- `docs/api-contracts-entity-access.md`
- `docs/api-contracts-entity-data.md`
- `docs/api-contracts-users.md`
- `docs/business-login-auth.md`
- `docs/business-user-tokens.md`
- `docs/business-system-parameters.md`
- `docs/business-jobs.md`
- `docs/env.md`
- `docs/glossary.md`
