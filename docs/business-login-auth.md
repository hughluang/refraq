# refraq Business Rules: Login And Permissions

## 1. Scope

This document defines the Management Foundation access slice for `refraq`:

- User identity (people)
- login and session rules
- Role as a first-class entity
- fixed Permission catalog and evaluation

This slice belongs to the **Management Foundation**, the enabling layer of refraq. The product identity is defined by **Data Product Capabilities**, not by login or permission features.

These rules are the working source of truth unless superseded by a later ADR or business document.

## 2. User Model

The current slice models people as **User** records.

Recommended User fields:

- `id`: unique identifier
- `account`: unique login account, initially treated as a username
- `display_name`: name shown in UI
- `password_hash`: stored server-side only (local identity source)
- `role_id`: optional foreign key to a Role (`null` means no role)
- `status`: `active` or `disabled`
- `identity_source`: `local` in this slice (`ldap` reserved)
- `last_login_at`: latest successful login timestamp, nullable

A User without a Role, or with a Role that lacks `console:access`, cannot obtain a Management Console session.

## 3. Login Identifier Rule

The first version uses a single `account` field for login.

Reason:

- Smaller contract
- Easier backend and UI implementation
- Leaves room to evolve to email, LDAP, or SSO later without blocking the slice

## 4. Successful Login Rule

Login succeeds only when all conditions are true:

1. `account` exists
2. password matches (for `identity_source=local`)
3. User status is `active`
4. User has a Role that includes `console:access`

On success, the system must:

- create a new session
- update `last_login_at`
- return the current user summary (including resolved permissions)
- set a session cookie for subsequent requests

## 5. Failed Login Rule

Login fails when:

- account does not exist
- password is wrong
- account is disabled
- account has no Role, or the Role lacks `console:access`

Behavior:

- invalid account and wrong password use the same external error wording
- disabled accounts return a distinct business error
- missing console access returns a distinct business error (`AUTH_CONSOLE_ACCESS_REQUIRED`)
- no detail should reveal password rules or internal storage details

## 6. Session Rule

The first version uses server-managed sessions.

Session rules:

- session is created on successful login
- protected APIs require a valid **Session or User PAT** (see `docs/business-user-tokens.md`); Console browser flows use Session
- logout invalidates the current session (does not deactivate or soft-delete PATs unless a separate token action is performed)
- expired or invalid sessions behave as unauthenticated
- disabling a User invalidates all of that User's sessions immediately and must reject that User's PATs (`401`)
- after disable, requests that still present a former session cookie or that User's PAT are treated as unauthenticated (`401`)
- re-enabling a User does not restore prior sessions; the User must sign in again (existing non-deactivated, non-deleted PATs remain subject to expiry/deactivate/delete rules in the tokens doc)

Recommended first-version session policy:

- session duration: 8 hours
- idle refresh is optional in v1
- multiple simultaneous sessions are allowed unless later restricted

Frontend navigation around the session boundary:

- the only return-path query param is `from` (same-origin relative path)
- successful login uses a hard (document) navigation to the validated `from` path
- successful logout uses a hard (document) navigation to `/login`
- the console client guard must not emit Refine's `to` query param after auth failure
- when a session becomes invalid while a cookie may still be present, the client redirects to `/login` with a validated `from` path
- the Management Console may paint the AppShell before `GET /auth/me` returns: `proxy.ts` already gates on cookie presence, and `authProvider.check` is optimistic (does not await `/auth/me`)
- only protected Console documents fetch Session identity; public pages such as `/login` and `/403` stay anonymous and must never hard-navigate to login on `401`
- `GET /auth/me` is time-bounded; a timeout is a non-401 load-error terminal with retry, not a logout
- opening `/login` with a valid Session enters the Console at the validated `from` path
- opening `/login` when `GET /auth/me` fails with a non-401 error (network / 5xx / timeout) is a load-error terminal with retry, not the login form and not a logout
- the client ACL gate blocks page content until permissions and Module Identities are ready, so a no-permission route shows the forbidden terminal instead of module content or a data-fetch error
- the client may keep a tab-scoped **User** display summary in `sessionStorage` for UX only (account / display name / locale / display timezone). This is not a **Session**; the Session remains the HttpOnly cookie. Permissions and role fields are not persisted there and must come from login or `/auth/me`
- an invalid Session still yields `401` on API calls: the client clears the display summary and hard-navigates to `/login` with a validated `from` path
- losing `console:access` while a Session cookie remains (`403` on console navigation / module-identity APIs) is an explicit forbidden terminal state in the shell, not an infinite skeleton
- a `GET /auth/me` failure that is not `401` (network / 5xx), while permissions have not yet loaded this tab, is an explicit load-error terminal in the shell with retry; it is not an infinite skeleton and not a logout

## 7. Role Model

Role is a first-class entity. Each User may hold **at most one** Role (`role_id` nullable).

### Locked system role: `super_admin`

- **System Role**: product-owned; identity is stable (`id` / `key`)
- Inserted by **Site Bootstrap** when the role store is empty (stored `permissions` may be empty; not authoritative)
- **Foundation Upgrade** ensures the identity row exists (`locked`, stable id/key/name) — it does **not** grant Super Admin access by rewriting a stored permission list
- Effective permissions are definitionally the full Permission catalog whenever `key == super_admin`
- `key` cannot be changed via Role APIs
- Cannot be deleted
- Permissions cannot be edited via Role APIs (`ROLE_LOCKED`)

### Seeded ordinary role: `operator`

- Inserted by **Site Bootstrap** when the role store is empty, with `console:access` and `dashboard:read`
- Display name and permissions are editable
- **Foundation Upgrade** never resets this role
- May be deleted only when no User references it

### Custom roles

- Creatable in the Management Console when the caller has `roles:write`
- Permissions chosen only from the fixed catalog
- Deletion forbidden while any User still references the role

`viewer` is not seeded. Operators may recreate an equivalent role via the Role UI if needed.

## 8. Permission Evaluation Rule

Permission must be checked in backend using `resource + action` strings from the Role's bound set.

Fixed Permission catalog (Foundation + metadata foundation extensions):

- `console:access`
- `dashboard:read`
- `users:read`
- `users:write`
- `roles:read`
- `roles:write`
- `settings:read`
- `settings:write`
- `sources:read` / `sources:write`
- `metadata:read` / `metadata:write`
- `jobs:run`
- `query:run`
- `catalog:sample`
- `tokens:read` / `tokens:write`
- `audit:read`

Rules:

- New permissions enter the catalog in code/docs first; Role UI only checkboxes catalog entries
- Free-form permission strings are rejected
- Frontend checks are UX only; backend remains authoritative
- Seeded `operator` keeps `console:access` + `dashboard:read` only (no `settings:*`, no metadata write/query/sample/token/audit by default)
- Metadata permission meanings: `docs/business-metadata.md` §6; User PAT: `docs/business-user-tokens.md`
- Session TTL used at login is the **effective** value of the `admin_session_ttl_hours` **System Parameter** (stored value, seeded 8; no env fallback); changing TTL does not rewrite existing sessions — see `docs/business-system-parameters.md` and `docs/api-contracts-settings.md`

## 9. Route Protection Rule

### Frontend

- unauthenticated users may access only public pages such as `/login`
- authenticated users may access console routes according to permissions
- users without required permission must see an explicit no-permission state instead of a broken page

### Backend

- protected endpoints require a valid Session or User PAT
- user-management endpoints require `users:read` / `users:write`
- role-management endpoints require `roles:read` / `roles:write`
- platform settings endpoints require `settings:read` / `settings:write`
- metadata / token / audit endpoints use permissions in §8 and `docs/business-metadata.md`
- console navigation requires `console:access` (module visibility filtered separately)

## 10. Logout Rule

Logout always targets the current session.

Expected behavior:

- session is invalidated server-side
- session cookie is cleared
- frontend returns user to `/login`

Calling logout while already unauthenticated may still return success for simplicity.

## 11. Audit-Oriented Events

Foundation login paths should remain easy to audit:

- login success
- login failure
- logout
- forbidden access

Persistent storage for those Foundation auth events is still not required by this document.
Management-plane audit for metadata, secrets, User PAT, and controlled query is defined in `docs/business-metadata.md` and is in scope for the metadata foundation phase.

## 12. Dual Auth Transport (Session And User PAT)

- Console browser flows continue to use **Session** cookies as defined above.
- Non-browser API and MCP clients use **User PAT** Bearer credentials (`docs/business-user-tokens.md`).
- Both resolve to the same **User** and Role **Permission** evaluation.
- Do not treat Session id as a PAT; do not treat PAT as a **Client** credential.

## 13. Business Non-Goals

The Foundation login/permission slice does not require:

- password reset
- email verification
- MFA
- SSO / LDAP protocol integration (field `identity_source` only)
- Client / machine-token management APIs
- multi-role assignment per User
- free-form custom permissions outside the catalog
- hard delete of User records

User PAT (person-owned Bearer tokens) is specified in `docs/business-user-tokens.md` for the metadata foundation phase and is not a Client API.