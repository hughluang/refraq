# Backend agent guide

Authoritative structure contract: [`docs/backend-layout.md`](../docs/backend-layout.md).
Module responsibilities: [`docs/modules.md`](../docs/modules.md).

## Hard rules

1. Choose a **package tier** before adding a top-level package (shared kernel / platform kernel / platform primitive / product domain / runtime). No empty shells.
2. Cross-package imports use only **published modules** listed in `docs/backend-layout.md` §3 (leaf modules that own the symbol; domain helpers via `metadata.source_jobs` etc.).
3. Place ORM, stores, rules, schemas, and HTTP/MCP adapters in the package that **owns the use case** — not in a global `routers/` or `repositories/` bucket.
4. Mechanism Job HTTP (by Job id) lives in `jobs/`; Source/Catalog/structure facade HTTP lives in `metadata/`; Foundation HTTP lives in `admin/`.
5. Domain and HTTP code must **not** import `worker.app`. Use `@shared_task` and `jobs.api.revoke_queued_delivery` (or other published async helpers). Composition (`main.py`) may bind the Celery runtime.
6. Subclass `backend.core.errors.AppError` for HTTP-mappable errors; do not subclass concrete `admin.errors` types from other tiers.
7. Enforcement tests: `backend/tests/test_layout_imports.py`. Do not “fix” failures by widening the contract — fix the import or extend the published list deliberately in docs.
