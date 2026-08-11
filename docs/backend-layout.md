# Backend Layout Contract

This document is the **authoritative structure contract** for `backend/`.
It describes the end-state rules for package tiers, published APIs, placement, and dependencies.
Migration sequencing lives only under `.process/` and must not relax these rules.

Companion: module responsibilities in [`docs/modules.md`](modules.md). Architecture intent in [`docs/architecture.md`](architecture.md).

## 1. Package tiers and when to add a package

Every top-level package belongs to exactly one tier:

| Tier | Meaning | Current members | Add a package when |
|------|---------|-----------------|--------------------|
| **Shared kernel** | Stable infrastructure and cross-package primitives with no product use-case rules | `core` | Multiple parties need it, and it does not express a business use case |
| **Platform kernel** | Site-enabling capability; product domains may depend on its **published API** | `admin` (Management Foundation) | Independent model/lifecycle; real code; language is people/authz/session/audit, not a product domain |
| **Platform primitive** | Mechanism reusable by domains; **owns mechanism-resource HTTP**; does **not** own domain use-case HTTP | `jobs` (Job lifecycle) | Model is mechanistic (kind + opaque input), not one domain's resource facade |
| **Product domain** | Business-language boundary; vertically coherent | `metadata` | Distinct business language; real code; mixing into another package keeps causing friction |
| **Runtime** | Process/queue/scheduler assembly; owns **Scheduled Task** | `worker` | Needs its own process entry or Beat; do not invent another product domain for that |

New packages: choose a tier first, then land real code. **No empty shell packages.**

**Scheduled Task ownership (fixed):** `worker` owns the Scheduled Task table and Beat. `jobs` owns only the Job table. No dual ownership.

## 2. Target tree (end state)

Directory shape is illustrative, not a mandate for every filename.

```text
backend/
  main.py                 # composition root: mount published routers; Site Bootstrap
  core/                   # shared kernel: config, DB/Redis, upgrade, AppError, probes
  admin/                  # platform kernel (Identity / RBAC / Console foundation)
    # published modules listed in §3
    models.py *_store.py permissions.py …
    schemas/ routers/     # this package's HTTP shapes and adapters
  jobs/                   # Job platform primitive
    models.py store.py …
    schemas/ routers/     # mechanism HTTP by Job id (get/cancel); no domain use-case HTTP
  metadata/               # product domain: Source / Catalog / structure Job use cases
    models.py errors.py sources/ catalog/ connectors/
    schemas/ routers/     # domain use-case HTTP
    mcp_server.py tasks.py
  worker/                 # runtime: Celery app, Beat, Scheduled Task, system tasks, discovery
  alembic/
  tests/                  # includes dependency / published-API enforcement tests
```

## 3. Published API

Each **platform kernel / platform primitive / product domain** package has an explicit published surface.

- **Form:** the module set listed below, plus each module's export list (`__all__` or equivalent). Other packages import only symbols from these paths.
- **Internal:** stores, ORM, private helpers, and modules not listed here.
- **Forbidden:** re-exporting store/ORM internals through a published module to evade enforcement.
- **Composition / runtime** (`main`, `worker`) may import published APIs and adapter entry modules needed for assembly (routers, task modules). They still must not reach unpublished store internals unless that entry *is* the published adapter.

### `admin` published modules

| Module | Published for |
|--------|----------------|
| `backend.admin.deps` | Current user, permission, PAT resolution, actor token id, session cookie helpers |
| `backend.admin.permissions` | Permission catalog helpers used by MCP and deps |
| `backend.admin.errors` | Foundation error types (subclass `core.errors.AppError`) |
| `backend.admin.audit` | `persist_audit_event` |
| `backend.admin.roles` | `ensure_system_role`, `seed_roles`, `effective_permissions`, `SUPER_ADMIN_KEY`, role write helpers used by composition |
| `backend.admin.security` | Password/session id helpers used by composition |
| `backend.admin.user_store` | `UserRecord`, `UserStore`, `get_user_store`, `reset_user_store` (typing + bootstrap) |
| `backend.admin.role_store` | `RoleRecord`, `RoleStore`, `get_role_store`, `reset_role_store` |
| `backend.admin.session_store` | `SessionStore`, `get_session_store`, `reset_session_store` |
| `backend.admin.token_store` | Token store ports used by deps/tokens HTTP |
| `backend.admin.audit_store` | Audit store ports used by audit HTTP / writers |
| `backend.admin.routers.*` | Foundation HTTP adapters (mounted by `main` only) |

Import the leaf module that owns the symbol. Do not add a pure re-export facade.

### `jobs` published modules

| Module | Published for |
|--------|----------------|
| `backend.jobs.api` | Seam policy only: `revoke_queued_delivery`, `job_out` (JobRecord→JobOut) |
| `backend.jobs.store` | Store port used by domain facades and reaper (create/get/status transitions, `JobRecord`, `TERMINAL`) |
| `backend.jobs.errors` | Mechanism Job errors (`JobNotFound`, `JobNotCancellable`, …) |
| `backend.jobs.schemas.*` | Mechanism Job response shapes (shared with domain facades) |
| `backend.jobs.routers.*` | Mechanism-resource HTTP (by Job id); mounted by `main` |

### `metadata` published modules

| Module | Published for |
|--------|----------------|
| `backend.metadata.errors` | Domain errors (subclass `AppError`, not `admin` concrete types) |
| `backend.metadata.source_jobs` | Structure enqueue / list-by-source facade |
| `backend.metadata.mcp_server` | MCP tool host entry |
| `backend.metadata.tasks` | Celery shared-task callables (discovered by `worker`) |
| `backend.metadata.routers.*` | Domain use-case HTTP; mounted by `main` |

### `worker` published modules

| Module | Published for |
|--------|----------------|
| `backend.worker.api` | Upgrade/composition helpers (e.g. `ensure_system_schedules`) |
| `backend.worker.app` | Celery app entry (`celery -A backend.worker.app`); composition may bind it for producers |
| `backend.worker.tasks` | Platform system tasks (discovered by the app) |

### Cross-package errors

- `backend.core.errors.AppError` carries `code` + `http_status` (+ message).
- Foundation and domain errors subclass `AppError`.
- Product domains and platform primitives **must not** subclass concrete `admin.errors` types.
- HTTP mapping in composition recognizes `AppError`.

## 4. Placement (by ownership, not by technical layer)

| Kind | Lives in |
|------|----------|
| ORM / store | Package that **owns** the data |
| Domain rules, authz policy, use-case facade | Package that owns that language |
| Request/response shapes and HTTP/MCP adapters for a use case | Package that **owns that use case** |
| Mechanism-resource HTTP (get/cancel Job by id) | `jobs` |
| Domain use-case HTTP (Source, structure enqueue/list, Catalog) | product domain (`metadata`) |
| Outbound adapter families | Owning product domain (e.g. `metadata/connectors`) |
| Domain error types | That product domain (base in `core`) |
| Config, engine, secrets crypto, upgrade orchestration, `AppError`, process probes | `core` (upgrade may call platform-kernel published API) |
| Celery app, Beat, **Scheduled Task**, system tasks, task registration | `worker` |
| Domain async work units (`@shared_task` or equivalent) | Owning product domain; **discovered and registered by `worker`** |
| Process probes (health/ready) | `core` (thin); not inside a product domain |

**Use-case ownership:** follow the business language of the operation. Structure collection, Catalog, Source-scoped Job facade → `metadata`. User/Role/Session/PAT/Console foundation → `admin`. Job-id mechanism read/write → `jobs`. Console nav may aggregate routes from multiple packages; that does **not** put all HTTP into `jobs`.

## 5. Structure inside a package

A package's modules are of two kinds:

- A **language unit** carries one sub-language of the package: its use-case
  orchestration and its persistence.
- A **cross-cutting module** serves the package as a whole (models, error types,
  identifiers, task entry, adapter host).

Rules:

- A language unit lives in a subpackage named after that language; inside it,
  modules are named by role (`service.py`, `store.py`, replaceable adapter families).
- Cross-cutting modules stay at the package root.
- All language units in a package take the same shape, whatever their size.
  Elevate by language boundary, not by file count.
- Consequently, a package root carries no module belonging to a single sub-language.
- Do not add empty technical-layer directories (`domain/`, `application/`,
  `infrastructure/`) inside a tier.

## 6. Naming

- `*store*`: persistence only; no HTTP; no permission decisions.
- Published modules: cross-package entry (see §3); do not mythologize a single filename.
- `service.py` / use-case-named modules: in-package orchestration.
- `models.py`, `errors.py`, `tasks.py`, `router(s)`, `schemas/`: as named.
- Top-level directory names express **tier and language**, not “bucket of all routers”.

## 7. Allowed dependencies (whitelist; acyclic)

Forward rules:

1. `core` depends on no platform kernel / primitive / product-domain business package (upgrade may import **published** `admin` and `worker.api` only for orchestration).
2. **Product domain ↔ product domain:** no direct imports. Collaborate via shared-kernel protocols or composition binding—extend this contract with an explicit edge when needed.
3. **Product domain → platform kernel / primitive:** published API only (Conformist).
4. Platform primitive → platform kernel: default none; if needed, add an explicit whitelist edge via published API.
5. Drivers (router/MCP) → own-package domain logic → published APIs / `core`. Domain and HTTP **must not** import `worker.app`. Delivery goes through `jobs` published API (or an agreed async published surface). Tasks use `@shared_task` (or equivalent); `worker` assembles.
6. No frontend ↔ backend source imports.

Concrete edges:

| From | May import |
|------|------------|
| `main` (composition) | `core`, published `admin` / `jobs` / `metadata` (including their `routers.*` for mount), Site Bootstrap helpers |
| `core` | stdlib, third parties, Alembic; `admin.roles` published symbols from `upgrade` only |
| `admin` | `core`; own stores/schemas/routers |
| `jobs` | `core`; own store/schemas/routers; published `admin` when cancel/audit needs it |
| `metadata` | `core`; published `admin`; published `jobs`; own modules |
| `worker` | `core`; published `admin` / `jobs` / `metadata` for assembly and system tasks |
| `alembic` | `core` Base + every package `models` module |
| `tests` | any backend module (enforcement tests assert production edges) |

## 8. Enforcement

- This document plus [`docs/modules.md`](modules.md) Allowed Dependencies stay aligned with code.
- Automated checks: packages must not import another package's unpublished modules; `core` must not import business packages except the upgrade→`admin.roles` edge; business code must not import `worker.app`.
- Checks live under `backend/tests/` (layout/import tests). Temporary allowlists, if any, are registered in that test and removed when migration phases finish—not by editing this contract.

## 9. Repository root under `backend/`

Only: composition (`main.py`), tiered packages, `alembic/`, `tests/`, dependency and env files. No scattered business `service.py` / stores at the `backend/` root.
