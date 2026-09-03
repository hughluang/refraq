# refraq Architecture

## 1. Purpose

`refraq` is a **Data Product Integration Platform** (a Data Business Platform).
Its business identity is defined by **Data Product Capabilities**, which turn distributed source-system data into unified, consumable, and governable data outputs.

The **Management Console** and **Management Foundation** (login, session, roles, permissions) are delivered enabling capabilities, not the product identity. The next delivery phase is the **metadata foundation** (`docs/business-metadata.md`). Data Product catalog / Entity / Serving capabilities remain later.

This repository is intentionally split into:

- `backend/`: authoritative business rules, auth state, permission checks, API contracts
- `frontend/`: Management Console UI, route protection, user interaction, API consumption

## 2. System Boundary

### In Scope

The Management Foundation slice includes:

- User login (local password and OIDC federation; `identity_source=local|oidc`)
- Current-user query
- Logout
- Configurable Role + fixed Permission catalog
- Permission-based route and action control
- Persistent User/Role storage (Postgres) and shared Session storage (Redis)
- Official Foundation Upgrade (migrate under advisory lock, ensure System Role) and entrypoint (upgrade then serve)
- Dev dependency Compose and a published site Compose template (web + api + backing services; images from a version tag)

### Out of Scope For Foundation Phase (still true)

- Customer-facing Data Product catalog / Entity / Serving / Access marketplace
- Migration of legacy system code
- SAML, CAS, LDAP synchronization, MFA, and non-OIDC federation protocols
- Client / machine-token management APIs
- Empty pre-created domain packages before real code arrives
- Sliding session TTL and cross-origin browser access to the API

### In Scope For Metadata Foundation Phase

- Source registry (embedded reachability for database kinds), structure and join-detection **Jobs**, catalog browse, semantics, joins, controlled read-only query
- User PAT for API/MCP; Celery platform async runtime (Redis broker) + **Job** / Scheduled Task in Postgres; encrypted Source secrets; management-plane audit
- See `docs/business-metadata.md`

## 3. High-Level Topology

### Backend

The backend owns:

- Session issuance and invalidation
- Password verification
- User identity model
- Role and permission evaluation
- HTTP Problem Details for failures (unauthenticated, unauthorized, validation, unhandled); Request ID on every response ([`docs/conventions-errors.md`](conventions-errors.md))
- Schema migration and System Role ensure via Foundation Upgrade / official entrypoint (not app lifespan permission reconcile)
- Site Bootstrap on lifespan only when stores are empty (see `docs/adr/0003-foundation-upgrade-vs-bootstrap.md`)

### Frontend

The frontend owns:

- Login form and logout entry
- Protected page routing
- Fetching current user state
- Hiding or disabling actions based on permissions returned by backend
- Resolving locale-specific Site Branding from the backend's unresolved public maps and falling back to Refraq defaults when that read fails

### Deploy Shape

A site exposes the Management Console (web) to browsers and pulls published **linux/amd64** images pinned by the image tags in the GitHub Release compose attachment. It does not build from a source tree. The site API service must be named `api`.
The browser calls same-origin `/api`; Next.js rewrites to the internal API service.
`REFRAQ_API_UPSTREAM` identifies that internal API origin. The frontend image reads it at build time for rewrites, and the running Next.js server reads the same value for direct server-rendering calls such as Site Branding. Site compose sets both. Browser-visible URLs remain same-origin and never contain the internal upstream.
Same-origin `/mcp` is streamed by the web process to an internal MCP service (`REFRAQ_MCP_UPSTREAM`). Compose does not publish the MCP listen port. Process `readyz` stays on the MCP container network.
Postgres and Redis are **Backing Services**; app processes stay share-nothing.
The Session cookie's `Secure` flag follows browser-facing HTTPS stamped by the web `/api` rewrite (`REFRAQ_BROWSER_FACING_PROTO`, default `http`), not `REFRAQ_ENV` and not client-supplied `X-Forwarded-Proto`. HTTP sites must keep the Session. OIDC callback origin uses the same rewrite for proto plus `REFRAQ_BROWSER_FACING_HOST` (or a loopback Host when unset); client-supplied public `Host` values are not used as `redirect_uri`.

## 4. Auth Architecture

The Management Console uses server-managed sessions with cookie transport.

Reason:

- The existing frontend API helper already sends `credentials: "include"`
- This matches a same-site Management Console better than exposing bearer token handling in the browser
- It keeps browser auth small

Metadata foundation adds **User PAT** Bearer authentication for MCP and non-browser clients (`docs/business-user-tokens.md`). Session and PAT both resolve to a User and the same Permission catalog on HTTP APIs. HTTP MCP accepts PAT only. Client machine principals remain deferred.

### Session Flow

1. User submits account and password to backend
2. Backend verifies credentials and account status
3. Backend creates a session and returns current user summary
4. Backend sets an `HttpOnly` session cookie
5. Frontend calls `GET /auth/me` on refresh or protected-route entry
6. Backend derives current user from the session cookie
7. Logout invalidates session and clears cookie

Session expiry is absolute (set at creation; lookup does not renew TTL).

## 5. Permission Model

The first version uses RBAC with **Role** as a first-class entity.

- People are **User** records; each User has at most one Role (nullable).
- Permissions are chosen from a fixed catalog (`console:access`, `dashboard:read`, `users:*`, `roles:*`, `settings:*`, `branding:*`, plus `sources:*`, `metadata:*`, platform-mechanism `jobs:run`, `query:run`, `catalog:sample`, `tokens:*`, `audit:read`).
- Console side navigation is served from a backend-seeded module catalog (`GET /console/navigation`); Console Module Identity for SPA wiring/ACL is `GET /console/module-identities`. See `docs/adr/0002-console-navigation-catalog.md`.
- Seeded roles: locked `super_admin` (effective permissions = full catalog by identity) and editable `operator` (`console:access` + `dashboard:read` by default; metadata write/query/sample/token permissions are not implied).
- Machine principals are reserved as **Client** and remain out of scope; person-owned **User PAT** is in scope for metadata foundation.
- Console login requires the User's Role to include `console:access`.

Permission checks happen in backend first.
Frontend checks are only for UX and must never be treated as the final enforcement layer.

## 6. Request Path

1. Frontend page, MCP client, or provider calls the Console origin (`/api` to the API process; `/mcp` streamed to the MCP process)
2. API process resolves current User from Session cookie or User PAT; HTTP MCP resolves User PAT from `Authorization` only
3. Backend loads user role and permissions
4. Backend checks permission against requested resource/action
5. Backend returns:
   - `200` for allowed access
   - `401` if not authenticated
   - `403` if authenticated but lacking permission

## 7. Dependency Direction

The repository should follow these dependency rules:

- `frontend` depends on backend API contracts, never on backend source code
- `backend/routers` depends on `schemas` and service/repository logic
- `repositories` must not import frontend concepts
- Business rules must not be buried inside UI components

## 8. Persistence And Evolution

- Default **Store Backend** is `persistent` (Postgres for User/Role, Redis for Session).
- `memory` exists for automated tests only; missing URLs must not silently select memory.
- Shared infrastructure (settings, engine, `DeclarativeBase`, Redis, `AppError`) lives under `backend/core/`. Business ORM tables live in owning packages (Foundation: `backend/admin/`; metadata: `backend/metadata/`; platform Job: `backend/jobs/`; Celery/Scheduled Task: `backend/worker/`).
- Module layout stays a modular monolith with package tiers and published APIs: see `docs/backend-layout.md`. Add packages when real code arrives; do not pre-scaffold empty domain trees.
- Directory structure aids maintainability; multi-instance correctness depends on **Backing Services**, not sticky sessions.
- Structure and other long-running **Jobs** use an out-of-process queue and worker with Redis as broker (`docs/adr/0004-redis-queue-for-ingestion.md`); the default runtime is Celery (`docs/adr/0006-celery-platform-async-runtime.md`). Job shape: `docs/adr/0008-job-generic-input.md`. Source `access` is app-encrypted as a whole document (`docs/adr/0005-app-encrypted-connection-secrets.md`, `docs/adr/0011-encrypted-access-blob-and-connector-spec.md`).
- Catalog identity and database reachability are Source-scoped (`docs/adr/0007-source-owns-catalog-identity.md`, `docs/adr/0010-source-owns-access.md`).
- See `docs/adr/0001-postgres-redis-foundation-stores.md`.

### Port Configuration

Local convention: backend `127.0.0.1:8000`, browser same-origin `/api`, Next.js rewrite to the backend upstream. See `docs/env.md` §3.

## 9. Architecture Rule Summary

- Auth truth lives in backend
- UI protection is secondary to backend enforcement
- `refraq` stays independent from the old system
- Login, federation, session, and permission belong to the Management Foundation, not the product identity
- New features must fit the login/session/permission model (Session and/or User PAT) instead of inventing parallel auth flows
- Shared state belongs in Backing Services; grow modules with real capabilities only
- Metadata foundation precedes Data Product catalog work; do not dual-read external `dbmeta` as authority
