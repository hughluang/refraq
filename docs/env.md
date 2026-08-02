# refraq Environment Conventions

## 1. Purpose

This document records the current environment variables and the expected local-development conventions.

These conventions serve the first delivery slice (the **Management Console** and its **Management Foundation**). They are not specific to any product-defining **Data Product Capability**.

## 2. Current Files

### Backend

Current `backend/.env.example` defines:

- `REFRAQ_ENV=dev`
- `REFRAQ_API_HOST=127.0.0.1`
- `REFRAQ_API_PORT=8000`
- `ADMIN_SESSION_SECRET=change-me`
- `ADMIN_SESSION_TTL_HOURS=8`
- `INITIAL_ADMIN_ACCOUNT=root`
- `INITIAL_ADMIN_PASSWORD=change-me`

### Frontend

Current `frontend/.env.example` defines:

- `NEXT_PUBLIC_REFRAQ_API_BASE_URL=/api`
- `REFRAQ_API_UPSTREAM=http://127.0.0.1:8000`
- `NEXT_PUBLIC_DEFAULT_LOCALE=zh-CN`

## 3. Local Convention (Unified)

- backend host: `127.0.0.1`
- backend port: `8000`
- browser API base URL: `/api` (same-origin)
- Next.js rewrite upstream: `http://127.0.0.1:8000`

The Management Console talks to the backend through a Next.js rewrite so the session cookie is set on the frontend origin and `proxy.ts` can see `refraq_sid`.

## 4. Variable Ownership

### Backend-Owned Variables

- `REFRAQ_ENV`
- `REFRAQ_API_HOST`
- `REFRAQ_API_PORT`
- `ADMIN_SESSION_SECRET` (reserved for future signed-cookie usage; v1 sessions are server-managed)
- `ADMIN_SESSION_TTL_HOURS`
- `INITIAL_ADMIN_ACCOUNT`
- `INITIAL_ADMIN_PASSWORD`

### Frontend-Owned Variables

- `NEXT_PUBLIC_REFRAQ_API_BASE_URL` (browser-facing base; default `/api`)
- `REFRAQ_API_UPSTREAM` (server-side rewrite target for Next.js)
- `NEXT_PUBLIC_DEFAULT_LOCALE`

## 5. Usage Rules

- Use `.env.example` as the canonical template
- Keep docs and env examples in sync
- Do not commit real secrets
- Do not change API port in code and forget to update frontend env
- The initial admin password is meant for first-time local development only; rotate it before any non-local deployment

## 6. Initial Admin Seeding

On backend startup, if the administrator store is empty, a single `super_admin` record is created from `INITIAL_ADMIN_ACCOUNT` and `INITIAL_ADMIN_PASSWORD`. The display name defaults to the account value. Subsequent restarts do not re-seed.
