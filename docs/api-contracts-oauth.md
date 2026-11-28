# refraq API Contracts: OAuth Delegation

## 1. Purpose

This document defines the HTTP endpoints for **OAuth Client** administration, dual-mode delegated token issuance (`POST /oauth/token`), and RFC 8414 / RFC 9728 discovery metadata.

Related boundaries:

- Business rules: `docs/business-oauth-delegation.md`
- Identity Providers and SCIM: `docs/api-contracts-identity-providers.md`, `docs/api-contracts-scim.md`
- Entity MCP and Metadata MCP endpoints: `docs/api-contracts-entity-mcp.md`, `docs/api-contracts-metadata-mcp.md`
- Errors and request IDs: `docs/conventions-errors.md`
- Pagination: `docs/conventions-pagination.md`

## 2. Transport And Authorization

- Admin endpoints under `/oauth-clients` accept **Session** or **User PAT** (or API-scoped Delegated Access Token with matching permission), return JSON on success, and use RFC 9457 Problem Details on failure.
- `POST /oauth/token` accepts `application/x-www-form-urlencoded`, authenticates the OAuth Client, and returns RFC 6749 §5.2 JSON errors (`{"error", "error_description"}`) with `Cache-Control: no-store`.
- Discovery endpoints under `/.well-known/*` are public `GET` endpoints returning JSON.

## 3. OAuth Client Administration

Permissions: `oauth_client:read` for reads; `oauth_client:write` for mutations.

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `GET` | `/oauth-clients` | `oauth_client:read` | List OAuth Clients (**Offset Page**) |
| `POST` | `/oauth-clients` | `oauth_client:write` | Create an OAuth Client (returns one-time `client_secret` for secret-based clients) |
| `GET` | `/oauth-clients/{id}` | `oauth_client:read` | Read one OAuth Client |
| `PATCH` | `/oauth-clients/{id}` | `oauth_client:write` | Update client configuration or enabled state |
| `POST` | `/oauth-clients/{id}/rotate-secret` | `oauth_client:write` | Rotate `client_secret` for secret-based clients (returns plaintext once) |
| `DELETE` | `/oauth-clients/{id}` | `oauth_client:write` | Delete an OAuth Client and revoke its active tokens |

`GET /oauth-clients` returns an **Offset Page** ordered newest-first (`created_at DESC`, `id DESC`). Query params: `limit` (default **50**, max **200**), `offset` (default **0**), optional `q` (case-insensitive literal substring of `name` or `client_id`), optional `provider_id`, and optional `enabled`.

### 3.1 Client Resource Shape

```json
{
  "id": "ocl_0123456789ab",
  "client_id": "rfq_cid_0123456789abcdef",
  "name": "System A Assistant",
  "description": "Delegated Entity MCP access for System A",
  "provider_id": "idp_0123456789ab",
  "enabled": true,
  "token_endpoint_auth_method": "private_key_jwt",
  "jwks": null,
  "jwks_uri": "https://sys-a.example.com/.well-known/jwks.json",
  "secret_prefix": null,
  "client_secret_configured": false,
  "allowed_grant_types": [
    "urn:ietf:params:oauth:grant-type:jwt-bearer",
    "urn:ietf:params:oauth:grant-type:token-exchange"
  ],
  "allowed_subject_audiences": ["sys-a-oidc-client"],
  "allowed_surfaces": ["entity_mcp"],
  "allowed_scopes": ["entity:data_read"],
  "token_ttl_sec": 900,
  "created_at": "2026-11-28T00:00:00Z",
  "updated_at": "2026-11-28T00:00:00Z",
  "last_used_at": null
}
```

`POST /oauth-clients` returns `201` `{ "oauth_client": { … }, "client_secret": "rfq_cs_…" | null }`.
`POST /oauth-clients/{id}/rotate-secret` returns `200` `{ "oauth_client": { … }, "client_secret": "rfq_cs_…" }`.

## 4. Token Endpoint (`POST /oauth/token`)

Public path via Console rewrite: `POST /api/oauth/token`.

### 4.1 Client Authentication

- `private_key_jwt`: form fields `client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer` and `client_assertion=<JWT>` (optional `client_id` must match `sub`/`iss`).
- `client_secret_basic`: HTTP `Authorization: Basic <base64(client_id:client_secret)>`.
- `client_secret_post`: form fields `client_id` and `client_secret`.

### 4.2 Supported Grant Types

1. **ID-JAG**: `grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer` with `assertion=<ID-JAG JWT>`, optional `resource` (RFC 8707 URI), optional `scope`.
2. **Token Exchange**: `grant_type=urn:ietf:params:oauth:grant-type:token-exchange` with `subject_token=<IdP JWT>`, optional `resource` (RFC 8707 URI), optional `scope`.

### 4.3 Success Response (`200`)

```json
{
  "access_token": "rfq_oat_...",
  "token_type": "Bearer",
  "issued_token_type": "urn:ietf:params:oauth:token-type:access_token",
  "expires_in": 900,
  "scope": "entity:data_read"
}
```

## 5. Discovery Metadata Endpoints

- `GET /.well-known/oauth-authorization-server` and `GET /.well-known/oauth-authorization-server/api/oauth`:
  Returns RFC 8414 metadata including `issuer` (`{origin}/api/oauth`), `token_endpoint` (`{origin}/api/oauth/token`), `grant_types_supported`, `token_endpoint_auth_methods_supported`, `token_endpoint_auth_signing_alg_values_supported`, and `authorization_grant_profiles_supported: ["urn:ietf:params:oauth:grant-profile:id-jag"]`.
- `GET /.well-known/oauth-protected-resource/mcp/entity`, `GET /.well-known/oauth-protected-resource/mcp`, and `GET /.well-known/oauth-protected-resource/api`:
  Returns RFC 9728 metadata with `resource`, `authorization_servers: ["{origin}/api/oauth"]`, `bearer_methods_supported: ["header"]`, and `scopes_supported`.

## 6. Errors

Admin Problem Codes:

| Code | HTTP | When |
| --- | --- | --- |
| `OAUTH_CLIENT_NOT_FOUND` | 404 | OAuth Client does not exist |
| `OAUTH_CLIENT_CONFIG_INVALID` | 422 | Invalid auth method, JWKS private key material, grant types, surfaces, or scopes |
| `OAUTH_CLIENT_SCOPE_FORBIDDEN` | 409 | `allowed_scopes` contains `console:access`, `tokens:write`, or a granting permission |
| `OAUTH_CLIENT_SECRET_UNSUPPORTED` | 409 | Rotate secret called on a `private_key_jwt` client |

Token endpoint OAuth errors: `invalid_request` (400), `invalid_client` (401), `unauthorized_client` (400), `unsupported_grant_type` (400), `invalid_grant` (400), `invalid_target` (400), `invalid_scope` (400), `temporarily_unavailable` (503).

## 7. Non-Goals

- `GET /oauth/authorize` interactive consent endpoint
- Token introspection (`POST /oauth/introspect`) or revocation (`POST /oauth/revoke`) endpoints
- Dynamic Client Registration (`POST /oauth/register`)

## 8. References

- `docs/business-oauth-delegation.md`
- `docs/api-contracts-entity-mcp.md`
- `docs/api-contracts-metadata-mcp.md`
