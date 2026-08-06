# refraq Environment Conventions

## 1. Purpose

This document records the current environment variables and the expected local-development and self-deploy conventions.

These conventions serve the **Management Console**, **Management Foundation**, and the **metadata foundation** phase (secrets master key, Celery worker/beat). Data Product catalog capabilities may add further variables later.

## 2. Current Files

### Backend

Current `backend/.env.example` defines:

- `REFRAQ_ENV=dev`
- `REFRAQ_API_HOST=127.0.0.1`
- `REFRAQ_API_PORT=8000`
- `REFRAQ_STORE_BACKEND=persistent`
- `DATABASE_URL=postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq`
- `REDIS_URL=redis://127.0.0.1:6379/0`
- `ADMIN_SESSION_SECRET=change-me`
- `ADMIN_SESSION_TTL_HOURS=8`
- `INITIAL_ADMIN_ACCOUNT=root`
- `INITIAL_ADMIN_PASSWORD=change-me`
- `REFRAQ_SECRETS_MASTER_KEY=change-me-secrets-master-key` (metadata foundation: encrypt Connection secrets at rest)
- `CELERY_BROKER_URL=redis://127.0.0.1:6379/2` (Celery broker; prefer a logical DB separate from Session `REDIS_URL`)
- `REFRAQ_JOB_WORKER_CONCURRENCY=1` (Celery worker concurrency hint)
- `REFRAQ_JOB_RUNNING_TIMEOUT_SEC=3600` (stuck `running` **Job** reaper threshold)

`REFRAQ_STORE_BACKEND=memory` is for automated tests only. Do not use it in production examples.
Metadata foundation variables are required when running ingestion/secret features; Foundation-only local login may still boot without them until those code paths are exercised.

### Frontend

Current `frontend/.env.example` defines:

- `NEXT_PUBLIC_REFRAQ_API_BASE_URL=/api`
- `REFRAQ_API_UPSTREAM=http://127.0.0.1:8000`
- `NEXT_PUBLIC_DEFAULT_LOCALE=en-US`

`REFRAQ_API_UPSTREAM` is read at **Next.js build time** for rewrites. Local `next dev` uses the env file; deploy images pass it as a Docker build-arg (typically `http://api:8000`).

## 3. Local Convention (Unified)

- backend host: `127.0.0.1`
- backend port: `8000`
- browser API base URL: `/api` (same-origin)
- Next.js rewrite upstream: `http://127.0.0.1:8000` (dev)

The Management Console talks to the backend through a Next.js rewrite so the session cookie is set on the frontend origin and `proxy.ts` can see `refraq_sid`.

Self-deploy Compose exposes only the web service to browsers; the API stays on the internal network.

## 4. Variable Ownership

### Backend-Owned Variables

- `REFRAQ_ENV`
- `REFRAQ_API_HOST`
- `REFRAQ_API_PORT`
- `REFRAQ_STORE_BACKEND` (`persistent` default; `memory` tests only)
- `DATABASE_URL` (required when `persistent`)
- `REDIS_URL` (required when `persistent`)
- `ADMIN_SESSION_SECRET` (reserved for future signed-cookie usage; v1 sessions are server-managed)
- `ADMIN_SESSION_TTL_HOURS`
- `INITIAL_ADMIN_ACCOUNT`
- `INITIAL_ADMIN_PASSWORD`
- `REFRAQ_SECRETS_MASTER_KEY` (required to store/read Connection secrets)
- `CELERY_BROKER_URL` (required when running Celery worker/beat; default same host Redis DB `2`)
- `REFRAQ_JOB_WORKER_CONCURRENCY`
- `REFRAQ_JOB_RUNNING_TIMEOUT_SEC`
- `REFRAQ_INTEGRATION_DATABASE_URL` (pytest `@pytest.mark.integration` only; default `…/refraq_test`)
- `REFRAQ_INTEGRATION_REDIS_URL` (integration only; default `redis://127.0.0.1:6379/1`)
- `REFRAQ_INTEGRATION_CELERY_BROKER_URL` (integration only; default `redis://127.0.0.1:6379/3`)

### Frontend-Owned Variables

- `NEXT_PUBLIC_REFRAQ_API_BASE_URL` (browser-facing base; default `/api`)
- `REFRAQ_API_UPSTREAM` (server-side rewrite target; build-time for production images)
- `NEXT_PUBLIC_DEFAULT_LOCALE`

## 5. Usage Rules

- Use `.env.example` as the canonical template
- Keep docs and env examples in sync
- Do not commit real secrets
- Do not change API port in code and forget to update frontend env
- The initial admin password is meant for first-time local development only; rotate it before any non-local deployment
- Missing `DATABASE_URL` / `REDIS_URL` with `persistent` must fail fast; never silently fall back to memory
- Settings dotenv load order: repo-root `.env` then `backend/.env` (later wins). Prefer `backend/.env` as the local canonical file
- Integration tests must not reuse interactive `DATABASE_URL` / `REDIS_URL`; they use `REFRAQ_INTEGRATION_*` defaults so Compose live data stays intact

## 6. Initial Admin Seeding

On backend startup, if the user store is empty, default roles are ensured and a single `super_admin` user is created from `INITIAL_ADMIN_ACCOUNT` and `INITIAL_ADMIN_PASSWORD`. The display name defaults to the account value. Subsequent restarts do not re-seed. Multiple replicas remain safe because seeding is gated on an empty user store.

## 7. Celery Worker And Beat

Platform async runtime (`docs/adr/0006-celery-platform-async-runtime.md`):

- API process: create durable Job rows and enqueue via Celery after commit (`docs/api-contracts-jobs.md`)
- Worker: `celery -A backend.worker.app worker --concurrency="${REFRAQ_JOB_WORKER_CONCURRENCY:-1}"`
- Beat (single replica): `celery -A backend.worker.app beat` — reads **Scheduled Task** rows from Postgres; do not run multiple Beat replicas
- Worker and Beat share `DATABASE_URL`, `CELERY_BROKER_URL`, and (when decrypting secrets) `REFRAQ_SECRETS_MASTER_KEY`
- No Celery result backend; operator-visible status and logs live on Postgres Job rows
- Do not run long collection inside the interactive API request path (`docs/adr/0004-redis-queue-for-ingestion.md`)

## 8. Secret Handling

- Never commit real `REFRAQ_SECRETS_MASTER_KEY`, admin passwords, or Connection passwords
- Rotating `REFRAQ_SECRETS_MASTER_KEY` requires a documented re-encrypt procedure before it is safe in production; until then treat the key as stable per environment
