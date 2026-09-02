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
- `core/pagination.py`: Offset Page query dependency (`page_params`) and envelope (`OffsetPage`)
- `core/upgrade.py`: **Foundation Upgrade** (advisory-locked Alembic migrate, then call domain System Role ensure, system schedules, and Type Mapping seeds); exit non-zero on failure
- `core/entry.py`: official product start path (run Foundation Upgrade, then serve); exit non-zero if upgrade fails (does not serve)
- Process probes (health/ready HTTP adapters)

Time contract: [`docs/conventions-time.md`](conventions-time.md), ADR [`0022`](adr/0022-unified-time-contract.md).
Error / request-id contract: [`docs/conventions-errors.md`](conventions-errors.md), ADR [`0023`](adr/0023-api-problem-details.md).
Pagination contract: [`docs/conventions-pagination.md`](conventions-pagination.md), ADR [`0029`](adr/0029-offset-page-as-platform-list-envelope.md).

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
- `admin/branding/` (Site Branding language unit: singleton configuration, packaged seed files, operator overlays, resolution-independent presentation, validation, caching, and HTTP)
- `admin/model_services/` (Model Service registry, purpose vector state, connectivity test, and HTTP)
- `admin/system_parameters/` (System Parameter mechanism: registry, store, resolver, occupy, HTTP)
- `admin/federation/` (Identity Provider configuration, OIDC validation, binding, pending admission, claim, and unfederation)
- `admin/parameters.py` (admin-owned System Parameter specs and typed accessors)
- `admin/roles.py` (Role domain: System Role ensure, Site Bootstrap seed, write invariants)
- `admin/audit.py` (audit write facade)
- Foundation stores: `user_store`, `role_store`, `session_store`, `token_store`, `audit_store`

Must not contain:

- Source/catalog/structure-Job domain logic (belongs in `metadata/`)
- Platform Job table ownership (belongs in `jobs/`)
- Celery app / Beat / Scheduled Task (belongs in `worker/`)

Do not put Console Module catalog, System Parameter mechanism, or System Role ensure rules into `backend/core/`.
The mechanism package must not name an occupancy window, a Beat loop, or a Session.
Do not pre-create empty packages for future capabilities before implementation.

### `backend/jobs/`

Responsibilities:

- Platform **Job** ORM (`jobs` table), store adapters, and lifecycle status machine
- Opaque generic `input` payload; no domain foreign keys as universal columns
- `jobs/parameters.py` (Job-owned System Parameter specs and typed accessors)
- Shared helpers used by domain enqueue paths and the stuck-Job reaper
- Job observation presentation (`present_jobs`: trigger actor / schedule names); Scheduled Task name lookup is an injected adapter
- Mechanism-resource HTTP (get/cancel by Job id) under `jobs/routers/`
- Published API in [`docs/backend-layout.md`](backend-layout.md) §3

Must not contain:

- Domain collector / Source facade HTTP (stay in `metadata/`)
- Celery app / Beat scheduler / Scheduled Task ownership (stay in `worker/`)
- Importing `worker` (Scheduled Task names are an injected adapter, bound by composition)

### `backend/metadata/`

Responsibilities:

- Source domain models and services (embedded reachability for database kinds); `sources.access` interprets Connector Spec (validate / seal / project / endpoint)
- Connector adapters (PostgreSQL, MSSQL, Oracle) consume `SourceEndpoint`; outbound invocation shell in `connectors/runtime` binds an already-interpreted endpoint
- Domain facade for structure and join-detection **Jobs** minted via **Scheduled Task** (run-now / Beat) and Source-scoped schedule **facade** (`POST/GET /sources/{id}/schedules`, `owner_ref` withdraw). Does not own the Scheduled Task table
- Source work Job execution shell in `source_job_runner` (`run_source_work_job`: claim, kind check, **Kind execution lock** with memory / Postgres adapters, Source lookup and usability). `source_jobs` mints; kind bodies live in `structure_jobs/service` (`run_structure_job`: collect → Normalized Type → structure refresh) and `join_detection_jobs/` (parse stored DDL → resolve column endpoints → insert missing joins)
- Domain Celery work units (`@shared_task`); discovered by `worker`: structure and join-detection minting in `source_jobs`, `catalog_embed` mint/runner in `catalog_embed_jobs`, Job kind dispatch in `tasks.py`
- Catalog object / semantics / join / controlled query / Catalog Sample services (`catalog/service` owns Current catalog reads + Join Path; Object Semantics in `catalog/semantics`; join list/writes in `catalog/join_writes` (human/MCP adapter: validation, audit, contract errors); directed join-pair admission and insert-if-missing persist in `catalog/join_pair` (`pair_state`, writer mapping, `apply_insert_join`); Join Origin attester constants in `catalog/join_origin`; views/refs internal; HTTP/MCP object projection in `catalog/present`; sample compile+run lives under `query/`; structure refresh orchestration in `catalog/structure_refresh` commits Current catalog and Structure Diff via catalog `catalog_write` primitives + Diff persist; plan merge in `catalog/structure_merge`; Join Change records in `catalog/join_changes` (adapters persist); Semantics Change in `catalog/semantics_changes`; optional Catalog Search hybrid in `catalog/embedding` / `catalog/search_hybrid` / `catalog/index_embeddings`; persist-plan walk in `catalog/structure_persist` (`apply_structure_plan` / `apply_join_detection_plan`; join step calls `join_pair`; adapters translate records); list predicates in `catalog/list_query` (Memory applies the spec in Python; SQL asks the same module for WHERE via a column protocol); search rank/page in `catalog/search_rank`; catalog store exposes narrow Protocols — `CatalogReadStore` / `CatalogSemanticsStore` / `CatalogJoinStore` / `CatalogStructureStore` (+ `CatalogGraphStore` for Join Path BFS) — while memory/SQL adapters remain one class each)
- Business Domain registry (global flat entity referenced by catalog objects)
- Type Mapping registry (global engine + native type → Normalized Type; product seeds via Upgrade)
- Domain use-case HTTP under `metadata/routers/` and shapes under `metadata/schemas/` (adapters only: auth + transport)
- MCP tool catalog (`mcp_catalog.py`) shared by `GET /mcp/catalog` and `tools/list`
- MCP tool handlers (`backend/metadata/mcp_server.py`) that delegate to the same services
- Product MCP HTTP process (`python -m backend.metadata.mcp_http`): Streamable HTTP at `/mcp`, PAT header only, intranet `GET /readyz`

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
- `worker/parameters.py` (composition `assemble_system_parameters`, Beat in-code constants, reaper interval derived from lost-detection)
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
- Shared layout shells and feedback primitives (`PageChrome`, remaining-space `FillColumn`, `ListTable`, `CreateListAction`, `ConfirmActionModal`)

Must not contain:

- Page-specific orchestration
- Permission truth

### `frontend/src/lib/`

Responsibilities:

- Shared API helpers
- Small framework-agnostic utility code
- Offset Page types and page-math helpers (`lib/pagination.ts`); paged-list generation / reset / load results live in `lib/paged-list-session.ts`; list status decisions live in `lib/list-state.ts` (`listPresentationOf` returns `{ state, refreshing }`); Console Offset Page fetch state is `hooks/usePagedList.ts`; HTTP Console lists use `hooks/useConsolePagedList.ts`; `components/display/ListTable.tsx` binds the session and composes `ListPager`

Must not contain:

- Page rendering
- Business workflows that belong in providers or pages

### `frontend/src/locales/`

Responsibilities:

- Language resources
- Stable translation keys

Locale set is open-ended and owned by `frontend/src/providers/locale-catalog.ts` (code + native label). That catalog feeds i18next `supportedLngs`. The catalog **native label** is for **language identity** only: the top-bar language switcher and Account Center UI-language select. It is not reused for configuration-slot chrome.

When a Console surface labels a **catalog locale as a configuration slot** (for example, Site Branding tabs over `brand_names` / `taglines`), the label follows the **current UI language** via i18n keys `locale.label.<code>` in each `locales/<lng>/common.json`. Do not use the catalog native label there.

Preference persistence uses a **cookie** `refraq.locale` (via `next-i18next` `createProxy` + `useChangeLanguage`). Detection order is **cookie → `NEXT_PUBLIC_DEFAULT_LOCALE` (fallback)**; do **not** use navigator, Accept-Language, query, or localStorage for negotiation. `localStorage` is no longer read after migration; a one-time client bridge may copy a legacy `localStorage` value into the cookie on first load, then clear it.

Integration: `frontend/i18n.config.ts` + `next-i18next` (`createProxy`, `getT` / `getResources`) wrapped by `frontend/src/providers/app-i18n-provider.tsx`. SSR hydrates only the current language via `getResources`; the client injects a custom `I18nProvider` `use` backend (`i18next-resources-to-backend` + dynamic `import` of `locales/<lng>/<ns>.json`, same source as `resourceLoader`) so other locales load on demand when switching. The Refine i18n adapter is still created inside a client subscriber (`RefineRoot`); do not remount the tree with a locale `key` to refresh UI. Locale switching must go through `useChangeLanguage` (cookie + server re-render), not a bare `i18n.changeLanguage`.

To add a locale: add `locales/<code>/common.json`, register it in `i18n.config.ts` `resourceLoader` / `supportedLngs` (via `LOCALE_CATALOG`), append one row to `LOCALE_CATALOG`, and add `locale.label.<code>` to **every** existing `locales/<lng>/common.json` (configuration-slot chrome in each UI language).

## 4. Allowed Dependencies

### Backend

See the whitelist in [`docs/backend-layout.md`](backend-layout.md) §7. Summary:

- `core` → no business packages except `upgrade` → published `admin` / `worker.api` / `worker.parameters`
- `admin` → `core` (+ own modules)
- `jobs` → `core`; published `admin` (including System Parameter resolver) when needed
- `metadata` → `core`; published `admin` / `jobs`; published `worker.api` / `worker.errors` / `worker.schemas` / `worker.schedules`
- `worker` → `core`; published surfaces for assembly
- `main` → `core` + package routers / bootstrap via published surfaces
- `alembic` → `core` Base + every package `models` module

### Frontend

- `app/` → `features/`, `providers/`, `components/`, `lib/`
- `features/` → `providers/` (hooks/types only via Refine), `components/`, `lib/`
- `features/schedules` → `features/jobs` (Job type, cancel, detail modal, trigger presentation); `features/sources` (`getSource` for related-schedules workbench title only)
- `features/sources` → `features/jobs` (Structure Diff detail opens Job observe modal only); `features/schedules` (Scheduled Task types)
- `features/jobs` must not import `features/sources` or `features/schedules`
- `providers/` → `lib/`
- `components/` → `lib/` only for light helpers

## 5. Forbidden Coupling

- Do not import frontend files into backend
- Do not let persistence stores shape UI labels or page logic
- Do not let frontend components define the authoritative permission matrix
- Do not scatter login/session logic across many pages; keep it in providers and route guards
- Do not house Job observation UI or `/jobs` HTTP in `features/sources` (belongs in `features/jobs`)
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
- Console Module Identity codegen: `scripts/gen_console_module_catalog.py` → `frontend/src/features/console/module-identity/generated-ids.ts`, `generated-catalog.ts`
- Console route ACL: `frontend/src/components/access/PageCanAccess.tsx` + `frontend/src/features/console/module-identity/adapters.ts` (`matchPath`)
- Platform settings API: `backend/admin/system_parameters/` (mechanism HTTP) + `<package>/parameters.py` declarations
- Settings UI: `frontend/src/features/settings/`
- Site Branding API: `backend/admin/branding/`
- Site Branding resolution, management page, and preview: `frontend/src/features/branding/`
- Model Service API: `backend/admin/model_services/`
- Model Service Console: `frontend/src/features/model-services/`
- Site Branding framework consumption and theme bridge: `frontend/src/providers/`; server-rendered public branding fetch: `frontend/src/features/branding/server.ts`

## 7. Metadata / Operations Console Ownership

- Job observation (list, detail, logs, cancel, trigger presentation): `frontend/src/features/jobs/`
- Scheduled Task definition workbench (platform list, Source related-schedules page `/console/sources/:id/schedules`, run-now, related Jobs HTTP): `frontend/src/features/schedules/`
- Source / catalog / Structure Diff: `frontend/src/features/sources/` — does not own Job types or `/jobs` HTTP
- Source registry HTTP: `frontend/src/features/sources/api/sources.ts`
- Current catalog HTTP: `frontend/src/features/sources/api/catalog.ts`
- Object Semantics HTTP: `frontend/src/features/sources/api/semantics.ts`
- Join Path HTTP: `frontend/src/features/sources/api/joins.ts`
- Catalog Sample HTTP: `frontend/src/features/sources/api/sample.ts`; Console ACL is identity action `sample` (`catalog:sample`)
- Structure Diff HTTP: `frontend/src/features/sources/api/structure-diffs.ts`
- Catalog Object Console logic: `frontend/src/features/sources/catalog-detail/` (`sampleFilters`, `columnDrafts`, `joinEdges`, `catalogStatus`)
- Account Center MCP section: `frontend/src/features/account/McpSection.tsx` (catalog HTTP + copied `{origin}/mcp` config); same-origin `/mcp` stream: `frontend/src/app/mcp/route.ts`
