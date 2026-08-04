# refraq Architecture

## 1. Purpose

`refraq` is a **Data Product Integration Platform** (a Data Business Platform).
Its business identity is defined by **Data Product Capabilities**, which turn distributed source-system data into unified, consumable, and governable data outputs.

Its first delivery target is the **Management Console** and the **Management Foundation**: User login, session management, configurable Role-based permissions, and permission-controlled backend access. These are enabling capabilities, not the product identity; Data Product Capabilities are delivered in later phases.

This repository is intentionally split into:

- `backend/`: authoritative business rules, auth state, permission checks, API contracts
- `frontend/`: Management Console UI, route protection, user interaction, API consumption

## 2. System Boundary

### In Scope

The Management Foundation slice includes:

- User login (people; `identity_source=local`)
- Current-user query
- Logout
- Configurable Role + fixed Permission catalog
- Permission-based route and action control
- Persistent User/Role storage (Postgres) and shared Session storage (Redis)
- Official Foundation Upgrade (migrate under advisory lock, ensure System Role) and entrypoint (upgrade then serve)
- Dev dependency Compose and a self-deploy Compose example (web + api + backing services)

### Out of Scope For Current Phase

- Customer-facing Data Product Capability features
- Migration of legacy system code
- SSO, OAuth, MFA, LDAP protocol integration, and third-party identity providers
- Client / Token management APIs
- Empty pre-created domain packages for future capabilities
- Sliding session TTL and cross-origin browser access to the API

## 3. High-Level Topology

### Backend

The backend owns:

- Session issuance and invalidation
- Password verification
- User identity model
- Role and permission evaluation
- HTTP error semantics for unauthenticated and unauthorized access
- Schema migration and System Role ensure via Foundation Upgrade / official entrypoint (not app lifespan permission reconcile)
- Site Bootstrap on lifespan only when stores are empty (see `docs/adr/0003-foundation-upgrade-vs-bootstrap.md`)

### Frontend

The frontend owns:

- Login form and logout entry
- Protected page routing
- Fetching current user state
- Hiding or disabling actions based on permissions returned by backend

### Deploy Shape

Self-deploy exposes the Management Console (web) to browsers.
The browser calls same-origin `/api`; Next.js rewrites to the internal API service.
`REFRAQ_API_UPSTREAM` is fixed at frontend image build time for deploy.
Postgres and Redis are **Backing Services**; app processes stay share-nothing.

## 4. Auth Architecture

The first version uses server-managed sessions with cookie transport.

Reason:

- The existing frontend API helper already sends `credentials: "include"`
- This matches a same-site Management Console better than exposing bearer token handling in the browser
- It keeps the first implementation smaller

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
- Permissions are chosen from a fixed catalog (`console:access`, `dashboard:read`, `users:*`, `roles:*`, `settings:*`).
- Console side navigation is served from a backend-seeded module catalog (`GET /console/navigation`); Console Module Identity for SPA wiring/ACL is `GET /console/module-identities`. See `docs/adr/0002-console-navigation-catalog.md`.
- Seeded roles: locked `super_admin` (full catalog) and editable `operator` (`console:access` + `dashboard:read`).
- Machine principals are reserved as **Client** and are out of scope for this slice.
- Console login requires the User's Role to include `console:access`.

Permission checks happen in backend first.
Frontend checks are only for UX and must never be treated as the final enforcement layer.

## 6. Request Path

1. Frontend page or provider calls backend API
2. Backend resolves current session
3. Backend loads user role and permissions
4. Backend checks permission against requested resource/action
5. Backend returns:
   - `200` for allowed access
   - `401` if not logged in
   - `403` if logged in but lacking permission

## 7. Dependency Direction

The repository should follow these dependency rules:

- `frontend` depends on backend API contracts, never on backend source code
- `backend/routers` depends on `schemas` and service/repository logic
- `repositories` must not import frontend concepts
- Business rules must not be buried inside UI components

## 8. Persistence And Evolution

- Default **Store Backend** is `persistent` (Postgres for User/Role, Redis for Session).
- `memory` exists for automated tests only; missing URLs must not silently select memory.
- Shared infrastructure (settings, engine, `DeclarativeBase`, Redis) lives under `backend/core/`. Business ORM tables live in domain packages (Foundation: `backend/admin/models.py`); add further vertical-slice packages when Data Product Capabilities arrive rather than a global models tree.
- Module layout stays a modular monolith: add capability packages when real code arrives; do not pre-scaffold empty domain trees.
- Directory structure aids maintainability; multi-instance correctness depends on **Backing Services**, not sticky sessions.
- See `docs/adr/0001-postgres-redis-foundation-stores.md`.

### Port Configuration

Local convention: backend `127.0.0.1:8000`, browser same-origin `/api`, Next.js rewrite to the backend upstream. See `docs/env.md` §3.

## 9. Architecture Rule Summary

- Auth truth lives in backend
- UI protection is secondary to backend enforcement
- `refraq` stays independent from the old system
- Login, session, and permission belong to the Management Foundation, not the product identity
- New features must fit the login/session/permission model instead of inventing parallel auth flows
- Shared state belongs in Backing Services; grow modules with real capabilities only
