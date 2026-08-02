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
- session is required for protected APIs
- logout invalidates the current session
- expired or invalid sessions behave as unauthenticated
- disabling a User invalidates all of that User's sessions immediately
- after disable, requests that still present a former session cookie are treated as unauthenticated (`401`)
- re-enabling a User does not restore prior sessions; the User must sign in again

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

## 7. Role Model

Role is a first-class entity. Each User may hold **at most one** Role (`role_id` nullable).

### Locked system role: `super_admin`

- Seeded at startup
- `key` cannot be changed
- Cannot be deleted
- Permissions are always the full Permission catalog and cannot be edited

### Seeded ordinary role: `operator`

- Seeded at startup with `console:access` and `dashboard:read`
- Display name and permissions are editable
- May be deleted only when no User references it

### Custom roles

- Creatable in the Management Console when the caller has `roles:write`
- Permissions chosen only from the fixed catalog
- Deletion forbidden while any User still references the role

`viewer` is not seeded. Operators may recreate an equivalent role via the Role UI if needed.

## 8. Permission Evaluation Rule

Permission must be checked in backend using `resource + action` strings from the Role's bound set.

Fixed Permission catalog for this slice:

- `console:access`
- `dashboard:read`
- `users:read`
- `users:write`
- `roles:read`
- `roles:write`

Rules:

- New permissions enter the catalog in code/docs first; Role UI only checkboxes catalog entries
- Free-form permission strings are rejected
- Frontend checks are UX only; backend remains authoritative

## 9. Route Protection Rule

### Frontend

- unauthenticated users may access only public pages such as `/login`
- authenticated users may access console routes according to permissions
- users without required permission must see an explicit no-permission state instead of a broken page

### Backend

- protected endpoints require a valid session
- user-management endpoints require `users:read` / `users:write`
- role-management endpoints require `roles:read` / `roles:write`

## 10. Logout Rule

Logout always targets the current session.

Expected behavior:

- session is invalidated server-side
- session cookie is cleared
- frontend returns user to `/login`

Calling logout while already unauthenticated may still return success for simplicity.

## 11. Audit-Oriented Events

The first version should be written so these events can be logged later:

- login success
- login failure
- logout
- forbidden access

Persistent audit storage is not required in the current scaffold phase, but code paths should make those events easy to add.

## 12. Business Non-Goals

The current slice does not require:

- password reset
- email verification
- MFA
- SSO / LDAP protocol integration (field `identity_source` only)
- Client / Token management APIs
- multi-role assignment per User
- free-form custom permissions outside the catalog
- hard delete of User records
