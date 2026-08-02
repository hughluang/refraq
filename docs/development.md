# refraq Development Guide

## Purpose

This document records the stable development conventions for contributors working inside this repository.

## Repository Boundary

- `refraq` is implemented only inside this repository.
- New product code belongs only in `backend/` and `frontend/`.
- Do not place new refraq feature work in any legacy codebase.

## Documentation Rules

- Root `README.md` is product-facing and should stay focused on repository identity and product value.
- Documents under `docs/` are the committed source of truth for architecture, business rules, API contracts, and development conventions.
- Local process files belong in `.process/` and are not part of the committed baseline.
- Formal documents must stay self-contained and must not depend on local process files.

## Working Style

- Prefer small, verifiable changes.
- Before editing, read the nearest README and the relevant document under `docs/`.
- When code and documents disagree, resolve the mismatch instead of inventing new behavior silently.
- Ask for confirmation before introducing ORM, migrations, Docker, compose, or external services that are not already present.

## Local Commands

### Backend

- Install dependencies: `python -m pip install -r backend/requirements.txt`
- Run dev server: `uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000`
- Run tests: `pytest backend/tests -q`

### Frontend

- Install dependencies: `npm install`
- Run dev server: `npm run dev`
- Run lint: `npm run lint`
- Run build: `npm run build`

## Suggested Reading Order

For Management Foundation auth/RBAC work, read in this order:

1. `docs/architecture.md`
2. `docs/modules.md`
3. `docs/business-login-auth.md`
4. `docs/api-contracts-auth.md`
5. `docs/api-contracts-users.md`
6. `docs/api-contracts-roles.md`
7. `docs/env.md`
