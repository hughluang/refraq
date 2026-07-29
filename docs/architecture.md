# refraq Architecture

## 1. Purpose

`refraq` is a **Data Product Integration Platform** (a Data Business Platform).
Its business identity is defined by **Data Product Capabilities**, which turn distributed source-system data into unified, consumable, and governable data outputs.

Its first delivery target is the **Management Console** and the **Management Foundation**: administrator login, session management, and permission-controlled backend access. These are enabling capabilities, not the product identity; Data Product Capabilities are delivered in later phases.

This repository is intentionally split into:

- `backend/`: authoritative business rules, auth state, permission checks, API contracts
- `frontend/`: Management Console UI, route protection, user interaction, API consumption

## 2. System Boundary

### In Scope

The first slice implements the Management Foundation:

- Administrator login
- Current-user query
- Logout
- Permission-based route and action control
- Future management resource handling under the same auth model

### Out of Scope For Current Phase

- Customer-facing product features
- Migration of legacy system code
- Docker / compose integration
- ORM and Alembic
- SSO, OAuth, MFA, and third-party identity providers

## 3. High-Level Topology

### Backend

The backend owns:

- Session issuance and invalidation
- Password verification
- User identity model
- Role and permission evaluation
- HTTP error semantics for unauthenticated and unauthorized access

### Frontend

The frontend owns:

- Login form and logout entry
- Protected page routing
- Fetching current user state
- Hiding or disabling actions based on permissions returned by backend

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

## 5. Permission Model

The first version uses RBAC.

Recommended initial roles:

- `super_admin`: full access, including administrator management
- `operator`: operational write access to business resources, no admin-user management
- `viewer`: read-only access

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

## 8. Initial Technical Risks

### Port Configuration Drift

Current backend example uses port `8000`, but frontend example uses base URL `6068`.
This must be unified before first real integration.

### Placeholder Infrastructure

There is no database layer, migration system, or persistent session store yet.
The first auth implementation should therefore keep interfaces small enough to evolve later.

## 9. Architecture Rule Summary

- Auth truth lives in backend
- UI protection is secondary to backend enforcement
- `refraq` stays independent from the old system
- Login, session, and permission belong to the Management Foundation, not the product identity
- New features must fit the login/session/permission model instead of inventing parallel auth flows
