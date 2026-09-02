# refraq Business Rules: System Parameters

## 1. Scope

This document defines the **System Parameter** mechanism: which site-wide values may exist, which package owns each, and how a value is declared, stored, resolved, changed, and retired.

A System Parameter is a platform mechanism, like **Job** and **Scheduled Task** — not a product domain. The mechanism owns declaration, storage, seed occupy, resolution, reset, audit, and presentation. It does **not** own the parameters themselves: every parameter belongs to the package that consumes it. **Platform Settings** is the Console Module that presents them — a presentation surface, not the owner of the set.

Related boundaries:

- Terminology: `docs/glossary.md` and root `CONTEXT.md`.
- Decision: `docs/adr/0028-system-parameters.md`.
- HTTP: `docs/api-contracts-settings.md`.
- Console module and IA: `docs/business-management-console.md` §5.
- Environment variables: `docs/env.md`.
- Package tiers, published API, allowed edges: `docs/backend-layout.md` §3 and §8.
- Consumers: `docs/business-jobs.md`, `docs/business-scheduled-tasks.md`, `docs/business-login-auth.md`.

## 2. Where A Tunable Value Lives

Ask in order. The first match is the home; the homes are mutually exclusive.

| # | Question | Home |
| --- | --- | --- |
| 1 | Must a process know it before it can reach data or identity, or is it a credential needed to reach the store? | Environment variable |
| 2 | Does it differ per instance of a business object? | Field on that object |
| 3 | Site-wide, and decided by the operator from the business (§2.1)? | **System Parameter** |
| 4 | Site-wide, but changing it changes a product behavior contract rather than an operator decision? | In-code constant; changing it is a release |
| 5 | Does it differ per **User** as a presentation preference? | **Account Center** |
| 6 | Is it a temporary switch with an end of life (rollout, experiment, kill switch)? | Not a System Parameter |

Three tests decide membership:

- **Intent** (#3, decisive): the operator must be able to decide the value from the business (§2.1). This is the only test that says what the page is *for*; the others say what is *safe* or *owned*.
- **Boot safety**: a bad stored value may degrade worker / Beat, but must never stop the process that serves Platform Settings from starting. Bounds are optional and declared only where a real cliff or a stated policy exists; a bound is not what makes a value a System Parameter.
- **Deployment fact** (#1): the value describes where this deployment lives rather than how the platform behaves. The secrets master key, and any value needed to reach the store that holds System Parameters, are never System Parameters. A non-secret value the deployment already owns is still not a System Parameter — intent clause 4 rejects it.

Question 6 is the main reason settings pages rot: a rollout or kill switch has a removal date; a System Parameter does not. A capability the operator turns on for good (for example enabling an MCP endpoint) is a System Parameter (question 3), not a rollout switch.

### 2.1 The Intent Test

**A System Parameter is a value an operator can decide from the business, without knowing how the platform is built.**

A value can satisfy every mechanical rule in §3 and still have no business meaning — `job_worker_concurrency` did, which is why it was admitted and later retired (§5.2). The intent test is asked first.

| # | Clause | It fails when |
| --- | --- | --- |
| 1 | The reason for the value is stateable in the organisation's own vocabulary: a policy, a risk tolerance, a commitment to users, a governance cap | Explaining the parameter requires first explaining pools, loops, queues, connections, or replicas |
| 2 | The value is decided from intent — "is eight hours our session policy?" | Choosing a good value requires reading metrics or profiling, making it the deployment operator's call, not the business operator's |
| 3 | Changing it changes what the platform promises | It changes only how fast the platform keeps a promise that itself did not change |
| 4 | The value is the whole of the quantity being decided | The operator-visible effect is the product or sum of this value and a knob living elsewhere, so the page offers half a control |

Clause 4 covers a second half living in a deployment system, a process supervisor, or a container command line; a value with two homes is forbidden by §10 regardless of the kind of second home. A key that fails the intent test is not rescued by a tighter range, a better help string, or an apply note. It has a different home in §2, most often question 4: an in-code constant, changed by a release.

### 2.2 Current Environment Surface

Applying the test to `docs/env.md` gives a fixed classification. This is the reference answer; it is not re-argued per key.

| Variable | Home |
| --- | --- |
| `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`, `REFRAQ_STORE_BACKEND`, `REFRAQ_API_HOST`, `REFRAQ_API_PORT`, `REFRAQ_ENV`, `TZ`, `REFRAQ_INTEGRATION_*` | Environment variable |
| `ADMIN_SESSION_SECRET`, `INITIAL_ADMIN_ACCOUNT`, `INITIAL_ADMIN_PASSWORD`, `REFRAQ_SECRETS_MASTER_KEY` | Environment variable (secret; never a System Parameter) |
| `ADMIN_SESSION_TTL_HOURS`, `REFRAQ_JOB_LOST_DETECTION_SEC` | **System Parameter** — registered (§5); the variables leave `.env` |
| `REFRAQ_JOB_WORKER_CONCURRENCY` | Neither. Worker pool size is owned by the deployment and set on the worker command line (§5.2); the variable is retired |
| `REFRAQ_CATALOG_FAIL_SAFE_THRESHOLD`, `REFRAQ_QUERY_TIMEOUT_SEC`, `REFRAQ_QUERY_MAX_ROWS` | **System Parameter** candidates owned by `metadata`; not registered yet (§5.1) |
| `REFRAQ_EMBEDDING_API_URL`, `REFRAQ_EMBEDDING_MODEL`, `REFRAQ_EMBEDDING_TIMEOUT_SEC` | Neither. Retired. Catalog Search hybrid is an in-use **Model Service** (`docs/business-model-services.md`); leftover names are ignored and reported at startup |

## 3. Admission Rules

A key is a System Parameter only if it passes the intent test (§2.1) **and** satisfies all eight rules below. The intent test decides whether the value is the operator's to decide at all; these eight decide whether the mechanism can carry it safely. Failing one means the key belongs elsewhere.

1. **Site-wide** — one value serves the whole site.
2. **Runnable without the operator** — a fresh install runs. A parameter may ship unset (`seed` is null); the consumer reads "not configured" as "feature not enabled". No System Parameter's absence prevents the process that serves Platform Settings from starting.
3. **Constrained, not necessarily bounded** — a declared type plus a constraint. Integer bounds are optional and exist only where a real cliff or stated policy exists. A value that fails the current constraint is not fatal: consumers derive a safe value from the constraint, and the catalog serves the stored value so the operator can see and clear it.
4. **Secret is a mechanism, not a ban** — a secret parameter is encrypted at rest (`backend/core/secrets.py`), write-only, never returned. The wire carries whether a value exists plus the change Instant; audit records the change without the value. Bootstrap credentials and the secrets master key stay environment variables. This slice registers no secret key; the shape is stated so the next one does not invent a second home.
5. **Declared apply** — the parameter states when a change takes effect and whether an operator action is required.
6. **Reversible** — reset returns the seed, including unset.
7. **Owned** — exactly one package consumes it, declares it, and provides the typed accessor and the apply behavior.
8. **Observable** — `source`, changed-at, and changed-by are visible in the Console, and writes produce a **Management Audit Event** (`resource_type` `system_parameter`). Secret parameters show presence, not the value.

## 4. Ownership And Division Of Labor

| Concern | Owner |
| --- | --- |
| Admission (is this a System Parameter at all) | Architecture review against §2.1, then §2 and §3; the outcome lands in this document |
| Declaration (key, constraint, seed, apply, i18n keys, group) | The package that **consumes** the parameter |
| Storage, seed occupy, resolution, last-known-good, reset, audit, HTTP | The mechanism, `backend/admin/system_parameters/` |
| Assembly (collecting declarations into one registry) | Composition |
| Apply behavior | The **consumer**, by reading at its own boundary |
| Presentation | One catalog-driven Console panel, with no per-key frontend code |

### 4.1 The Mechanism Does Not Know Domain Language

The mechanism stores keys and values and never names an occupancy window, a Beat loop, or a Session.

- **Pull, not push.** The store never calls into a domain to apply a change, reload a service, or restart a process. Each consumer reads at its own boundary: per use, at object creation, at process start, or when it writes through to another row.
- **Apply is presentation metadata.** The spec carries `operator_action_required` and an apply note i18n key. Real apply behavior lives in the consumer, so "restart required" is a consequence of where the consumer reads, not a flag the mechanism maintains.
- A background reload job, a settings-to-service callback, or a change-signal fan-out is out of scope. Cross-process consistency comes from reading the store, not from broadcasting.

### 4.2 Declaration And Assembly

- Each owning package declares its specs in `<package>/parameters.py` and publishes both the spec list and its **typed accessors**. The mechanism publishes only a generic resolver, so no function inside `admin` is named after another package's concept.
- Composition assembles the registry from those published spec lists and then runs seed occupy, reusing the existing product-seed path (`ensure_product_type_mappings`); no new pattern is introduced.
- The API process and the worker / Beat process both assemble and occupy. Occupy is insert-if-missing and safe to run concurrently.
- The assembled registry is frozen after composition. Reading an unregistered key is an error, so a process that forgets a declaration fails at boot rather than silently falling back.
- Product seed occupy has the same meaning as for **Type Mapping** seeds: write only when the row is missing, never overwrite an operator value, and reset restores the seed.

### 4.3 Spec Fields

| Field | Notes |
| --- | --- |
| `key` | Stable identifier; flat; does not encode the owner (§7) |
| `constraint` | Typed authoring (`IntConstraint` in this slice) rendered onto the wire as a JSON Schema fragment under a closed profile (`type`, `minimum`, `maximum`, `enum`, `pattern`, `maxLength`). Bounds are optional. `title` / `description` are unused; naming and copy stay the i18n keys. Unlike Connector Specs (a literal document handed to an engine), parameter constraints are a closed profile, so construction itself forbids `if` / `$ref` / nesting |
| `seed` | Product default; installed by occupy. Null means not configured |
| `owner` | Declaring package; code-side metadata, freely refactored |
| `group` | Console grouping; code-side metadata |
| `operator_action_required` | Whether applying needs an action outside Platform Settings |
| `apply_note_key` | i18n key describing exactly when the change takes effect |
| Label / help i18n keys | Console copy; never hard-coded English in the panel |
| Secret (code-side, later) | Whether the value is encrypted write-only. Not on the wire as a type; the catalog omits the value |

## 5. Registered Parameters

| Key | Owner | Seed | Range | Operator action | Applies |
| --- | --- | --- | --- | --- | --- |
| `job_lost_detection_sec` | `jobs` | 60 | 15–3600 | No | Widening is live; tightening waits one old renew interval (`max(5, previous/3)` s) before the reaper cutoff shrinks. The hidden system reaper **Scheduled Task** interval is derived from this same value, so the operator's one field is the whole of lost-detection latency |
| `admin_session_ttl_hours` | `admin` | 8 | 1–168 | No | New **Session**s only; existing sessions keep their `expires_at` |
| `sso_pending_ttl_days` | `admin` | 7 | 1–30 | No | Only new pending federated identities; existing `expires_at` values do not change |

Ownership follows business language, not the file that reads the value: occupancy lost-detection is a **Job** primitive, so `jobs` owns it even though `worker` reaps.

### 5.1 Known Candidates Not Yet Registered

`REFRAQ_CATALOG_FAIL_SAFE_THRESHOLD`, `REFRAQ_QUERY_TIMEOUT_SEC`, and `REFRAQ_QUERY_MAX_ROWS` pass §2 and §3 and are owned by `metadata`. They stay environment variables until that slice is delivered. They are listed so their membership is not re-argued, and because they are why the registry must not live inside one package's catalog. A small registered set is the expected shape of this page; it grows when values that are genuinely the operator's arrive.

### 5.2 Retired

Admission was reopened to let more in, so the original six were re-tested rather than grandfathered. Four fail the intent test. They are recorded as verdicts, not precedent.

| Key(s) | Owner / seed | Intent failure | Home |
| --- | --- | --- | --- |
| `job_worker_concurrency` | `worker` / 1 (range 1–32) | Deployed capacity is `replicas × concurrency`; a site-wide value owns one factor of a quantity whose other factor belongs to the deployment (clause 4, rule 1). The Console shows a value the worker read once at start (rule 8); "restart the worker" routes the operator to the deployment where the flag would have been set (rule 5) | Worker command line, owned by the deployment. Compose sets no flag, so Celery's default (CPU count) applies. Retired seed was 1, so this is a deliberate change in deployed behaviour |
| `beat_sync_every_sec`, `beat_max_interval_sec` | `worker` / 30, 5 | No operator has a business reason to prefer one Beat loop interval over another; they would change either value only after an engineer read a graph (clauses 1–3) | In-code constants `BEAT_SYNC_EVERY_SEC = 30`, `BEAT_MAX_INTERVAL_SEC = 5`, changed by a release (§2 question 4) |
| `reaper_interval_sec` | `worker` / 60 | Effective detection latency ≈ `job_lost_detection_sec` + reaper interval — half a control (clause 4) | Derived in code from `job_lost_detection_sec`; Beat copies the derived value onto the hidden reaper row's `interval_seconds` without recomputing `next_run_at`. Operators never PATCH that row |

## 6. Value Lifecycle

- **Effective stored value** is the row. There is no environment baseline and no in-process overlay beside the store. A leftover environment variable whose name matches a registered key is ignored and reported at startup as dead.
- **Catalog reads are strict.** `read_stored_parameter` returns the stored value untouched. A store error or unreadable row raises — Platform Settings must not present seed or last-known-good as if they were the stored catalog.
- **Consumers read a safe value.** `resolve_int` admits the stored value against the constraint and otherwise falls back: nearest declared bound, else the seed. Unset stays unset — the consumer is not handed a substitute number for "not configured". On store error or unreadable row, `resolve_int` uses last-known-good, then the in-code seed (or unset). Never an environment variable.
- **`source`** is `seed` until an operator writes the key, then `user`. Reset returns it to `seed`. Writing a value that equals the seed still makes the source `user`; source records provenance, not equality. An unrecognised stored `source` is a corrupt row: the catalog raises; consumers take the read-failure path (last known good, then seed).
- **Reset** writes the seed back, including unset. It does not delete the row, so history and attribution stay intact.
- **The row is a change record**, not only a slot: it keeps the current value, the previous value, the change Instant, and the acting **User**. A consumer whose apply needs a grace window (today `job_lost_detection_sec`) computes it from the previous value (after the same constraint fallback) and the change Instant, so the rule holds across processes and restarts. Deriving that from the audit trail is forbidden — audit is not a control-flow dependency.
- **Reads take no TTL cache.** Each consumer reads at its own boundary.
- **Out-of-constraint stored values are not fatal.** A narrowed constraint must not stop a process from starting. The catalog serves the stored value; the Console flags it from the constraint.
- The memory backend is process-local and for automated tests only.

## 7. Catalog Lifecycle

- **Keys are stable identifiers and stay flat.** Owner and group are spec fields, so a parameter can move package or Console group with no data migration. Encoding the owner into the key trades a rename migration for cosmetic grouping.
- **Adding a key needs no Alembic migration** — declare the spec, add one row to §5, add locale copy. Occupy installs the row at next start.
- **Changing a seed is not retroactive.** Occupy only fills a missing row, so existing sites keep the old value and new installs get the new one. Retroactive change requires an explicit, documented migration.
- **Deprecating**: mark the spec deprecated, stop reading it, then delete the row in a later release.
- **A key name is never reused for a new meaning.** Retire it and add a new key.

## 8. Console

- One route, `/console/settings`, one panel rendered from the catalog payload. No second-level Settings navigation and no per-key page.
- Each parameter shows its value control bounded by the declared range, its `source`, who changed it and when, its apply note, and a per-key reset. When a registered key sets `operator_action_required`, the panel distinguishes it; none of the current keys do.
- Permissions stay `settings:read` and `settings:write`.
- Platform Settings presents System Parameters only. Reference data with its own lifecycle (**Type Mapping**, Business Domains) stays in its own module and does not migrate onto this page.

## 9. Growth Triggers

Stated in advance so the design changes only for a named reason.

- **A knob becomes scoped** (per tenant, workspace, or Data Product): it is not a System Parameter. The site-wide table remains the instance default and a scoped mechanism is a separate table and cascade. No `scope` column is added here.
- **Non-administrators must read a parameter**: add a visibility field to the spec. Default stays administrator-only.
- **The set grows past roughly fifteen keys**: groups already exist in the spec, so the panel holds; revisit only the page layout.
- **A registered key stops passing the intent test** (§2.1), or is found never to have passed it: retire it to the home §2 gives it and record the verdict in §5.2. Narrowing its range or rewriting its help text is not a fix.
- **A parameter needs a value type other than integer:** extend `value` with that type, add a typed constraint class that renders a profile fragment, and ship the Console control in the same change. Do not register a key whose type the panel cannot edit.
- **The mechanism starts naming domain concepts**: the §4 division has broken down. Fix the declaration ownership rather than splitting the package.
- **The mechanism outgrows the platform kernel** (its own lifecycle, scopes, non-Console consumers): promote it to a platform primitive beside `jobs`. Not before.

## 10. Non-Goals

- An environment baseline with a database overlay, or any second home for a registered key
- A settings-side reload, callback, or polling job that applies values into domains
- Bootstrap credentials or the secrets master key in the store (secret *parameters* are a later mechanism; those two stay environment variables)
- Temporary rollout switches, experiment flags, or kill switches
- Engineering tuning knobs — pool sizes, worker or replica counts, loop and poll intervals, buffer and batch sizes — whose value is chosen from telemetry rather than business intent, and whose real owner is the deployment or an in-code constant
- Per-object knobs (a **Scheduled Task** field, including **Running Time Limit**; a **Source** `access` document) and per-**User** preferences
- Reference data catalogs on the Platform Settings page
- Runtime-defined parameters: the catalog is code, and there is no admin UI to create a key
- A System Parameter whose absence prevents the process that serves Platform Settings from starting
