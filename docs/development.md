# refraq Development Guide

## Purpose

This document records the stable development conventions for contributors working inside this repository.

## Repository Boundary

- `refraq` is implemented only inside this repository.
- New product code belongs only in `backend/` and `frontend/`.
- Do not place new refraq feature work in any legacy codebase.

## Documentation Rules

- Root `README.md` is product-facing and should stay focused on repository identity and product value.
- Root `CONTEXT.md` is the domain language glossary (terms and relationships only; not implementation steps). Keep it aligned with `docs/glossary.md`.
- Documents under `docs/` are the committed source of truth for architecture, business rules, API contracts, and development conventions.
- Architecture decisions that are hard to reverse live under `docs/adr/`.
- Local process files belong in `.process/` and are not part of the committed baseline.
- Formal documents must stay self-contained and must not depend on local process files.

## Working Style

- Prefer small, verifiable changes.
- Before editing, read the nearest README and the relevant document under `docs/`.
- For metadata-phase work, start with `docs/business-metadata.md` and `CONTEXT.md`.
- For **Job** / **Scheduled Task** work, start with `docs/business-jobs.md` and `docs/business-scheduled-tasks.md`.
- When code and documents disagree, resolve the mismatch instead of inventing new behavior silently.
- Grow capability modules only when real code arrives; do not pre-create empty domain packages.

## Local Commands

### Dependencies (Postgres + Redis)

- Start: `docker compose up -d`
- Stop: `docker compose down`

### Backend

- Install dependencies: `python -m pip install -r backend/requirements.txt`
- Copy env: `cp backend/.env.example backend/.env` (and point URLs at Compose)
- Foundation Upgrade (schema + System Role identity ensure, no serve): `python -m backend.core.upgrade`
- Official start (upgrade then serve): `python -m backend.core.entry`
- Dev reload after schema is current: `uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000`
  - Direct `uvicorn` runs **Site Bootstrap** only (empty stores). It does not run schema migrate or System Role identity ensure.
  - After schema changes, run `python -m backend.core.upgrade` (or use `entry`). Super Admin effective permissions follow the Permission catalog by identity; adding a catalog key does not require Upgrade for Super Admin authz.
- Run API tests (memory Store Backend via conftest): `pytest backend/tests -q`
- Run integration tests (Compose must be up): `pytest backend/tests -q -m integration`
  - Uses isolated stores by default: Postgres DB `refraq_test` + Redis logical DB `1` (does not TRUNCATE/FLUSH interactive `refraq` / Redis `0`)
  - Override with `REFRAQ_INTEGRATION_DATABASE_URL` / `REFRAQ_INTEGRATION_REDIS_URL` if needed

### Frontend

- Install dependencies: `npm install`
- Run dev server: `npm run dev`
- Run lint: `npm run lint`
- Run build: `npm run build`
- Management Console content width: `docs/ui-console-layout.md` (section containers full width; internal controls own their own width)

### Self-deploy example

- Full stack: `docker compose -f deploy/compose.yaml up --build`
- Browser reaches the web service on host port `3000` (remap in compose if needed); `/api` is rewritten to the internal API.
- Frontend image build expects `frontend/node_modules` present (`npm ci` / `npm install` on the build host) and bakes `REFRAQ_API_UPSTREAM` via build-arg (default `http://api:8000`).

## Suggested Reading Order

### Metadata foundation (current next phase)

1. `CONTEXT.md`
2. `docs/business-metadata.md`
3. `docs/business-user-tokens.md`, `docs/business-account.md`
4. `docs/business-management-console.md` (`metadata` and `operations` nav groups)
5. `docs/business-jobs.md`, `docs/business-scheduled-tasks.md`
6. `docs/api-contracts-sources.md`, `docs/api-contracts-jobs.md`, `docs/api-contracts-schedules.md`, `docs/api-contracts-metadata.md`
7. `docs/api-contracts-tokens.md`, `docs/api-contracts-account.md`, `docs/api-contracts-audit.md`, `docs/api-contracts-metadata-mcp.md`
8. `docs/adr/0004-redis-queue-for-ingestion.md`, `docs/adr/0005-app-encrypted-connection-secrets.md`, `docs/adr/0006-celery-platform-async-runtime.md`, `docs/adr/0007-source-owns-catalog-identity.md`, `docs/adr/0008-job-generic-input.md`, `docs/adr/0010-source-owns-access.md`, `docs/adr/0011-encrypted-access-blob-and-connector-spec.md`, `docs/adr/0021-catalog-scope-in-access.md`, `docs/adr/0022-unified-time-contract.md`, `docs/adr/0023-api-problem-details.md`, `docs/adr/0024-normalized-type-mapping.md`
9. `docs/backend-layout.md`, `docs/architecture.md`, `docs/modules.md`, `docs/env.md`, `docs/conventions-time.md`, `docs/conventions-errors.md`

Treat `docs/product-core/*` as **long-horizon** reference only (files are marked superseded for near-term sequencing).

### Management Foundation auth/RBAC

1. `CONTEXT.md`
2. `docs/architecture.md`
3. `docs/modules.md`
4. `docs/adr/0001-postgres-redis-foundation-stores.md`
5. `docs/adr/0002-console-navigation-catalog.md` (cite by full filename; another `0002-*.md` exists)
6. `docs/adr/0003-foundation-upgrade-vs-bootstrap.md` (cite by full filename; another `0003-*.md` exists)
7. `docs/business-login-auth.md`
8. `docs/business-management-console.md`
9. `docs/ui-console-layout.md` (Console main-area width)
10. `docs/api-contracts-auth.md`
11. `docs/api-contracts-users.md`
12. `docs/api-contracts-roles.md`
13. `docs/api-contracts-console.md`
14. `docs/api-contracts-settings.md`
15. `docs/env.md`
