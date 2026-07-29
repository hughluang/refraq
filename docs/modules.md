# refraq Module Responsibilities

## 1. Goal

This document defines what each module is responsible for, what it may depend on, and what it must not absorb.

The module layout below serves the current delivery slice: the **Management Console** and its **Management Foundation** (auth, session, permission). Product identity stays with Data Product Capabilities, which will add their own modules in later phases.

## 2. Backend Modules

### `backend/main.py`

Responsibilities:

- Create FastAPI app
- Register routers
- Expose health and framework-level startup configuration

Must not contain:

- Permission logic
- Data access logic
- Large request validation blocks

### `backend/config.py`

Responsibilities:

- Centralize environment-driven runtime settings
- Expose typed configuration for app startup and auth configuration

Must not contain:

- Business rules
- Derived per-request state

### `backend/routers/`

Responsibilities:

- Define HTTP routes
- Parse request data
- Map domain errors to HTTP responses
- Delegate actual work to domain/service/repository code

Must not contain:

- SQL or persistence details
- Hidden business rules that are not reused elsewhere

### `backend/schemas/`

Responsibilities:

- Define request and response models
- Keep API payload shape explicit

Must not contain:

- Persistence operations
- Permission decisions

### `backend/repositories/`

Responsibilities:

- Encapsulate data access
- Present clear interfaces for loading users, sessions, and future business resources

Must not contain:

- HTTP concerns
- UI-facing formatting logic

### `backend/admin/`

Responsibilities:

- Hold Management Foundation domain code (auth, permission, administrator management) that does not belong to generic transport or storage layers

Recommended subdomains for the first slice:

- `admin/auth.py`
- `admin/permissions.py`
- `admin/session.py`

### `backend/tests/`

Responsibilities:

- Prove route behavior
- Prove auth error semantics
- Lock permission behavior before frontend integration

Priority:

- API-level tests first
- Domain tests second

## 3. Frontend Modules

### `frontend/src/app/`

Responsibilities:

- Route tree
- Layouts
- Page entry files

Must not contain:

- Long-lived API client state
- Raw permission rules duplicated from backend

### `frontend/src/providers/`

Responsibilities:

- Bridge framework-level concerns into the app
- Auth provider
- Data provider
- Access-control provider
- i18n provider

This is the main integration layer for the first login/permission slice.

### `frontend/src/components/`

Responsibilities:

- Reusable UI building blocks
- Small presentation-focused components

Must not contain:

- Page-specific orchestration
- Permission truth

### `frontend/src/lib/`

Responsibilities:

- Shared API helpers
- Small framework-agnostic utility code

Must not contain:

- Page rendering
- Business workflows that belong in providers or pages

### `frontend/src/locales/`

Responsibilities:

- Language resources
- Stable translation keys

## 4. Allowed Dependencies

### Backend

- `main.py` -> `config.py`, `routers/`
- `routers/` -> `schemas/`, `admin/`, `repositories/`
- `admin/` -> `repositories/`, `schemas/` when needed
- `repositories/` -> storage adapters or in-memory data sources

### Frontend

- `app/` -> `providers/`, `components/`, `lib/`
- `providers/` -> `lib/`
- `components/` -> `lib/` only for light helpers

## 5. Forbidden Coupling

- Do not import frontend files into backend
- Do not let backend repositories shape UI labels or page logic
- Do not let frontend components define the authoritative permission matrix
- Do not scatter login/session logic across many pages; keep it in providers and route guards

## 6. First-Slice Ownership

For the login/permission slice, each concern should land here:

- Login API contract: `backend/schemas/` + `backend/routers/`
- Credential verification and session issuance: `backend/admin/`
- Session lookup: `backend/admin/` or `backend/repositories/`
- Current-user fetch and logout wiring: `frontend/src/providers/`
- Login page UI: `frontend/src/app/login/`
- Protected layout behavior: `frontend/src/app/(dashboard)/`
