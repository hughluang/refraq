# refraq Environment Conventions

## 1. Purpose

This document records the current environment variables and the expected local-development conventions.

These conventions serve the first delivery slice (the Management Console and its Management Foundation). They are not specific to any product-defining Data Product Capability.

## 2. Current Files

### Backend

Current `backend/.env.example` defines:

- `REFRAQ_ENV=dev`
- `REFRAQ_API_HOST=0.0.0.0`
- `REFRAQ_API_PORT=8000`
- `ADMIN_JWT_SECRET=change-me`
- `ADMIN_JWT_EXPIRE_HOURS=8`

### Frontend

Current `frontend/.env.example` defines:

- `NEXT_PUBLIC_REFRAQ_API_BASE_URL=http://127.0.0.1:6068`
- `NEXT_PUBLIC_DEFAULT_LOCALE=zh-CN`

## 3. Known Mismatch

There is a documented mismatch today:

- backend default port: `8000`
- frontend default API base URL: `6068`

This mismatch must be resolved before real backend/frontend joint debugging.

## 4. Recommended Local Convention

Use this as the preferred local-development convention for the first implementation:

- backend host: `127.0.0.1`
- backend port: `8000`
- frontend API base URL: `http://127.0.0.1:8000`

Reason:

- backend already defaults to `8000`
- it reduces moving parts for the first auth slice

## 5. Variable Ownership

### Backend-Owned Variables

- `REFRAQ_ENV`
- `REFRAQ_API_HOST`
- `REFRAQ_API_PORT`
- auth/session-related backend secrets

### Frontend-Owned Variables

- `NEXT_PUBLIC_REFRAQ_API_BASE_URL`
- `NEXT_PUBLIC_DEFAULT_LOCALE`

## 6. Usage Rules

- Use `.env.example` as the canonical template
- Keep docs and env examples in sync
- Do not commit real secrets
- Do not change API port in code and forget to update frontend env

## 7. First Cleanup Task

Before the first end-to-end auth integration, do the following:

1. choose the final local API port
2. update backend and frontend `.env.example`
3. update frontend fallback behavior if needed
4. re-check `docs/architecture.md`, `docs/development.md`, and this document
