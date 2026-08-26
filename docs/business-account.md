# refraq Business Rules: Account Center

## 1. Scope

This document defines **Account Center** rules: the current User’s self-service Console surface for profile, local password change, UI locale, **Display Timezone**, and **User PAT** management.

Related:

- Session / login: `docs/business-login-auth.md`
- User PAT: `docs/business-user-tokens.md`
- API shapes: `docs/api-contracts-account.md`, `docs/api-contracts-auth.md`
- Terminology: `CONTEXT.md`, `docs/glossary.md`

Platform system parameters remain under Console Module `settings` (`docs/api-contracts-settings.md`); they are not Account Center.

## 2. Decision

- Account Center is a Console page at `/console/account`, entered from the header username menu.
- It is registered in Console Module Identity as identity-only (`routes.list` null, `routes.show` `/console/account`) and does **not** appear in the sidebar navigation tree.
- Any authenticated User with Console access may open Account Center; no extra permission is required for the shell, profile, password, locale, or Display Timezone self-service (`actions.show` → `console:access`).
- **User PAT** create/list/deactivate/restore/soft-delete remains gated by `tokens:read` / `tokens:write` and is embedded as a section inside Account Center (not a sidebar nav item; module `routes.list` is null).
- Self-service mutates **only the caller’s** User; admin `/users` APIs continue to manage other Users via `users:*`.

## 3. Profile, Locale, And Display Timezone

| Field | Rules |
| --- | --- |
| account | Read-only in Account Center |
| role / identity_source | Read-only |
| display_name | Self-service editable |
| email | Optional contact field: nullable, not unique, not verified, not used for login or mail |
| locale | Persisted on the User; must be a supported Console locale code (`zh-CN`, `en-US`); applied on login / identity restore |
| display_timezone | Optional IANA zone on the User for **Management Console** Instant formatting; `null` = follow browser; must be a `zoneinfo`-valid IANA id when set; does **not** change HTTP/MCP Instant wire (`Z`) |

## 4. Password Change

- Only when `identity_source=local`.
- Requires current password and a new password.
- On success: update password hash; invalidate **other** Sessions for that User; **keep** the current Session (S1).
- Password reset / forgot-password flows remain out of scope.

## 5. Non-Goals

- Email uniqueness or verification
- Using email as a login identifier
- Account Center secondary navigation (may come later)
- Merging Account Center into platform `settings`
- Admin impersonation of another User’s Account Center

## 6. References

- `docs/api-contracts-account.md`
- `docs/api-contracts-tokens.md`
- `docs/business-user-tokens.md`
