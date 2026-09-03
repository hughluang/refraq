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
- Document types, skeleton, and writing rules: `docs/conventions-docs.md`.

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
- MCP HTTP (same env as API; local bind `127.0.0.1:8001`): `python -m backend.metadata.mcp_http`
- Dev reload after schema is current: `uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000`
  - Direct `uvicorn` runs **Site Bootstrap** only (empty stores). It does not run schema migrate or System Role identity ensure, and it does not start or reload Celery.
  - After schema changes, run `python -m backend.core.upgrade` (or use `entry`), then restart worker and Beat (`docs/env.md` §8). Super Admin effective permissions follow the Permission catalog by identity; adding a catalog key does not require Upgrade for Super Admin authz.
- Run API tests (memory Store Backend via conftest): `pytest backend/tests -q`
- Catalog store dual-adapter contract: `pytest backend/tests/test_catalog_store_conformance.py -q` (Memory always; SQL param runs when Compose Postgres is up, otherwise skips). Run this file when changing `backend/metadata/catalog/store/`.
- Run integration tests (Compose must be up): `pytest backend/tests -q -m integration`
  - Uses isolated stores by default: Postgres DB `refraq_test` + Redis logical DB `1` (does not TRUNCATE/FLUSH interactive `refraq` / Redis `0`)
  - Override with `REFRAQ_INTEGRATION_DATABASE_URL` / `REFRAQ_INTEGRATION_REDIS_URL` if needed

### Frontend

- Install dependencies: `npm install`
- Run dev server: `npm run dev` (binds `127.0.0.1` so the sandbox Console is not reachable on the office network).
- Run lint: `npm run lint`
- Run build: `npm run build`
- Management Console content width: `docs/ui-console-layout.md` (section containers full width; internal controls own their own width)

### Release and site install

- A version is a git tag `v*` (for example `v0.1.0`). Tagging is the only image publish trigger. Ordinary commits do not build images.
- GitHub Actions builds **linux/amd64** images and pushes `ghcr.io/hughluang/refraq-api:<version>` and `ghcr.io/hughluang/refraq-web:<version>` (tag without the `v`). After both image manifests exist, the same tag creates a GitHub Release that attaches a stamped `docker-compose.yaml` (image tags written in) and `.env.example`. Other architectures are not published. A tag on GHCR is not by itself an installable version.
- `deploy/compose.yaml` is a template. Do not start a site from `deploy/`.
- Install: download the two Release assets from `https://github.com/hughluang/refraq/releases/latest`, or the stable URLs `https://github.com/hughluang/refraq/releases/latest/download/docker-compose.yaml` and `https://github.com/hughluang/refraq/releases/latest/download/.env.example`, into a directory outside the git tree. Fill live secrets in `.env`. Do not keep the live `.env` in the repository. Compose project name is `refraq-prod`.
- The downloaded compose statically pins the version at download time. Treat it as a replaceable artifact. Site knobs belong in `.env`. If wiring must change, use a site-owned `compose.override.yml` (not a Release asset). Do not edit the official compose and expect a later overwrite-upgrade to keep those edits.
- Start: `docker compose pull && docker compose up -d`. Do not `docker compose down -v` unless the site data should be destroyed. Worker and Beat use the same image tag as the API (stamped together).
- Upgrade: download only `docker-compose.yaml` from Latest and overwrite the site compose, then `docker compose pull && docker compose up -d`. Do not overwrite the live `.env`. Diff that release's `.env.example` and add any new keys by hand.
- Roll back: download compose from a prior release, not Latest: `https://github.com/hughluang/refraq/releases/download/vX.Y.Z/docker-compose.yaml`, then pull and up.
- Sites still running an older interpolated compose with `REFRAQ_VERSION` keep that pin until they replace compose with a stamped attachment. After the switch, leftover `REFRAQ_VERSION` in `.env` has no effect.
- Browser reaches the web service on host port `3001` (`REFRAQ_WEB_PORT`); `/api` is rewritten to the internal API service named `api`; `/mcp` is streamed to the internal MCP service named `mcp` (`REFRAQ_MCP_UPSTREAM`). Keep local `next dev` on `127.0.0.1:3000` and run `python -m backend.metadata.mcp_http` so Account Center's copied `{origin}/mcp` works.
- Published web images bake `REFRAQ_API_UPSTREAM=http://api:8000` at build time. The site compose also sets the same value at runtime for server-rendering (Site Branding) and sets `REFRAQ_MCP_UPSTREAM=http://mcp:8001`. Compose does not publish the MCP port.

## Suggested Reading Order

### Metadata foundation (current next phase)

1. `CONTEXT.md`
2. `docs/business-metadata.md`
3. `docs/business-user-tokens.md`, `docs/business-account.md`
4. `docs/business-management-console.md` (`metadata` and `operations` nav groups)
5. `docs/business-jobs.md`, `docs/business-scheduled-tasks.md`
6. `docs/api-contracts-sources.md`, `docs/api-contracts-jobs.md`, `docs/api-contracts-schedules.md`, `docs/api-contracts-metadata.md`
7. `docs/api-contracts-tokens.md`, `docs/api-contracts-account.md`, `docs/api-contracts-audit.md`, `docs/api-contracts-metadata-mcp.md`
8. `docs/adr/0004-redis-queue-for-ingestion.md`, `docs/adr/0005-app-encrypted-connection-secrets.md`, `docs/adr/0006-celery-platform-async-runtime.md`, `docs/adr/0007-source-owns-catalog-identity.md`, `docs/adr/0008-job-generic-input.md`, `docs/adr/0010-source-owns-access.md`, `docs/adr/0011-encrypted-access-blob-and-connector-spec.md`, `docs/adr/0021-catalog-scope-in-access.md`, `docs/adr/0022-unified-time-contract.md`, `docs/adr/0023-api-problem-details.md`, `docs/adr/0024-normalized-type-mapping.md`, `docs/adr/0027-running-time-limit-on-schedule.md`
9. `docs/backend-layout.md`, `docs/architecture.md`, `docs/modules.md`, `docs/env.md`, `docs/conventions-time.md`, `docs/conventions-errors.md`, `docs/conventions-pagination.md`

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
14. `docs/business-system-parameters.md`, `docs/adr/0028-system-parameters.md`
15. `docs/api-contracts-settings.md`
16. `docs/business-branding.md`, `docs/adr/0034-site-branding-overrides-product-mark.md`
17. `docs/api-contracts-branding.md`
18. `docs/env.md`
