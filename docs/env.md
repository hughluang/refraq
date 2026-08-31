# refraq Environment Conventions

## 1. Purpose

This document records the current environment variables and the expected local-development and site-install conventions.

These conventions serve the **Management Console**, **Management Foundation**, and the **metadata foundation** phase (secrets master key, Celery worker/beat). Data Product catalog capabilities may add further variables later.

## 2. Current Files

### Backend

Current `backend/.env.example` defines:

- `REFRAQ_ENV=dev`
- `REFRAQ_API_HOST=127.0.0.1`
- `REFRAQ_API_PORT=8000`
- `REFRAQ_MCP_HOST=127.0.0.1` (MCP process bind; local default localhost)
- `REFRAQ_MCP_PORT=8001`
- `REFRAQ_STORE_BACKEND=persistent`
- `TZ=UTC` (process timezone default; override via standard `TZ` only)
- `DATABASE_URL=postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq`
- `REDIS_URL=redis://127.0.0.1:6379/0`
- `ADMIN_SESSION_SECRET=change-me`
- `INITIAL_ADMIN_ACCOUNT=root`
- `INITIAL_ADMIN_PASSWORD=change-me`
- `REFRAQ_SECRETS_MASTER_KEY=change-me-secrets-master-key` (metadata foundation: encrypt Source secrets at rest)
- `CELERY_BROKER_URL=redis://127.0.0.1:6379/2` (Celery broker; prefer a logical DB separate from Session `REDIS_URL`). If unset, broker is derived from `REDIS_URL` (`…/2`); if both unset, resolution fails (no localhost invent).
- `REFRAQ_CATALOG_FAIL_SAFE_THRESHOLD=0.75` (abort structure catalog write when absent ratio exceeds this; **System Parameter** candidate owned by `metadata` — `docs/business-system-parameters.md` §5.1)
- `REFRAQ_QUERY_TIMEOUT_SEC=30` (controlled query dual timeout: application + engine statement/command timeout; **System Parameter** candidate — §5.1)
- `REFRAQ_QUERY_MAX_ROWS=1000` (platform cap for controlled query `max_rows`; request default is 100; **System Parameter** candidate — §5.1)

Session TTL and occupancy lost-detection are **System Parameter**s (`docs/business-system-parameters.md` §5). They are not environment variables. A leftover name matching a registered key (`ADMIN_SESSION_TTL_HOURS`, `REFRAQ_JOB_LOST_DETECTION_SEC`, or the key itself in uppercase) is ignored and reported at startup as dead. The stored row is the only home.

Worker concurrency is neither. It is owned by the deployment and set on the worker command line (§8); `REFRAQ_JOB_WORKER_CONCURRENCY` is retired and reading it is not implemented anywhere. Beat loop / reload intervals and the reaper poll interval are in-code constants or derived from lost-detection (`docs/business-system-parameters.md` §5.2), not environment variables and not System Parameters.

Remove `ADMIN_SESSION_TTL_HOURS` and `REFRAQ_JOB_LOST_DETECTION_SEC` from live `.env` files. Changing them and restarting has no effect. Tune session TTL and lost-detection in Platform Settings. Set concurrency where the worker is launched.

`REFRAQ_STORE_BACKEND=memory` is for automated tests only. Do not use it in production examples.
Metadata foundation variables are required when running ingestion/secret features; Foundation-only local login may still boot without them until those code paths are exercised.

### Frontend

Current `frontend/.env.example` defines:

- `NEXT_PUBLIC_REFRAQ_API_BASE_URL=/api`
- `REFRAQ_API_UPSTREAM=http://127.0.0.1:8000`
- `REFRAQ_MCP_UPSTREAM=http://127.0.0.1:8001` (web Route Handler streams `/mcp` here; never expose `readyz`)
- `REFRAQ_QUERY_TIMEOUT_SEC=30` (web `/mcp` wait is this value plus margin; must match backend query timeout)
- `NEXT_PUBLIC_DEFAULT_LOCALE=en-US`

`REFRAQ_API_UPSTREAM` has matching build-time and runtime duties. Next.js reads it at build time to compile browser `/api` rewrites. Server-only frontend code reads it at runtime for direct SSR calls such as public Site Branding. Local `next dev` uses the env file. Published web images bake `http://api:8000` as a Docker build argument; the site compose also sets the same runtime value.

### Deploy

`deploy/` is a site template, not a live site directory. Copy `deploy/compose.yaml` and `deploy/.env.example` (or the GitHub Release attachments) into a directory outside the git tree. Never commit the live `.env`.

Current `deploy/.env.example` defines:

- `REFRAQ_VERSION` (required; image tag without the `v`, for example `0.1.0`. Do not use `latest`. Change this value to upgrade or roll back.)
- `INITIAL_ADMIN_ACCOUNT=root`
- `INITIAL_ADMIN_PASSWORD` (required live secret)
- `ADMIN_SESSION_SECRET` (required live secret)
- `REFRAQ_SECRETS_MASTER_KEY` (required live secret; stable per site)
- `POSTGRES_PASSWORD` (required; platform Postgres, internal Docker network only)
- `REFRAQ_WEB_PORT=3001` (host port for the Management Console)
- `REFRAQ_BROWSER_FACING_PROTO` (optional on web; default `http`; set `https` when TLS terminates in front of the Console)
- `REFRAQ_BROWSER_FACING_HOST` (optional on web and API; host or `host:port` the browser uses for the Console, without scheme. Required for non-loopback Console URLs so OIDC `redirect_uri` is not taken from request `Host`)

Published images are **linux/amd64** only (`ghcr.io/hughluang/refraq-api:<version>` and `ghcr.io/hughluang/refraq-web:<version>`). Compose project name is `refraq-prod` so volumes do not collide with the local Postgres/Redis Compose and stay attached when the site directory moves.

## 3. Local Convention (Unified)

- backend host: `127.0.0.1`
- backend port: `8000`
- MCP process: `127.0.0.1:8001` (`python -m backend.metadata.mcp_http`)
- browser API base URL: `/api` (same-origin)
- browser MCP URL: `{origin}/mcp` (same-origin; Account Center copies this)
- Next.js rewrite upstream: `http://127.0.0.1:8000` (dev)
- Next.js `/mcp` stream upstream: `http://127.0.0.1:8001` (`REFRAQ_MCP_UPSTREAM`)
- Next.js server-rendering API upstream: `http://127.0.0.1:8000` (dev)

The browser talks to the backend through a Next.js rewrite so the session cookie is set on the frontend origin and `proxy.ts` can see `refraq_sid`. Server-only rendering code calls the same upstream directly through `REFRAQ_API_UPSTREAM`; it does not make a loopback request to the Next.js server. URLs emitted into HTML remain browser-facing same-origin paths and never expose this internal upstream.

Site compose exposes only the web service to browsers; the API stays on the internal network and must be named `api`. The MCP process is the same api image with `python -m backend.metadata.mcp_http`; compose names it `mcp` and does **not** publish its port. Web streams `{origin}/mcp` to `REFRAQ_MCP_UPSTREAM` (`http://mcp:8001` on site). Process `readyz` is compose-internal only. The copied Account Center URL is the Console origin plus `/mcp`; there is no second public MCP hostname. The host port defaults to `3001` (`REFRAQ_WEB_PORT`) so a local Console on `127.0.0.1:3000` can keep running. Bind local `next dev` to `127.0.0.1` so the office network cannot open the sandbox Console.

Session cookie `Secure` follows browser-facing HTTPS. The web `proxy.ts` hop for `/api` overwrites `X-Forwarded-Proto` from `REFRAQ_BROWSER_FACING_PROTO` (default `http`) and `X-Forwarded-Host` from `REFRAQ_BROWSER_FACING_HOST` when set, otherwise from a loopback request Host; it does not pass through client-supplied public Hosts. The API then reads those stamped headers (then a loopback request Host). `REFRAQ_ENV=prod` does not force `Secure`. HTTP sites must keep the Session; set `REFRAQ_BROWSER_FACING_PROTO=https` on web when TLS terminates in front of the Console. Set `REFRAQ_BROWSER_FACING_HOST` on web and API to the browser-facing Console host when it is not loopback.

## 4. Variable Ownership

### Backend-Owned Variables

- `REFRAQ_ENV`
- `REFRAQ_API_HOST`
- `REFRAQ_API_PORT`
- `REFRAQ_MCP_HOST` (MCP process bind; local default `127.0.0.1`)
- `REFRAQ_MCP_PORT` (MCP process port; default `8001`)
- `REFRAQ_STORE_BACKEND` (`persistent` default; `memory` tests only)
- `TZ` (process timezone; default UTC in examples/images; not `APP_TIMEZONE`)
- `DATABASE_URL` (required when `persistent`)
- `REDIS_URL` (required when `persistent`)
- `ADMIN_SESSION_SECRET` (reserved for future signed-cookie usage; v1 sessions are server-managed)
- `INITIAL_ADMIN_ACCOUNT`
- `INITIAL_ADMIN_PASSWORD`
- `REFRAQ_SECRETS_MASTER_KEY` (required to store/read Source secrets)
- `CELERY_BROKER_URL` (required when running Celery worker/beat; default same host Redis DB `2`)
- `REFRAQ_BROWSER_FACING_HOST` (optional; host or `host:port`, no scheme) — canonical Console host for OIDC `redirect_uri`; when unset, only a loopback Host is used
- `REFRAQ_CATALOG_FAIL_SAFE_THRESHOLD` (metadata candidate; not yet a System Parameter)
- `REFRAQ_QUERY_TIMEOUT_SEC` (metadata candidate; not yet a System Parameter)
- `REFRAQ_QUERY_MAX_ROWS` (metadata candidate; not yet a System Parameter)
- `REFRAQ_INTEGRATION_DATABASE_URL` (pytest `@pytest.mark.integration` only; default `…/refraq_test`)
- `REFRAQ_INTEGRATION_REDIS_URL` (integration only; default `redis://127.0.0.1:6379/1`)
- `REFRAQ_INTEGRATION_CELERY_BROKER_URL` (integration only; default `redis://127.0.0.1:6379/3`)

### Frontend-Owned Variables

- `NEXT_PUBLIC_REFRAQ_API_BASE_URL` (browser-facing base; default `/api`)
- `REFRAQ_API_UPSTREAM` (internal backend origin; build-time rewrite target and runtime server-rendering target; never exposed to browser code)
- `REFRAQ_MCP_UPSTREAM` (internal MCP origin; runtime stream target for `/mcp` only; never `readyz`)
- `REFRAQ_QUERY_TIMEOUT_SEC` (web `/mcp` wait floor plus margin; keep aligned with backend)
- `NEXT_PUBLIC_DEFAULT_LOCALE`
- `REFRAQ_BROWSER_FACING_PROTO` (`http` | `https`; default `http`) — stamped onto `/api` rewrite as `X-Forwarded-Proto` for Session `Secure`; set `https` when TLS terminates in front of the Console
- `REFRAQ_BROWSER_FACING_HOST` (optional; host or `host:port`, no scheme) — stamped onto `/api` rewrite as `X-Forwarded-Host` for OIDC callback origin; when unset, only a loopback request Host is stamped

### Deploy-Owned Variables

- `REFRAQ_VERSION` (site image tag without the `v`; required to pull published images)
- `POSTGRES_PASSWORD` (platform Postgres password; Compose interpolation; not published to the host)
- `REFRAQ_WEB_PORT` (host port for the web service; default `3001`)
- `REFRAQ_BROWSER_FACING_PROTO` (optional; forwarded to web; default `http`)
- `REFRAQ_BROWSER_FACING_HOST` (optional; forwarded to web and API; browser-facing Console host or `host:port`)
- `REFRAQ_API_UPSTREAM` (web build argument and web runtime environment; both use the internal API origin `http://api:8000` on a site)
- `REFRAQ_MCP_UPSTREAM` (web runtime; site value `http://mcp:8001`; not a public origin)

## 5. Process timezone (`TZ`)

- Site and image default is process `TZ=UTC` (backend Dockerfile `ENV`, Compose service environment, `.env.example`).
- Override only via the standard `TZ` environment variable; do **not** invent `APP_TIMEZONE`.
- Production must run UTC. Instant semantics do not depend on process TZ, but default UTC avoids accidental local interpretation in libraries that read `TZ`.
- IANA zone data: declare Python package `tzdata` so Schedule Timezone / `zoneinfo` works without host OS zoneinfo.
- Full Instant / Schedule Timezone rules: [`docs/conventions-time.md`](conventions-time.md).

## 6. Usage Rules

- Use `.env.example` as the canonical template
- Keep docs and env examples in sync
- Do not commit real secrets
- Do not change API port in code and forget to update frontend env
- The initial admin password is meant for first-time local development only; rotate it before any non-local site. Site compose reads a live `.env` outside the git tree; do not leave example secrets in a live stack.
- Missing `DATABASE_URL` / `REDIS_URL` with `persistent` must fail fast; never silently fall back to memory
- Settings dotenv load order: repo-root `.env` then `backend/.env` (later wins). Prefer `backend/.env` as the local canonical file
- Integration tests must not reuse interactive `DATABASE_URL` / `REDIS_URL`; they use `REFRAQ_INTEGRATION_*` defaults so Compose live data stays intact

## 7. Initial Admin Seeding

On backend startup, if the user store is empty, default roles are ensured and a single `super_admin` user is created from `INITIAL_ADMIN_ACCOUNT` and `INITIAL_ADMIN_PASSWORD`. The display name defaults to the account value. Subsequent restarts do not re-seed. Multiple replicas remain safe because seeding is gated on an empty user store.

## 8. Celery Worker And Beat

Platform async runtime (`docs/adr/0006-celery-platform-async-runtime.md`):

- API process: create durable Job rows and enqueue via Celery after commit (`docs/api-contracts-jobs.md`)
- Worker: `celery -A backend.worker.app worker` — concurrency is a deployment concern, not a **System Parameter** (`docs/business-system-parameters.md` §5.2). No flag is passed, so Celery's own default (one process per CPU) applies; a deployment that needs to pin capacity passes `--concurrency` on this command line, and sizes it together with the replica count. The local `.vscode` launch configuration pins `--pool=solo --concurrency=1` because a debugger needs a single process; it overrides no stored value
- Beat (single replica): `celery -A backend.worker.app beat` — reads **Scheduled Task** rows from Postgres; do not run multiple Beat replicas. Loop `max_interval` and schedule reload `sync_every` are in-code constants (`BEAT_MAX_INTERVAL_SEC = 5`, `BEAT_SYNC_EVERY_SEC = 30`; `docs/business-system-parameters.md` §5.2). An overdue in-memory commitment is dispatched **once** until the next reload (or `BEAT_SYNC_EVERY_SEC` retry if the store row is still overdue); Beat does not tight-loop send while the worker consumes the tick. Occupancy lost-detection (`job_lost_detection_sec`, seed 60 → `JOB_WORKER_LOST`) is driven by the system reaper Scheduled Task on this Beat. Beat sync copies that same lost-detection value onto the reaper row's `interval_seconds` and does not recompute `next_run_at`, so tightening may wait for the current tick. If Beat is stopped, that reaping stops — starting only the API does not recover false `RUNNING` Jobs.
- Worker and Beat share `DATABASE_URL`, `CELERY_BROKER_URL`, and (when decrypting secrets) `REFRAQ_SECRETS_MASTER_KEY`
- After Foundation Upgrade, restart worker and Beat. Code on disk does not change a live process's registered names; a leftover worker after a `task_name` revision yields Beat `NotRegistered` and structure clocks that never mint. Confirm with `celery -A backend.worker.app inspect registered` that registered names match Scheduled Task rows.
- No Celery result backend; operator-visible status and run logs live on Postgres Job rows (`log_body`; later large attachments if needed)
- Do not run long collection inside the interactive API request path (`docs/adr/0004-redis-queue-for-ingestion.md`)

## 9. Secret Handling

- Never commit real `REFRAQ_SECRETS_MASTER_KEY`, admin passwords, or Source database passwords
- Rotating `REFRAQ_SECRETS_MASTER_KEY` requires a documented re-encrypt procedure before it is safe in production; until then treat the key as stable per environment

## 10. Local Identity Provider (Keycloak)

Root `compose.yaml` includes a development Keycloak. `deploy/compose.yaml` does not; production Identity Provider configuration is an operator concern.

Start it with the rest of the local stack (`docker compose up`). Realm import is `dev/keycloak/refraq-realm.json`. The service publishes host port `8080`. When that port is already taken, remap the host side only (for example `18080:8080`) and use the new port in the issuer and discovery URLs below and in the Console provider configuration; the realm redirect URIs point at the Console on `3000` and do not change.

| Item | Local value |
| --- | --- |
| Admin console | `http://127.0.0.1:8080` (`admin` / `admin`) |
| Issuer | `http://127.0.0.1:8080/realms/refraq` |
| Discovery | `http://127.0.0.1:8080/realms/refraq/.well-known/openid-configuration` |
| Client id | `refraq` |
| Client secret | `refraq-dev-secret` |
| Redirect URIs | `http://127.0.0.1:3000/api/auth/sso/*`, `http://localhost:3000/api/auth/sso/*` |
| Group claim | `groups` (full path) |
| Fixture `alice` / `alice` | group `/dept/analytics` |
| Fixture `bob` / `bob` | no groups |

These fixture passwords are local-only. Do not reuse them outside development.

Console configuration (Administration → Identity Providers):

- Issuer and client values from the table
- Scopes `openid`, `profile`, `email`
- Group claim `groups`
- For auto-provisioning: allowlist `/dept/analytics` and a default Role that is not `super_admin` and does not include `users:write`, `roles:write`, or `identity_providers:write`

Walkthrough against that realm (Management Console on `http://127.0.0.1:3000`):

1. Auto-provision: enable auto-provisioning, sign in as `alice`. A User `alice` is created with `identity_source=oidc`.
2. Pending queue: sign in as `bob`. No Session is issued; `/login?error=AUTH_SSO_NOT_ADMITTED` and a pending identity appear for `users:write`. Copy exact group strings from that record when configuring an allowlist.
3. Account collision: create a local User whose `account` matches a later IdP `preferred_username` (for example local `alice` before the first alice SSO). The assertion is queued, not silently bound. Claim it to the existing User or create a new account from the editable prefill.
4. Unfederation: from the Users list, set a new local password. Later SSO follows unbound admission.
5. Every-login group check: with auto-provisioning on, remove alice from `/dept/analytics` in Keycloak and sign in again. No new Session, User unchanged, no pending row.
6. Disable or delete the provider: the confirmation shows bound-user count and may optionally disable those Users (clears Sessions; disabled status rejects PATs).
