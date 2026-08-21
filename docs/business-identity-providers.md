# refraq Business Rules: Identity Providers

## 1. Scope
This document defines configured external identity providers, OIDC federation, external identity binding, automatic admission, pending identities, and administrative handoff. It does not define local password authentication or Role implementation.

Related boundaries:
- Login and shared User rules: `docs/business-login-auth.md`.
- Users API and pending claims: `docs/api-contracts-users.md`.
- Provider API: `docs/api-contracts-identity-providers.md`.
- Console Administration: `docs/business-management-console.md`.
- Decision: `docs/adr/0033-identity-federation.md`.

## 2. Identity Provider Model
An **Identity Provider** authenticates a person and asserts identity; it never owns refraq Roles, Permissions, Sessions, or User PATs. This slice implements OIDC only. The provider row stores `protocol=oidc`. Binding and provisioning consume a normalized external assertion, not OIDC wire types. Additional protocols are a future decision.

Each provider has a stable id, unique normalized `issuer`, `protocol=oidc`, display name, enabled state, encrypted protocol configuration, and audit timestamps. The issuer is unique across provider rows and cannot be changed after create, because it is part of the binding key. Configuration includes client credentials, scopes, auto-provisioning, group claim, exact group allowlist, and default Role. Custom claim-name maps beyond `group_claim` are out of scope.

## 3. External Identity Binding
An **External Subject** is the provider's stable OIDC `sub`. A binding is identified by `(issuer, subject)`, with `subject` limited to the OIDC contract. Each binding belongs to exactly one User, and each User has at most one binding. `provider_id` is only a weak reference so deleting and recreating configuration does not change the identity key.

`account` remains refraq's internal login identifier. Email, display name, preferred username, and provider ids are never binding keys. A renamed provider account does not transfer identity when its subject changes.

## 4. OIDC Admission
After protocol validation, admission evaluates in this order:

1. An existing `(issuer, subject)` binding resolves the User. Disabled Users return `AUTH_ACCOUNT_DISABLED`; Users without `console:access` return `AUTH_CONSOLE_ACCESS_REQUIRED`. If provider auto-provisioning is enabled, exact group matching is required on every login. Failure issues no Session and does not alter the User, pending queue, or PATs.
2. Without a binding, auto-provisioning may create a User only when exact group matching succeeds, the derived account is unused, and the configured default Role grants `console:access`. It sets `identity_source=oidc`, stores no usable password, assigns the configured default Role once, writes the binding, and issues a refraq Session. A default Role without `console:access` returns `AUTH_CONSOLE_ACCESS_REQUIRED` and creates no User, so the same successful-login rule holds on every path.
3. Every other valid assertion is recorded or updated as a pending identity and receives no Session.

The derived account order is `preferred_username`, then `email`, then `sub`. An account collision is queued, never silently bound. Group values are exact strings. Missing groups and provider-reported overflow (`_claim_names`, `hasgroups`, or equivalent) are queued rather than treated as allow or ordinary non-membership.

## 5. Pending Identity Handoff
A pending identity is not a User and is not subject to the User no-hard-delete rule. It has only the `pending` state and may be removed after expiry. Its claim snapshot includes issuer, subject, provider reference, derived account, display attributes, exact groups, admission reason, attempt count, first seen, last attempt, and `expires_at`.

The first attempt fixes `expires_at` using `sso_pending_ttl_days` (seed 7, range 1-30). Later attempts update attempt count and `last_attempt_at` but never extend expiry. Changing the System Parameter affects only newly written pending records.

Only `users:write` can list or claim pending identities. Claiming an existing User changes only the binding and sets `identity_source=oidc`; it does not change Role. Creating a User requires a selected Role and uses the claim snapshot as prefilled data. A User with another binding must be unfederated first. The last active local `super_admin` cannot be converted to OIDC.

## 6. Default Role Safety
A provider default Role is a one-time authorization grant, not continuous synchronization. Its effective permissions must not intersect `users:write`, `roles:write`, or `identity_providers:write`. The rule is checked when saving a provider and when adding those permissions to a Role referenced by any provider. `super_admin` is invalid as a default because its effective permissions are the full catalog. Manual claims are not subject to this auto-provisioning restriction.

Safety bounds the default Role from above; `console:access` bounds it from below. Because a referenced Role can lose `console:access` after the provider was saved, admission rechecks it on every auto-provisioned login rather than trusting the saved configuration.

## 7. Disablement, Deletion, And Unfederation
Disabling a provider blocks new federation handoffs but does not disable bound Users. Deleting or disabling a provider displays the number of bound Users and may optionally disable them through the existing User disable path, which clears Sessions and rejects PATs. Each cascaded disable is audited. The currently signed-in User is never included in that cascade.

Unfederation requires `users:write` and is an atomic administrative action: clear the binding, set `identity_source=local`, and set a new initial local password. Account Center and the User cannot perform it. The action is the inverse of claim; future OIDC attempts follow normal unbound admission rules.

## 8. Security And Standards
OIDC validation follows OpenID Connect Core 1.0 incorporating errata set 2, including ID Token validation and stable `sub`; Discovery issuer must exactly match the configured issuer. Authorization uses the code flow with PKCE `S256`, exact redirect URIs formed from the trusted Console origin, state and nonce, and issuer identification safeguards. RFC 9700, RFC 7636, RFC 9207, and RFC 3986 provide the OAuth security and comparison baseline.

refraq does not store IdP access or refresh tokens and does not request `offline_access`. External HTTP is restricted by the provider configuration and the `identity_providers:write` administrative boundary.

## 9. Audit Events
Provider create, update, test, enable, disable, and delete; SSO success and rejection (including handoff, provider unavailability, assertion rejection, and admission); pending claim; unfederation; and optional cascaded User disable produce Management Audit Events. Public admission errors intentionally collapse pending, group failure, overflow, and account collision to `AUTH_SSO_NOT_ADMITTED`; audit and pending records retain the reason. Audit detail must not include authorization codes, tokens, or full claims.

## 10. Non-Goals
- SAML, CAS, LDAP synchronization, and other non-OIDC protocols
- Continuous Role or group-to-Role synchronization
- RP-initiated logout, back-channel logout, SCIM provisioning, and multi-binding Users
- Provider-issued Sessions, Roles, Permissions, or PATs
- Account Center self-service unfederation

## 11. References
- `docs/api-contracts-identity-providers.md`
- `docs/api-contracts-auth.md`
- `docs/api-contracts-users.md`
- `docs/business-login-auth.md`
- `docs/adr/0033-identity-federation.md`
