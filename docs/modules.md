# refraq Module Responsibilities

## 1. Goal

This document defines what each module is responsible for, what it may depend on, and what it must not absorb.

**Backend structure contract** (package tiers, published APIs, placement, dependency whitelist, enforcement): [`docs/backend-layout.md`](backend-layout.md). This file focuses on responsibilities and ownership; when they disagree on layout, `backend-layout.md` wins.

The layout covers the **Management Console**, **Management Foundation**, and **metadata foundation**. Later Data Product catalog / Entity modules arrive only with real code.

## 2. Backend Modules

### `backend/main.py`

Responsibilities:

- Create FastAPI app (composition root)
- Mount package routers (including health probes from `core`)
- Map `AppError`, validation errors, HTTPException, and unhandled exceptions to Problem Details
- Install request-id middleware (`X-Request-ID`)
- Run **Site Bootstrap** when stores are empty (seed roles + initial admin); must not realign System Role permissions on non-empty stores

Must not contain:

- Permission logic
- Data access logic
- Schema migrations
- Foundation Upgrade orchestration (belongs in `core/upgrade.py`)
- Probe route implementations (belong in `core`)
- Large request validation blocks

### `backend/core/`

Responsibilities:

- Shared kernel used by Foundation and capability packages
- `core/config.py`: environment-driven settings via pydantic-settings (Store Backend, backing-service URLs)
- `core/db.py`: SQLAlchemy `DeclarativeBase`, engine, and session factory for Postgres (sessions pin `TimeZone=UTC`)
- `core/time.py`: **unique Instant / Clock entry** — `Clock` / `utc_now`, Instant field type, `UtcDateTime`, format helpers; Schedule wall-clock DST helpers used by `worker`
- `core/redis_client.py`: Redis client factory for Session storage
- `core/secrets.py`: application secret encryption helpers
- `core/errors.py`: `AppError` (code + http_status) and HTTP Problem Details serialization
- `core/request_id.py`: `X-Request-ID` middleware helpers, log filter, Celery header transfer
- `core/upgrade.py`: **Foundation Upgrade** (advisory-locked Alembic migrate, then call domain System Role ensure, system schedules, and Type Mapping seeds); exit non-zero on failure
- `core/entry.py`: official product start path (run Foundation Upgrade, then serve); exit non-zero if upgrade fails (does not serve)
- Process probes (health/ready HTTP adapters)

Time contract: [`docs/conventions-time.md`](conventions-time.md), ADR [`0022`](adr/0022-unified-time-contract.md).
Error / request-id contract: [`docs/conventions-errors.md`](conventions-errors.md), ADR [`0023`](adr/0023-api-problem-details.md).

Must not contain:

- Business rules for what a System Role is (those live in `admin/`; `core` only orchestrates)
- Domain-specific ORM table definitions (those live in owning packages such as `admin/models.py`)
- Product-domain use-case HTTP
- Business Schedule Task ownership (lives in `worker/`; `core` only supplies Instant/DST primitives)

### `backend/admin/`

Responsibilities:

- Management Foundation platform kernel: auth, permission, cookie/deps, User/Role/Session/PAT/audit
- Foundation ORM (`admin/models.py`) and Foundation stores (`*_store.py`)
- Foundation HTTP adapters under `admin/routers/` and shapes under `admin/schemas/`
- Published API listed in [`docs/backend-layout.md`](backend-layout.md) §3

Recommended modules:

- `admin/models.py` (Foundation ORM tables)
- `admin/permissions.py`
- `admin/deps.py`
- `admin/security.py`
- `admin/console_modules.py` (code-seeded Console Module catalog)
- `admin/settings_override.py` (in-process Settings Override; not Store Backend)
- `admin/roles.py` (Role domain: System Role ensure, Site Bootstrap seed, write invariants)
- `admin/audit.py` (audit write facade)
- Foundation stores: `user_store`, `role_store`, `session_store`, `token_store`, `audit_store`

Must not contain:

- Source/catalog/structure-Job domain logic (belongs in `metadata/`)
- Platform Job table ownership (belongs in `jobs/`)
- Celery app / Beat / Scheduled Task (belongs in `worker/`)

Do not put Console Module catalog, Settings Override, or System Role ensure rules into `backend/core/`.
Do not pre-create empty packages for future capabilities before implementation.

### `backend/jobs/`

Responsibilities:

- Platform **Job** ORM (`jobs` table), store adapters, and lifecycle status machine
- Opaque generic `input` payload; no domain foreign keys as universal columns
- Shared helpers used by domain enqueue paths and the stuck-Job reaper
- Mechanism-resource HTTP (get/cancel by Job id) under `jobs/routers/`
- Published API in [`docs/backend-layout.md`](backend-layout.md) §3

Must not contain:

- Domain collector / Source facade HTTP (stay in `metadata/`)
- Celery app / Beat scheduler / Scheduled Task ownership (stay in `worker/`)

### `backend/metadata/`

Responsibilities:

- Source domain models and services (embedded reachability for database kinds)
- Connector adapters (PostgreSQL, MSSQL, Oracle); outbound invocation shell in `connectors/runtime`
- Domain facade for structure **Jobs** minted via **Scheduled Task** (run-now / Beat) and Source-scoped schedules (`POST/GET /sources/{id}/schedules`)
- Structure Job runtime in `structure_jobs/service` (`run_structure_job`: collect → Normalized Type → refresh → Structure Diff)
- Domain Celery work units (`@shared_task`); discovered by `worker`
- Catalog object / semantics / join / controlled query / Catalog Sample services (`catalog/service` owns browse, search, Join Path, and semantics/join writes; sample compile+run lives under `query/`; structure refresh orchestration in `catalog/structure_refresh`, plan merge in `catalog/structure_merge`, Join Origin policy in `catalog/join_origin`; persistence adapters only persist)
- Business Domain registry (global flat entity referenced by catalog objects)
- Type Mapping registry (global engine + native type → Normalized Type; product seeds via Upgrade)
- Domain use-case HTTP under `metadata/routers/` and shapes under `metadata/schemas/` (adapters only: auth + transport)
- MCP tool handlers (`backend/metadata/mcp_server.py`) that delegate to the same services

Must not contain:

- Owning the platform **Job** table (lives in `backend/jobs/`)
- Generic Settings / engine factories (stay in `core/`)
- Celery app / Beat scheduler ownership (stay in `worker/`)
- Session cookie issuance (stay in `admin/`)
- Importing `worker.app`
- Pre-scaffolded empty subpackages for Entity / Data Product catalog
- Single-language orchestration or persistence at the package root

### `backend/worker/`

Responsibilities:

- Celery application factory and process entry (`celery -A backend.worker.app`)
- **Scheduled Task** ORM, system schedule seed, and Postgres-backed Beat scheduler
- Mechanism Scheduled Task HTTP (`worker/routers/`: list/get/patch/delete)
- Platform system tasks (for example stuck **Job** reaper)
- Discover and register domain and platform task modules
- Bind Celery request-id header transfer (not a Job column)

Must not contain:

- Domain collector logic (stay in `metadata/`)
- Interactive Console HTTP routes (pages stay in `frontend/`; mechanism REST is allowed)

Deploy **one** Beat replica. See `docs/adr/0006-celery-platform-async-runtime.md` and `docs/env.md` §8.
Schedule Timezone / Instant rules: [`docs/conventions-time.md`](conventions-time.md).

### Celery worker process

Responsibilities:

- Consume Celery tasks (domain Jobs and platform system tasks) and run collectors/handlers
- Update **Job** status (and later catalog snapshots) in Postgres

Must not serve interactive Console HTTP traffic. Start commands: `docs/env.md` §8.

### `backend/alembic/`

Responsibilities:

- Schema migration scripts and Alembic environment
- Read `DATABASE_URL` from settings (or alembic.ini override) and apply revisions

Must not contain:

- Business rules
- Runtime request handling

Alembic must import every domain model module so autogenerate sees the full schema.

### `backend/tests/`

Responsibilities:

- Prove route behavior
- Prove auth error semantics
- Lock permission behavior before frontend integration
- Enforce layout/published-API import rules (`test_layout_imports.py` and friends)
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

See the whitelist in [`docs/backend-layout.md`](backend-layout.md) §7. Summary:

- `core` → no business packages except `upgrade` → published `admin` / `worker.api`
- `admin` → `core` (+ own modules)
- `jobs` → `core`; published `admin` when needed
- `metadata` → `core`; published `admin` and `jobs` only
- `worker` → `core`; published surfaces for assembly
- `main` → `core` + package routers / bootstrap via published surfaces
- `alembic` → `core` Base + every package `models` module

### Frontend

- `app/` → `features/`, `providers/`, `components/`, `lib/`
- `features/` → `providers/` (hooks/types only via Refine), `components/`, `lib/`
- `providers/` → `lib/`
- `components/` → `lib/` only for light helpers

## 5. Forbidden Coupling

- Do not import frontend files into backend
- Do not let persistence stores shape UI labels or page logic
- Do not let frontend components define the authoritative permission matrix
- Do not scatter login/session logic across many pages; keep it in providers and route guards
- Do not import `worker.app` from domain or HTTP adapters
- Do not subclass concrete `admin.errors` types from product domains or platform primitives (use `core.errors.AppError`)

## 6. First-Slice Ownership

For the login/permission slice, each concern should land here:

- Login API contract: `backend/admin/schemas/` + `backend/admin/routers/`
- Credential verification and session issuance: `backend/admin/`
- Session persistence and lookup: `backend/admin/session_store.py` (and related stores)
- Current-user fetch and logout wiring: `frontend/src/providers/`
- Login page UI: `frontend/src/app/login/`
- Protected layout behavior: `frontend/src/app/console/`
- User resource UI: `frontend/src/features/users/`
- Role resource UI: `frontend/src/features/roles/`
- Console navigation API: `backend/admin/routers/console.py` + `admin/console_modules.py`
- Platform settings API: `backend/admin/routers/settings.py` + `admin/settings_override.py`
- Settings UI: `frontend/src/features/settings/`
