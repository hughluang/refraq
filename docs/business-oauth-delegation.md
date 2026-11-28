# refraq Business Rules: OAuth Delegation

## 1. Scope

This document defines cross-system OAuth 2.0 user delegation for `refraq`: registered **OAuth Client**s, dual-mode token issuance (`ID-JAG` JWT Authorization Grant and RFC 8693 Token Exchange), short-lived opaque **Delegated Access Token**s (`rfq_oat_`), RFC 8707 canonical resource audience restriction, RFC 9728 / RFC 8414 discovery metadata, headless **External Subject** admission, and instant revocation on **User** disablement.

Related boundaries:

- Identity Providers, OIDC federation, and SCIM 2.0 provisioning: `docs/business-identity-providers.md`, `docs/api-contracts-scim.md`
- OAuth HTTP endpoints and client CRUD: `docs/api-contracts-oauth.md`
- Login, Session, Role, and Permission catalog: `docs/business-login-auth.md`
- User PAT: `docs/business-user-tokens.md`
- Entity MCP and Metadata MCP surfaces: `docs/api-contracts-entity-mcp.md`, `docs/api-contracts-metadata-mcp.md`
- Terminology: `docs/glossary.md`

## 2. Purpose And Principal Model

An external application that shares an **Identity Provider** with `refraq` exchanges a signed user identity assertion for a short-lived **Delegated Access Token** (`rfq_oat_`). The token acts on behalf of the resolved **User** and never grants authority beyond the intersection of:

1. the User's current **Role** effective **Permission**s,
2. the registered **OAuth Client**'s `allowed_scopes`,
3. the requested `scope` (when provided), and
4. the target **Resource Surface** permission ceiling.

`console:access` is always stripped from Delegated Access Tokens. A Delegated Access Token cannot sign in to the Management Console.

Every authenticated request resolves to an immutable `Principal` bound to a single **Resource Surface** (`/api`, `/mcp`, or `/mcp/entity`) with pre-intersected `effective_permissions`. Background worker threads invoked through platform admission carry the `Principal` by value so scope ceilings and credential ids (`oat_<12hex>` or `pat_<12hex>`) never drop across thread boundaries.

## 3. OAuth Client Model

An **OAuth Client** represents one trusted relying application registered under a single **Identity Provider** (`provider_id`).

| Field | Rule |
| --- | --- |
| `id` | Server-issued `ocl_` plus 12 lowercase hex characters |
| `client_id` | Server-issued `rfq_cid_` plus 16 lowercase hex characters, unique and immutable |
| `name` | Trimmed, 1 to 128 characters |
| `provider_id` | Foreign key to an existing Identity Provider (`ON DELETE RESTRICT`) |
| `token_endpoint_auth_method` | `private_key_jwt`, `client_secret_basic`, or `client_secret_post` |
| `jwks` / `jwks_uri` | Required (exactly one or both) for `private_key_jwt`; private key parameters (`d`, `p`, `q`, `dp`, `dq`, `qi`, `oth`, `k`) are rejected |
| `secret_hash` / `secret_prefix` | Generated on create or rotate for `client_secret_*` clients; plaintext `rfq_cs_...` returned once |
| `allowed_grant_types` | Non-empty subset of `urn:ietf:params:oauth:grant-type:jwt-bearer` and `urn:ietf:params:oauth:grant-type:token-exchange` |
| `allowed_subject_audiences` | Required and non-empty when `token-exchange` is allowed; matches upstream `subject_token` `aud` |
| `allowed_surfaces` | Non-empty subset of `entity_mcp`, `metadata_mcp`, and `api` |
| `allowed_scopes` | Non-empty subset of the fixed Permission catalog; must not contain `console:access`, `tokens:write`, or any granting permission (`users:write`, `roles:write`, `identity_providers:write`, `entity:access_manage`, `sources:access_manage`, `oauth_client:write`) |
| `token_ttl_sec` | Optional integer in `[60, 3600]`; defaults to System Parameter `oauth_access_token_ttl_sec` (seed `900`) |
| `enabled` | Disabling a client immediately blocks exchanges and revokes its active Delegated Access Tokens |

Permissions:

- `oauth_client:read`: list and inspect OAuth Clients (never returns secrets)
- `oauth_client:write`: create, update, rotate secrets, and delete OAuth Clients; classified as a granting permission and forbidden on Identity Provider auto-provisioning default Roles

## 4. Dual-Mode Token Issuance

`POST /oauth/token` (publicly `/api/oauth/token`) supports two delegation profiles:

1. **ID-JAG (`urn:ietf:params:oauth:grant-type:jwt-bearer`)**: aligns with MCP 2026-07-28 Enterprise-Managed Authorization (`draft-ietf-oauth-identity-assertion-authz-grant`). Requires JOSE header `typ=oauth-id-jag+jwt`, asymmetric signature verified against the Identity Provider's JWKS (`RS256/384/512`, `ES256/384/512`), `iss == provider.issuer`, single-value `aud == {origin}/api/oauth`, matching `client_id` claim when present, and single-use `jti` replay protection.
2. **Token Exchange (`urn:ietf:params:oauth:grant-type:token-exchange`)**: aligns with RFC 8693 for Identity Providers that do not yet mint ID-JAG assertions. Verifies the asymmetric signature of `subject_token` against the Identity Provider's JWKS, checks `iss == provider.issuer`, and requires `aud` (and `azp` when present) to match `client.allowed_subject_audiences`.

Client authentication enforces exact method matching. For `private_key_jwt`, the assertion must be asymmetrically signed by a key in `client.jwks` or `client.jwks_uri`, satisfy `iss == sub == client.client_id`, `aud` in `{origin}/api/oauth` or `{origin}/api/oauth/token`, lifetime at most 300 seconds, and pass single-use `jti` replay protection.

## 5. Resource Binding And Discovery

- Canonical resource URIs follow RFC 8707 under the trusted site origin (`VerifiedOrigin`): `{origin}/mcp/entity`, `{origin}/mcp`, and `{origin}/api`.
- A Delegated Access Token is bound to one or more canonical resource surfaces permitted by the client. Presenting an `/mcp/entity` token to `/mcp` or `/api` returns HTTP `401`.
- Authorization Server metadata (RFC 8414) is served at `/.well-known/oauth-authorization-server` and `/.well-known/oauth-authorization-server/api/oauth`.
- Protected Resource Metadata (RFC 9728) is served at `/.well-known/oauth-protected-resource/mcp/entity`, `/.well-known/oauth-protected-resource/mcp`, and `/.well-known/oauth-protected-resource/api`.
- Unauthenticated MCP requests return HTTP `401` with `WWW-Authenticate: Bearer resource_metadata="{origin}/.well-known/oauth-protected-resource/{surface}"` when a trusted origin is available.

## 6. Headless Admission And Instant Revocation

- Delegated token issuance uses headless admission (`mode=headless_oauth`): it does **not** require `console:access` on the User's Role or on the provider's `default_role_id`.
- When `auto_provision` is enabled on the Identity Provider, an unbound External Subject passing `group_allowlist` and account availability is provisioned atomically with `identity_source=oidc` and `default_role_id`. Unadmitted headless attempts are audited and rejected without writing to the interactive **Pending Identity** queue.
- Scoped `group_mappings` on the Identity Provider synchronize only the mapped **User Group**s without disturbing manually assigned groups.
- Disabling a User through any path (Console status change, Identity Provider disable/delete cascade, or SCIM `active=false` / `DELETE`) runs through the single User lifecycle seam and immediately clears all active Sessions and revokes all active Delegated Access Tokens for that User.

## 7. Audit

- OAuth Client create, update, secret rotation, and delete write Management Audit Events (`resource_type=oauth_client`).
- Token exchange writes `resource_type=oauth_token`, `action=token_exchange` carrying `actor_user_id`, `actor_token_id` (`oat_<12hex>`), `client_id`, `provider_id`, `grant_type`, `scopes`, and `surfaces`, never plaintext assertions or secrets.
- Downstream Entity data reads via a Delegated Access Token record `pat_id = oat_<12hex>` in the Entity Access Log.

## 8. Non-Goals

- Interactive OAuth 2.1 authorization-code consent screens or Dynamic Client Registration (RFC 7591)
- Refresh tokens or client-credentials machine-only tokens without a human User subject
- DPoP sender-constrained access tokens (RFC 9449)
- OpenID Shared Signals Framework (SSF) / CAEP 1.0 real-time event streams

## 9. References

- `docs/api-contracts-oauth.md`
- `docs/api-contracts-scim.md`
- `docs/business-identity-providers.md`
- `docs/business-login-auth.md`
- `docs/api-contracts-entity-mcp.md`
- `docs/api-contracts-metadata-mcp.md`
