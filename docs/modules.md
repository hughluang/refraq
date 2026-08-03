# refraq Module Responsibilities

## 1. Goal

This document defines what each module is responsible for, what it may depend on, and what it must not absorb.

The module layout below serves the current delivery slice: the **Management Console** and its **Management Foundation** (auth, session, permission). Product identity stays with Data Product Capabilities, which will add their own modules in later phases.

## 2. Backend Modules

### `backend/main.py`

Responsibilities:

- Create FastAPI app
- Register routers (including health probes)
- Run idempotent seed when stores are empty

Must not contain:

- Permission logic
- Data access logic
- Schema migrations
- Probe route implementations (belong in `routers/health.py`)
- Large request validation blocks

### `backend/core/`

Responsibilities:

- Shared infrastructure used by Foundation and future capability packages
- `core/config.py`: environment-driven settings via pydantic-settings (Store Backend, backing-service URLs)
- `core/db.py`: SQLAlchemy `DeclarativeBase`, engine, and session factory for Postgres
- `core/redis_client.py`: Redis client factory for Session storage
- `core/entry.py`: official product start path (advisory-locked Alembic upgrade, then serve); exit non-zero on lock timeout or migration failure

Must not contain:

- Business rules
- HTTP route handlers
- Domain-specific ORM table definitions (those live in domain packages such as `admin/models.py`)

### `backend/admin/models.py`

Responsibilities:

- Define Foundation ORM table models (User, Role) against the shared `DeclarativeBase` in `core/db.py`
- Register tables onto `Base.metadata` for Alembic autogenerate

Must not contain:

- API request/response shapes (those belong in `schemas/`)
- Engine/session/Redis wiring (those belong in `core/`)

Future Data Product Capabilities add their own `<capability>/models.py` the same way. Alembic must import every domain model module so autogenerate sees the full schema.

### `backend/alembic/`

Responsibilities:

- Schema migration scripts and Alembic environment
- Read `DATABASE_URL` from settings (or alembic.ini override) and apply revisions

Must not contain:

- Business rules
- Runtime request handling

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

- Encapsulate data access for User, Role, and Session
- Present clear ports with `memory` and `persistent` adapters

Must not contain:

- HTTP concerns
- UI-facing formatting logic
- Auth policy decisions (belong in `admin/`)

### `backend/admin/`

Responsibilities:

- Hold Management Foundation domain code (auth, permission, cookie/deps) that does not belong to generic transport or storage layers

Recommended subdomains for the first slice:

- `admin/models.py` (Foundation ORM tables)
- `admin/permissions.py`
- `admin/deps.py`
- `admin/security.py`

Must not own Session persistence implementations (those live under `repositories/`).

Do not pre-create empty packages for future Data Product Capabilities.

### `backend/tests/`

Responsibilities:

- Prove route behavior
- Prove auth error semantics
- Lock permission behavior before frontend integration
- Optional `@pytest.mark.integration` against local Compose Postgres/Redis (isolated `refraq_test` + Redis DB `1`)

Priority:

- API-level tests first (default `memory` Store Backend)
- Domain tests second
- Integration tests third (local only in this slice)

## 3. Frontend Modules

### `frontend/src/app/`

Responsibilities:

- Route tree
- Layouts
- Thin page entry files (prefer re-exporting from `features/`)

Must not contain:

- Long-lived API client state
- Raw permission rules duplicated from backend
- Large resource CRUD orchestration (belongs in `features/`)

### `frontend/src/features/`

Responsibilities:

- Resource-scoped UI slices (types, list/create/edit views)
- Page-level orchestration that uses Refine hooks

Must not contain:

- Framework provider wiring (belongs in `providers/`)
- Authoritative permission matrix (backend remains source of truth)

### `frontend/src/providers/`

Responsibilities:

- Bridge framework-level concerns into the app
- Auth provider
- Data provider
- Access-control provider
- i18n provider (create the Refine adapter inside a `react-i18next` / `next-i18next` subscriber such as `RefineRoot`; `changeLocale` must use `useChangeLanguage`; do not remount the tree with a locale `key` to refresh UI)
- Notification provider

This is the main integration layer for the first login/permission slice.

### `frontend/src/components/`

Responsibilities:

- Reusable UI building blocks
- Shared layout shells and feedback primitives

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

Locale set is open-ended and owned by `frontend/src/providers/locale-catalog.ts` (code + native label). That catalog feeds i18next `supportedLngs` and the language switcher (catalog-driven Menu).

Preference persistence uses a **cookie** `refraq.locale` (via `next-i18next` `createProxy` + `useChangeLanguage`). Detection order is **cookie → `NEXT_PUBLIC_DEFAULT_LOCALE` (fallback)**; do **not** use navigator, Accept-Language, query, or localStorage for negotiation. `localStorage` is no longer read after migration; a one-time client bridge may copy a legacy `localStorage` value into the cookie on first load, then clear it.

Integration: `frontend/i18n.config.ts` + `next-i18next` (`createProxy`, `getT` / `getResources`) wrapped by `frontend/src/providers/app-i18n-provider.tsx`. SSR hydrates only the current language via `getResources`; the client injects a custom `I18nProvider` `use` backend (`i18next-resources-to-backend` + dynamic `import` of `locales/<lng>/<ns>.json`, same source as `resourceLoader`) so other locales load on demand when switching. The Refine i18n adapter is still created inside a client subscriber (`RefineRoot`); do not remount the tree with a locale `key` to refresh UI. Locale switching must go through `useChangeLanguage` (cookie + server re-render), not a bare `i18n.changeLanguage`.

To add a locale: add `locales/<code>/common.json`, register it in `i18n.config.ts` `resourceLoader` / `supportedLngs` (via `LOCALE_CATALOG`), and append one row to `LOCALE_CATALOG`.

## 4. Allowed Dependencies

### Backend

- `core/entry.py` -> `core/config`, Alembic, ASGI app (`backend.main`)
- `main.py` -> `core/`, `routers/`, `repositories/`
- `alembic/` -> `core/` (Base) + import every domain `models` module
- `routers/` -> `schemas/`, `admin/`, `repositories/`
- `admin/` -> `repositories/`, `schemas/` when needed; may use `core/` for settings; owns Foundation ORM in `admin/models.py`
- `repositories/` -> `core/` (db/redis), domain models (e.g. `admin.models`), and memory adapters

### Frontend

- `app/` -> `features/`, `providers/`, `components/`, `lib/`
- `features/` -> `providers/` (hooks/types only via Refine), `components/`, `lib/`
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
- Session persistence and lookup: `backend/repositories/`
- Current-user fetch and logout wiring: `frontend/src/providers/`
- Login page UI: `frontend/src/app/login/`
- Protected layout behavior: `frontend/src/app/console/`
- User resource UI: `frontend/src/features/users/`
- Role resource UI: `frontend/src/features/roles/`
