# refraq Backend

This directory contains the backend for refraq, the data product integration platform.

## Responsibility

The backend owns API contracts, Management Foundation domain rules (auth, RBAC), and persistence adapters.
User/Role data lives in Postgres; Session state lives in Redis when `REFRAQ_STORE_BACKEND=persistent`.

## Run

- Dev dependencies: from repo root, `docker compose up -d`
- Install: `uv pip install -r backend/requirements.txt` (or pip in a venv)
- Official start (migrate then serve): `python -m backend.core.entry`
- Tests: `pytest backend/tests -q` (memory); `pytest backend/tests -q -m integration` with Compose up (isolated `refraq_test` + Redis DB `1`)

See `docs/development.md` and `docs/env.md`.
