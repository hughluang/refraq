# refraq API Contracts: Identity Providers

## 1. Purpose
This document defines the authenticated Administration API for OIDC Identity Provider configuration and connectivity tests. It does not define the public login callback or User pending-claim endpoints.

Related boundaries:
- Business rules: `docs/business-identity-providers.md`.
- Public login: `docs/api-contracts-auth.md`.
- Pending claims and unfederation: `docs/api-contracts-users.md`.
- Errors: `docs/conventions-errors.md`.

## 2. Transport And Authorization
All endpoints use JSON success and RFC 9457 Problem Details failures. They accept Session or User PAT and require `console:access` plus `identity_providers:read` for reads or `identity_providers:write` for writes. Secrets are write-only and never returned.

## 3. Provider Shape
```json
{
  "id": "idp_corp",
  "protocol": "oidc",
  "display_name": "Corporate Login",
  "issuer": "https://idp.example.com",
  "enabled": true,
  "auto_provision": true,
  "group_claim": "groups",
  "group_allowlist": ["/dept/analytics"],
  "default_role_id": "role_operator",
  "scopes": ["openid", "profile", "email"],
  "client_id": "refraq",
  "client_secret_configured": true,
  "bound_user_count": 3,
  "created_at": "2026-08-20T09:00:00Z",
  "updated_at": "2026-08-21T03:00:00Z"
}
```
`issuer` is normalized and unique. `client_secret` is accepted on write and represented only by `client_secret_configured` on read. `bound_user_count` is the number of Users currently bound to this issuer and drives the disable and delete confirmations. Protocol-specific fields are governed by the protocol spec; unknown fields are rejected.

## 4. Provider Endpoints
### `GET /identity-providers/spec`
Permission: `identity_providers:read`. Returns the protocol specification used to drive create and edit forms. Query `protocol` defaults to `oidc`; unimplemented protocols are rejected with `IDENTITY_PROVIDER_PROTOCOL_UNSUPPORTED`.

### `GET /identity-providers`
Permission: `identity_providers:read`. Returns an Offset Page of provider summaries. Configuration secrets and private claims are omitted.

### `POST /identity-providers`
Permission: `identity_providers:write`. Creates a provider. The request includes protocol, display name, OIDC spec, and optional enabled state. It rejects `IDENTITY_PROVIDER_PROTOCOL_UNSUPPORTED`, `IDENTITY_PROVIDER_INVALID_CONFIG`, `IDENTITY_PROVIDER_ISSUER_DUPLICATE`, and `IDENTITY_PROVIDER_DEFAULT_ROLE_FORBIDDEN`.

### `GET /identity-providers/{id}`
Permission: `identity_providers:read`. Returns the provider shape and non-secret configuration.

### `PATCH /identity-providers/{id}`
Permission: `identity_providers:write`. Updates display name, enabled state, and protocol configuration. Issuer is immutable after create; a different issuer is rejected with `IDENTITY_PROVIDER_ISSUER_IMMUTABLE`. Default-Role safety is rechecked. It does not rewrite existing bindings. When `enabled` is set to `false`, the request may pass the query parameter `disable_bound_users=true` (a query parameter, not a body field). Without the flag, bound Users remain enabled and the provider cannot start new federation handoffs. With the flag, each bound User follows the existing disable path and is audited. The currently signed-in User is never cascaded. Enabling a provider never cascades.

### `POST /identity-providers/{id}/test`
Permission: `identity_providers:write`. Performs discovery and provider validation, then returns public metadata and the configured `group_claim` name. An unreachable discovery endpoint is `AUTH_SSO_PROVIDER_UNAVAILABLE`; a reachable but invalid document (issuer differs from the configured issuer, missing endpoints, or unusable signing algorithms) is `AUTH_SSO_ASSERTION_REJECTED`. It does not return user group values, tokens, or secrets, and it does not create a User or pending identity. Administrators copy exact group strings from a real login's pending-identity record (`users:write`).

### `DELETE /identity-providers/{id}`
Permission: `identity_providers:write`. The request may pass the query parameter `disable_bound_users=true` (a query parameter, not a body field). The response is `{ "bound_user_count": <int> }`, the number of Users that were bound at delete time. Without the flag, bindings remain and Users are not disabled; the provider is removed and cannot authenticate. With the flag, each User follows the existing disable path and is audited. The currently signed-in User is never cascaded.

## 5. Errors
| Status | Problem Code | Condition |
| --- | --- | --- |
| `400` | `IDENTITY_PROVIDER_INVALID_CONFIG` | Invalid OIDC spec, issuer, redirect, or group policy |
| `400` | `IDENTITY_PROVIDER_PROTOCOL_UNSUPPORTED` | Protocol is not implemented |
| `401` | `AUTH_SSO_ASSERTION_REJECTED` | Discovery document is reachable but invalid |
| `403` | `AUTH_FORBIDDEN` | Missing provider permission |
| `404` | `IDENTITY_PROVIDER_NOT_FOUND` | Provider does not exist |
| `409` | `IDENTITY_PROVIDER_ISSUER_DUPLICATE` | Issuer is already configured |
| `409` | `IDENTITY_PROVIDER_ISSUER_IMMUTABLE` | PATCH attempted to change issuer |
| `409` | `IDENTITY_PROVIDER_DEFAULT_ROLE_FORBIDDEN` | Default Role has granting permissions or is `super_admin` |
| `503` | `AUTH_SSO_PROVIDER_UNAVAILABLE` | Discovery or configured endpoint cannot be reached |

Other federation codes are defined in `docs/api-contracts-auth.md` and `docs/api-contracts-users.md`.

## 6. Non-Goals
- Runtime creation of protocols or free-form provider adapters
- Provider-owned Role or Permission administration
- Continuous group or Role synchronization
- Storing IdP access or refresh tokens
- RP-initiated logout, back-channel logout, SCIM, SAML, or CAS

## 7. References
- `docs/business-identity-providers.md`
- `docs/api-contracts-auth.md`
- `docs/api-contracts-users.md`
- `docs/adr/0033-identity-federation.md`
