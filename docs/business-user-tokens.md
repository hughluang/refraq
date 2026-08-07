# refraq Business Rules: User PAT

## 1. Scope

This document defines **User PAT** (personal access token) rules for non-browser access to refraq APIs and MCP.

Related:

- Session / login: `docs/business-login-auth.md`
- Metadata foundation consumers: `docs/business-metadata.md`
- API shapes: `docs/api-contracts-tokens.md`
- Terminology: `docs/glossary.md`

Client (machine principal) credential management remains out of scope.

## 2. Decision

- Management Console continues to use server-managed **Session** cookies.
- Agents, scripts, and MCP clients use **User PAT** with `Authorization: Bearer <token>`.
- A PAT authenticates a **User** and evaluates the same Role **Permission** catalog as Session-backed requests.
- Do not reuse the Session id as a Bearer token.
- Do not model PAT as a **Client**.

## 3. Token Model

| Field | Notes |
| --- | --- |
| id | Stable id |
| user_id | Owning User |
| name | Operator-visible label |
| token_hash | Server-side hash only; plaintext shown once at creation |
| prefix | Non-secret prefix for identification in lists |
| scopes | Optional future narrowing; v1 inherits full Role permissions |
| expires_at | Required expiry |
| revoked_at | Null until deactivated; cleared on restore |
| deleted_at | Null until soft-deleted; never cleared |
| created_at / last_used_at | Operational |

Rules:

- Plaintext token is returned **only** in the create response.
- List/get APIs return metadata never the secret.
- List APIs omit soft-deleted tokens (`deleted_at` set); management APIs treat them as not found.
- **Deactivate** sets `revoked_at` and is immediate for subsequent requests; **restore** clears `revoked_at`.
- **Delete** is allowed only while the token is deactivated (`revoked_at` set). It is soft: sets `deleted_at`, hides the token from the UI/list, keeps the row in the database, and cannot be restored through the product surface.
- Expired, deactivated, or soft-deleted tokens yield `401` with a distinct stable error code.
- Disabled Users cannot authenticate with PAT.
- Users without `console:access` may still use PAT for permitted API/MCP calls if their Role includes the relevant resource permissions; Console login rules are unchanged.

## 4. Permissions And Console Surface

| Permission | Meaning |
| --- | --- |
| `tokens:read` | List own PAT metadata |
| `tokens:write` | Create, deactivate, restore, and soft-delete (deactivated only) own PATs |

- Users manage **only their own** tokens in this phase (no admin impersonation API).
- Console Module id: `tokens` remains for Refine ACL / module identity (`tokens:read` / `tokens:write`).
- **User PAT** UI lives in **Account Center** (`docs/business-account.md`); it is **not** a sidebar navigation item and has no Console page route (`routes.list` is null).
- Account Center shell access does not require `tokens:*`; the Token section is shown only when the caller has `tokens:read`.

## 5. Transport And Auth Resolution

- Protected endpoints accept **either** valid Session cookie **or** valid User PAT Bearer.
- Exactly one principal resolution path per request; do not mix partial credentials in conflicting ways.
- MCP tools use the same resolution and Permission checks.
- Audit events for PAT create/deactivate/restore/delete and for actions performed via PAT record the User id (and token id where relevant, never plaintext).

## 6. Non-Goals

- OAuth2 / OIDC authorization code flows
- Refresh-token pairs as a separate product surface
- Client credentials / machine tokens
- Admin listing of all users’ plaintext-capable tokens
- Scope narrowing UI (may be added later; v1 = Role permissions)
- Hard-delete or admin restore of soft-deleted PATs

## 7. References

- `docs/api-contracts-tokens.md`
- `docs/api-contracts-auth.md` (Session remains cookie-based)
- `docs/business-account.md`
- `docs/business-metadata.md`
