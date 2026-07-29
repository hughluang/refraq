# refraq Business Rules: Login And Permissions

## 1. Scope

This document defines the first business slice for `refraq`:

- administrator identity
- login rules
- session rules
- role rules
- permission rules

This slice belongs to the **Management Foundation**, the enabling layer of refraq. The product identity is defined by **Data Product Capabilities**, not by login or permission features.

These rules are the working source of truth for the first implementation unless superseded by a later ADR or business document.

## 2. Administrator Model

The first version should support only internal administrators.

Recommended administrator fields:

- `id`: unique identifier
- `account`: unique login account, initially treated as a username
- `display_name`: name shown in UI
- `password_hash`: stored server-side only
- `role`: one of the supported admin roles
- `status`: `active` or `disabled`
- `last_login_at`: latest successful login timestamp, nullable

## 3. Login Identifier Rule

The first version uses a single `account` field for login.

Reason:

- Smaller contract
- Easier backend and UI implementation
- Leaves room to evolve to email or SSO later without blocking the first slice

## 4. Successful Login Rule

Login succeeds only when all conditions are true:

1. `account` exists
2. password matches
3. administrator status is `active`

On success, the system must:

- create a new session
- update `last_login_at`
- return the current administrator summary
- set a session cookie for subsequent requests

## 5. Failed Login Rule

Login fails when:

- account does not exist
- password is wrong
- account is disabled

Behavior:

- invalid account and wrong password use the same external error wording
- disabled accounts return a distinct business error
- no detail should reveal password rules or internal storage details

## 6. Session Rule

The first version uses server-managed sessions.

Session rules:

- session is created on successful login
- session is required for protected APIs
- logout invalidates the current session
- expired or invalid sessions behave as unauthenticated

Recommended first-version session policy:

- session duration: 8 hours
- idle refresh is optional in v1
- multiple simultaneous sessions are allowed unless later restricted

## 7. Role Model

The first version uses three roles.

### `super_admin`

Can:

- access all admin pages
- manage administrators
- manage system-level configuration when such pages are added

### `operator`

Can:

- access authenticated dashboard pages
- read and modify operational business resources

Cannot:

- manage administrator accounts
- change high-risk system configuration

### `viewer`

Can:

- access authenticated dashboard pages
- read allowed resources

Cannot:

- create, update, delete, or manage administrators

## 8. Permission Evaluation Rule

Permission must be checked in backend using `resource + action`.

Suggested first-version resource/action model:

- `dashboard:read`
- `admins:read`
- `admins:write`
- `system:manage`

Recommended role mapping:

- `super_admin`: all permissions
- `operator`: `dashboard:read`
- `viewer`: `dashboard:read`

This mapping is intentionally small for v1.
New business resources should extend the permission list instead of bypassing it.

## 9. Route Protection Rule

### Frontend

- unauthenticated users may access only public pages such as `/login`
- authenticated users may access dashboard routes according to permissions
- users without required permission must see an explicit no-permission state instead of a broken page

### Backend

- protected endpoints require a valid session
- endpoints for admin-user management require `super_admin`

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

The first version does not require:

- password reset
- email verification
- MFA
- SSO
- fine-grained custom per-user permissions
