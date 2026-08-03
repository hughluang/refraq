# refraq Development Guide

## Purpose

This document records the stable development conventions for contributors working inside this repository.

## Repository Boundary

- `refraq` is implemented only inside this repository.
- New product code belongs only in `backend/` and `frontend/`.
- Do not place new refraq feature work in any legacy codebase.

## Documentation Rules

- Root `README.md` is product-facing and should stay focused on repository identity and product value.
- Root `CONTEXT.md` records principles and tendencies (not implementation steps).
- Documents under `docs/` are the committed source of truth for architecture, business rules, API contracts, and development conventions.
- Architecture decisions that are hard to reverse live under `docs/adr/`.
- Local process files belong in `.process/` and are not part of the committed baseline.
- Formal documents must stay self-contained and must not depend on local process files.

## Working Style

- Prefer small, verifiable changes.
- Before editing, read the nearest README and the relevant document under `docs/`.
- When code and documents disagree, resolve the mismatch instead of inventing new behavior silently.
- Grow capability modules only when real code arrives; do not pre-create empty domain packages.

## Local Commands

### Dependencies (Postgres + Redis)

- Start: `docker compose up -d`
- Stop: `docker compose down`

### Backend

- Install dependencies: `python -m pip install -r backend/requirements.txt`
- Copy env: `cp backend/.env.example backend/.env` (and point URLs at Compose)
- Official start (migrate then serve): `python -m backend.core.entry`
- Dev reload after schema is current: `uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000`
- Run API tests (memory Store Backend via conftest): `pytest backend/tests -q`
- Run integration tests (Compose must be up): `pytest backend/tests -q -m integration`
  - Uses isolated stores by default: Postgres DB `refraq_test` + Redis logical DB `1` (does not TRUNCATE/FLUSH interactive `refraq` / Redis `0`)
  - Override with `REFRAQ_INTEGRATION_DATABASE_URL` / `REFRAQ_INTEGRATION_REDIS_URL` if needed

### Frontend

- Install dependencies: `npm install`
- Run dev server: `npm run dev`
- Run lint: `npm run lint`
- Run build: `npm run build`

### Self-deploy example

- Full stack: `docker compose -f deploy/compose.yaml up --build`
- Browser reaches the web service on host port `3000` (remap in compose if needed); `/api` is rewritten to the internal API.
- Frontend image build expects `frontend/node_modules` present (`npm ci` / `npm install` on the build host) and bakes `REFRAQ_API_UPSTREAM` via build-arg (default `http://api:8000`).

## Suggested Reading Order

For Management Foundation auth/RBAC work, read in this order:

1. `CONTEXT.md`
2. `docs/architecture.md`
3. `docs/modules.md`
4. `docs/adr/0001-postgres-redis-foundation-stores.md`
5. `docs/business-login-auth.md`
6. `docs/business-management-console.md` (Console shell IA and module mount contract)
7. `docs/api-contracts-auth.md`
8. `docs/api-contracts-users.md`
9. `docs/api-contracts-roles.md`
10. `docs/env.md`
