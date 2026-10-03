# refraq Business Rules: Model Services

## 1. Scope

This document defines **Model Service**: a site-wide, operator-managed external model endpoint. The first purpose is Catalog Search embedding. It does not define System Parameters, Source access, Identity Providers, or an LLM purpose.

Related boundaries:

- Terminology: `docs/glossary.md` and root `CONTEXT.md`.
- HTTP: `docs/api-contracts-model-services.md`.
- Catalog Search ranking: `docs/business-metadata.md` §10.5 and `docs/adr/0043-catalog-search-vector-complete-state.md`.
- Decision: `docs/adr/0039-model-services-and-catalog-embed.md`.
- Jobs: `docs/business-jobs.md`.
- Console IA: `docs/business-management-console.md`.
- Environment leftovers: `docs/env.md`.

## 2. Resource And Ownership

A **Model Service** is one named connection (purpose + protocol + wiring). The Management Foundation owns the registry as the `model_services` language unit under `backend/admin/`. It is not a **System Parameter**, not a Metadata domain object, and not Account Center.

Catalog Search consumes the in-use embedding service through the published admin API. Metadata must not read the Model Service store.

Each record has:

- a stable id
- `purpose` (`embedding` in this document; `llm` is out of scope)
- `protocol` (`openai_compat` in this document)
- display name
- protocol configuration (full embeddings URL, model name, optional API key)
- audit timestamps

Purpose state is site-wide per purpose, not a field of one row:

- at most one in-use Model Service
- a vector **closed** switch
- a **ready** bit written only by a successful `catalog_embed` **Job**
- a generation used to tag catalog embedding rows

Permissions are `model_services:read` and `model_services:write`. Seeded Roles other than Super Admin do not receive write.

## 3. Purpose And Protocol

Purpose says what the connection is for. Protocol says how to speak to it. Additional purposes and protocols are new values on the same object type.

`openai_compat` posts `{ "model", "input": [string, …] }` to the configured **full** embeddings URL and reads `{ "data": [{ "index", "embedding" }] }`. A configured API key is sent as `Authorization: Bearer`. The product does not append `/v1/embeddings`. Probe, index batch, and query embed share the in-use Model Service `timeout_sec` (integer seconds, 15–300; existing rows are 30). A failed query embed waits that full interval. Changing `timeout_sec` on an in-use row applies on the next call and does not clear ready, cancel `catalog_embed`, or mint a rebuild. `TIMEOUT_SEC` remains the default of 30, not the live deadline. Index and query vectors are projected to `EMBEDDING_OUTPUT_DIM` (1024) by prefix truncation and L2-normalize when the model returns a longer vector. Probe reports the native width and `elapsed_ms` as an observation, not a threshold.

Model and protocol are editable on a draft (not in use). They are immutable while the record is in use. Changing model or protocol means create another record, test it, and set it in use.

## 4. In Use, Closed, And Ready

There is no separate “clear in use” action. Temporary stop uses **close**. Discarding a connection uses **delete**. Replacing a connection uses **set in use** (the previous in-use row becomes a draft). Absence of an in-use service comes from never setting one, or from deleting the in-use row.

**Close** is a purpose-level vector switch. It does not lock the form, change field rules, or forbid test / set-in-use / URL or secret edits / delete. Search is lexical (process state) while closed. A due `catalog_embed` Job that finds the purpose closed succeeds without writing and does not clear ready. Close does not cancel an in-flight Job and does not change the site schedule’s enabled flag.

**Open** tests the current in-use service first. Failure leaves the purpose closed. There is no in-use service → open is refused. Open does not scan the index and does not mint a Job. Vector Search returns only when the ready bit is still set; otherwise search stays lexical.

**Ready** is not computed by scanning vectors. It is a bit a completed `catalog_embed` Job writes when that sweep finishes under the current service and generation. A skipped Job does not write it. Cleanup, set in use, and an in-use URL change clear it. Vector Search reads only this bit (plus in-use and not closed). Purpose `index_status`, while ready is false, is `indexing` when any `catalog_embed` Job is non-terminal, `failed` when the latest sweep (a Job whose result `outcome` is not `skipped`) is `failed`, and `none` otherwise. A skipped Job does not change that status.

**Cleanup** is a one-shot: delete that purpose’s catalog embedding rows and clear ready. It is allowed only when the purpose is closed or has no in-use service. It is refused while open with an in-use service. It is also refused while a `catalog_embed` Job is non-terminal. It does not mint a Job and does not cancel one.

Delete of an in-use record removes the row and secret, leaves the purpose with no in-use service, makes search lexical immediately, and does not clean the index or cancel an in-flight Job. Delete of a draft does not affect search.

## 5. Operator Actions

| Intent | Action | Search | Index / ready | Embed Job |
| --- | --- | --- | --- | --- |
| Pause remote calls | Close | Lexical immediately | Kept | Due ticks skip until open |
| Resume using the current index | Open | Vector iff ready | Unchanged | No |
| Drop stored vectors | Cleanup (closed or no in-use, and no Job running) | Already lexical | Rows deleted; ready cleared | No |
| Replace wiring or change in-use URL | Set in use / patch URL (test first; URL change must resupply or explicitly clear the secret) | Lexical immediately | Ready cleared; generation increments; schedule run-now | Yes |
| Rotate secret only | Patch secret (test first) | Vector continues | Unchanged | No |
| Discard the record | Delete (in-use allowed) | Lexical if it was in use | Index not cleaned; in-flight Job keeps running | No |

Set in use while closed still clears ready and runs the schedule now. The Job skips while closed and does not set ready. The operator runs the schedule from Operations, or waits for the next due tick after open, to fill the index.

Display-name-only and timeout-only edits do not require a test and do not rebuild. URL or secret changes require a test before save. An in-use URL change must not reuse a stored secret against the new URL.

## 6. Rebuild Job

`catalog_embed` is a Job kind minted only by the site **Scheduled Task** (`key` `catalog_embed:site`), not by `POST /jobs` and not by MCP. Summary is `catalog_embed`. `trigger_kind` is `schedule`. Input is empty; the runner reads the live embedding runtime. Default cadence is daily `0 3 * * *` UTC. The row is undeletable. Operators with `jobs:run` change cadence, enabled, and running time limit, and may run it now. Model Service HTTP does not pause it.

Set in use and an in-use URL change clear ready, increment generation, and call that schedule’s run-now. They do not cancel an in-flight Job. If generation or the in-use service changes while a Job is sweeping, that Job restarts the sweep itself.

After claim, the runner takes a site-wide **Kind execution lock** named `catalog_embed` (not per-**Source**). Contention ends that Job `succeeded` with `outcome=skipped` and `reason=already_active`. No in-use service, or a closed purpose, is the same skip (`no_service` or `closed`) and does not set ready.

The Job rewrites object and column embedding rows for the current generation and deletes embedding rows whose catalog target is gone. Skip compares `(content_hash, generation)`: `content_hash` is the text sent to embed; generation is its own column. The Job result records attempted / written / failed / skipped counts per kind, `orphans_deleted`, and, on success, `failure_reasons` (distinct embed error messages with counts). The run log reports per-Source planned totals, throttled written/failed/skipped heartbeats, and the same deduplicated embed failure reasons. Progress and reasons are not written onto public Job fields or purpose state. Observe remains `GET /jobs` and the schedule’s related Jobs. Per-row embed failures do not fail the Job when at least one vector was written, except when client-deadline rows (connect or read) outnumber written rows: the Job then stops at the next batch boundary, fails, and does not set ready. A run that fails every pending row against a non-empty catalog fails and does not set ready; a run that skips every row because it is already current succeeds and may set ready. Success writes the ready bit only when the Job’s service and generation are still current. Failure leaves the service in use and search lexical. Vector Search does not scan rows for a partial index. Cooperative cancel is honored at embed-batch boundaries. Cancel, abort, and restart are also noticed during catalog load, at the same cadence as the load heartbeat.

Structure commit and semantics writes do not call the embedding client. Search stays lexical until ready is set, so a half-written index is not a product state.

## 7. Catalog Search

Complete-state rank is vector nearest-neighbor when an embedding Model Service is in use, the purpose is not closed, and ready is true. Otherwise Catalog Search is the lexical ladder — a declared **process state**, not a second complete rank. Each search page names the path that produced it (`rank_mode`: `vector` or `lexical`). The two values do not mean "this request fell back". A failed query embedding call, a missed model API timeout, or a neighbor-score failure is `CATALOG_SEARCH_EMBED_FAILED` / `CATALOG_SEARCH_NEIGHBOR_FAILED` and does not close the purpose or clear ready. An empty neighbor list is a successful empty vector page. `index_status` / ready describe index build, not the page. Serving-time path rate is `refraq_catalog_search_hybrid_total{outcome=vector|lexical}` on `/metrics`. `refraq_catalog_search_vector_errors_total{reason=embed_failed|no_vectors|neighbor_failed}` counts those errors. Catalog Search is a **Top-K Read** (no `total`; ADR 0043).

HTTP and MCP share this rank.

## 8. Secrets And Environment

The API key is encrypted at rest, write-only, and never returned. Reads expose `has_secret`. An omitted key on patch keeps the stored secret when the URL is unchanged. A URL change (draft or in use, test or save) requires a new key or an explicit no-key declaration.

`REFRAQ_EMBEDDING_API_URL`, `REFRAQ_EMBEDDING_MODEL`, and `REFRAQ_EMBEDDING_TIMEOUT_SEC` are dead. They are ignored, reported at startup, and never imported into a Model Service.

## 9. Audit And Console

Create, update, test, set-in-use, close, open, cleanup, and delete produce **Management Audit Event**s (`resource_type` `model_service`). Audit detail must not include the API key. Run-now of the site schedule is a schedule audit, not a model-service audit.

The Console Module `model-services` lives in the `settings` nav group. The page title is Model services. Its description only registers endpoints; it does not mention closing vectors or one in-use service per purpose. Two tabs share that route: **Configure models** (default) and **Service status**. Tab choice is not in the URL; a refresh returns to Configure models.

Configure models is the record list. Add, test, edit, delete, and set-in-use stay there. Set-in-use on a draft row is labeled **Enable**; its confirm title is **Enable this service?**. Status remains **In use**. **Enable** is not **open**. Enable runs the connectivity test first.

Service status shows the Embedding purpose: the open/closed badge, the index-status badge, open / close / cleanup, and, when closed, the closed-state note. It does not name the in-use model and does not say whether an in-use service exists. Open stays disabled when no service is in use. Cadence, enabled, last Job, and run-now of the site schedule stay on the Operations schedules module. When the operator has `jobs:run`, Service status links there.

Set in use confirms before it clears ready and runs the schedule. An in-use URL save that does the same stays a form submit and does not add a second confirm.

## 10. Non-Goals

- LLM purpose or a second protocol
- A System Parameter or env home for the embeddings URL
- A separate “clear in use” action
- Defaulting open to a rebuild, scanning the store for ready, or a “partially ready” product state
- Blue-green dual indexes, an in-process LiteLLM gateway, `/models` as the connectivity test, or sharing one record between chat and embedding
- MCP observe or mint of `catalog_embed`
- A Model Service action that inserts a `catalog_embed` Job row itself

## 11. References

- `docs/api-contracts-model-services.md`
- `docs/adr/0039-model-services-and-catalog-embed.md`
- `docs/adr/0043-catalog-search-vector-complete-state.md`
- `docs/business-metadata.md`
- `docs/business-jobs.md`
