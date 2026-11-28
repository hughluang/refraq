# refraq API Contracts: SCIM 2.0 Provisioning

## 1. Purpose

This document defines the SCIM 2.0 Service Provider endpoints (`/scim/v2/*`, publicly `/api/scim/v2/*`) and per-**Identity Provider** SCIM provisioning token administration endpoints.

Related boundaries:

- Identity Providers and federation rules: `docs/business-identity-providers.md`, `docs/api-contracts-identity-providers.md`
- OAuth delegation and instant revocation: `docs/business-oauth-delegation.md`
- User Groups and Subject Attributes: `docs/api-contracts-users.md`, `docs/business-entity-access.md`

## 2. SCIM Provisioning Token Administration

Mounted under Identity Providers; requires `identity_providers:write` (or `identity_providers:read` for list).

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `GET` | `/identity-providers/{id}/scim-tokens` | `identity_providers:read` | List non-revoked SCIM tokens for a provider (metadata only) |
| `POST` | `/identity-providers/{id}/scim-tokens` | `identity_providers:write` | Mint a new `rfq_scim_` Bearer token scoped to this provider (plaintext returned once) |
| `DELETE` | `/identity-providers/{id}/scim-tokens/{token_id}` | `identity_providers:write` | Revoke a SCIM token immediately |

## 3. SCIM 2.0 Transport And Isolation

- Every `/scim/v2/*` request requires `Authorization: Bearer rfq_scim_...`.
- The token resolves to a sealed `ScimProviderPrincipal(provider_id, issuer, token_id)`. The provider must be enabled.
- All User and Group operations are strictly isolated to bindings belonging to that `issuer` / `provider_id`. Local Users and Users bound to another Identity Provider are never visible or mutable.
- Responses use `Content-Type: application/scim+json`. Errors under `/scim/v2/*` follow RFC 7644 `urn:ietf:params:scim:api:messages:2.0:Error`.

## 4. Discovery Endpoints

- `GET /scim/v2/ServiceProviderConfig`
- `GET /scim/v2/ResourceTypes`
- `GET /scim/v2/Schemas`

## 5. Users Endpoints (`/scim/v2/Users`)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/scim/v2/Users` | List non-deprovisioned Users bound to this provider; supports `startIndex`, `count`, and `filter` (`userName eq "..."`, `externalId eq "..."`) |
| `POST` | `/scim/v2/Users` | Provision a federated User (`identity_source=oidc`, provider `default_role_id`) or reactivate a previously SCIM-deprovisioned binding for the same `(issuer, subject)` |
| `GET` | `/scim/v2/Users/{id}` | Read one provider-bound User; returns `404` if soft-deprovisioned or outside provider scope |
| `PUT` | `/scim/v2/Users/{id}` | Replace User profile, `active` status, and optional Subject Attributes |
| `PATCH` | `/scim/v2/Users/{id}` | Apply RFC 7644 `PatchOp` (`add`, `replace`, `remove`) including `active` toggle and extension attributes |
| `DELETE` | `/scim/v2/Users/{id}` | Soft-deprovision: sets `users.status=disabled`, stamps `scim_deprovisioned_at`, revokes all Sessions and Delegated Access Tokens, and returns `204` |

Subject derivation follows the provider's `scim_subject_source` (`external_id` or `user_name`). Setting `active=false` or calling `DELETE` routes through `admin.lifecycle.disable_user` for immediate Session and `rfq_oat_` token revocation.

### 5.1 Subject Attribute Extension Schema

Extension URN: `urn:ietf:params:scim:schemas:extension:refraq:2.0:User` (and `:Group` on Groups). Keys map to registered **Subject Attribute** definitions and are validated against each definition's `value_type` and `multi_value` rules before persisting.

## 6. Groups Endpoints (`/scim/v2/Groups`)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/scim/v2/Groups` | List Groups bound to this provider (`startIndex`, `count`, `displayName eq "..."`, `externalId eq "..."`) |
| `POST` | `/scim/v2/Groups` | Create or bind a **User Group** and sync initial `members` |
| `GET` | `/scim/v2/Groups/{id}` | Read one provider-bound Group with its members |
| `PUT` | `/scim/v2/Groups/{id}` | Replace Group display name, members, and optional Subject Attributes |
| `PATCH` | `/scim/v2/Groups/{id}` | Apply RFC 7644 `PatchOp` on `displayName`, `members`, and extension attributes |
| `DELETE` | `/scim/v2/Groups/{id}` | Remove the provider group binding and delete the managed User Group |

## 7. Non-Goals

- SCIM Bulk operations (`/scim/v2/Bulk`)
- Hard deletion of `users` database rows
- Cross-provider User or Group visibility
- Mutating `super_admin` or `system` identities via SCIM

## 8. References

- `docs/business-identity-providers.md`
- `docs/business-oauth-delegation.md`
- `docs/api-contracts-users.md`
