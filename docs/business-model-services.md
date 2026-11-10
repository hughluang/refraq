# refraq Business Rules: Model Services

## 1. Scope

This document defines **Model Service**: a site-wide, operator-managed external model endpoint. The embedding purpose is one shared call used by Catalog Search and by Entity semantic search. It does not define System Parameters, Source access, Identity Providers, or an LLM purpose. Catalog ranking and Entity ranking stay with those domains.

Related boundaries:

- Terminology: `docs/glossary.md` and root `CONTEXT.md`.
- HTTP: `docs/api-contracts-model-services.md`.
- Catalog Search ranking: `docs/business-metadata.md` §10.5 and `docs/adr/0043-catalog-search-vector-complete-state.md`.
- Entity projection, Entity index readiness, and `search_entities`: `docs/business-entity.md` and `docs/api-contracts-entity-mcp.md`.
- Decision: `docs/adr/0039-model-services-and-catalog-embed.md`.
- Jobs: `docs/business-jobs.md`. Scheduled Tasks: `docs/business-scheduled-tasks.md`.
- Console IA: `docs/business-management-console.md`.
- Environment leftovers: `docs/env.md`.

## 2. Resource And Ownership

A **Model Service** is one named connection (purpose + protocol + wiring). The Management Foundation owns the registry as the `model_services` language unit under `backend/admin/`. It is not a **System Parameter**, not a Metadata domain object, and not Account Center.

Catalog Search and Entity semantic search call `embed_texts(texts, *, expected_generation, expected_control_revision=None)` on `backend.admin.model_services`. The call resolves the in-use row, splits by `batch_limit`, applies `timeout_sec`, validates the provider document, restores input order, and projects vectors. Callers do not read the Model Service store and do not assemble the protocol request. Metadata must not read the Model Service store. `entity` must not import `metadata`.

Each record has:

- a stable id
- `purpose` (`embedding` in this document; `llm` is out of scope)
- `protocol` (`openai_compat` in this document)
- display name
- protocol configuration (full embeddings URL, model name, optional API key)
- `timeout_sec` (integer seconds, 15–300)
- `batch_limit` (integer, 1–32; default 32)
- audit timestamps

Purpose state is site-wide per purpose, not a field of one row:

- at most one in-use Model Service
- a vector **closed** switch
- a generation that identifies the embedding space for both consumers
- a control revision that fences in-flight calls, index writes, and ready publication; it is not part of embedding-space identity
- processing contract `prefix-1024-l2-v1`
- a `ready` column on `model_service_purposes` that a successful `catalog_embed` publish still writes; Catalog Search does not read that column

Catalog readiness is the `ready` bit on `catalog_index_state`. Entity readiness is the `ready` bit on `entity_index_state`. Neither bit is model health, and neither bit is the other domain's readiness.

Permissions are `model_services:read` and `model_services:write`. Seeded Roles other than Super Admin do not receive write.

## 3. Purpose And Protocol

Purpose says what the connection is for. Protocol says how to speak to it. Additional purposes and protocols are new values on the same object type.

`openai_compat` posts `{ "model", "input": [string, …] }` to the configured **full** embeddings URL and reads `{ "data": [{ "index", "embedding" }] }`. A configured API key is sent as `Authorization: Bearer`. The product does not append `/v1/embeddings`. Probe, index batch, and query embed share the in-use Model Service `timeout_sec`. A failed query embed waits that full interval. Changing `timeout_sec` on an in-use row applies on the next call. It does not advance generation, bump the control revision, clear either index ready bit, cancel an embed Job, or mint a rebuild. `TIMEOUT_SEC` remains the default of 30, not the live deadline.

`batch_limit` is how many input strings one provider request may carry. The shared call splits a longer list into consecutive chunks of that size and concatenates the vectors in input order. The default is 32. A value outside 1–32 is rejected. Changing `batch_limit` applies on the next call and does not advance generation or the control revision.

Vectors longer than 1024 are prefix-truncated to 1024 and then L2-normalized. A prefix whose norm is zero is returned unscaled. Vectors of length 1024 or shorter pass through, including a shorter vector that is not normalized. The processing contract for that rule is `prefix-1024-l2-v1`. A stored contract other than the current one advances generation, bumps the control revision, clears both index ready bits, and asks both site schedules to run. The current contract does not. Probe reports the native width and `elapsed_ms` as an observation, not a threshold. Projection does not claim that truncation preserves model quality.

Model is editable on a draft and on the in-use row. Protocol is editable on a draft and immutable while the record is in use. An in-use protocol change is refused. An in-use model change that passes the connectivity test advances generation the same way an in-use URL change does.

## 4. In Use, Closed, And Ready

There is no separate “clear in use” action. Temporary stop uses **close**. Discarding a connection uses **delete**. Replacing a connection uses **set in use** (the previous in-use row becomes a draft). Absence of an in-use service comes from never setting one, or from deleting the in-use row.

Generation advances when the in-use service changes, when the in-use URL changes, when the in-use model changes, when the operator forces a generation, or when the stored processing contract is not current. Each of those commits both consumers' rebuild intent before either enqueue: both index ready bits clear, both indexes record that a rebuild is owed, and each site schedule is asked to run. One domain's sweep does not wait for the other. Secret-only, timeout-only, batch-limit-only, and display-name-only edits do not advance generation and do not bump the control revision.

**Close** is a purpose-level vector switch. It bumps the control revision and does not change generation. It does not lock the form, change field rules, or forbid test / set-in-use / URL, model, or secret edits / delete. Catalog Search is lexical (process state) while closed. Entity semantic search is refused while closed. Both indexes keep their current-generation vectors and their ready bits. A due `catalog_embed` or `entity_embed` Job that finds the purpose closed succeeds without writing and does not clear ready. Close does not cancel an in-flight Job and does not change either site schedule’s enabled flag.

**Open** tests the current in-use service first, then bumps the control revision and clears `closed`. Failure leaves the purpose closed. There is no in-use service → open is refused. Open does not scan either index, does not change generation, and does not mint a Job. Catalog vector search returns when the Catalog index ready bit is still set. Entity semantic search returns when the Entity index is ready on the current generation. Retained vectors of that generation stay usable.

**Catalog ready** is not computed by scanning vectors. A completed `catalog_embed` Job writes `catalog_index_state.ready` when that sweep finishes under the current service, generation, and control revision. The same publish writes `model_service_purposes.ready`. Catalog Search reads `catalog_index_state.ready` (plus in-use, a URL, and not closed). It does not read the purpose column. A skipped Job does not write the Catalog bit. Purpose `index_status` is the Catalog index status: while that ready bit is false, it is `indexing` when any `catalog_embed` Job is non-terminal, `failed` when the latest sweep (a Job whose result `outcome` is not `skipped`) is `failed`, and `none` otherwise. A skipped Job does not change that status.

**Entity ready** is `entity_index_state.ready`. A completed `entity_embed` sweep writes it only when every current target succeeded, including a sweep whose current target set is empty. After that bit is set, a later sweep that fails some current targets leaves the bit set and records the gap. That gap rule is Entity's. It does not change Catalog's partial-failure rule (§6). Entity `index_status` uses the same `none` | `indexing` | `ready` | `failed` ladder over `entity_embed` sweeps.

A publish whose generation or control revision is no longer current does not set either ready bit. Closing, switching, forcing a generation, or cleaning must not let an older call or Job restore ready.

**Cleanup** deletes Catalog embedding rows and Entity projection rows, clears both ready bits, and does not record a rebuild owed. It bumps the control revision and does not change generation. It is allowed only when the purpose is closed or has no in-use service. It is refused while open with an in-use service. It is also refused while a `catalog_embed` or `entity_embed` Job is non-terminal. It does not mint a Job, does not cancel one, and does not refill either index.

**Force generation** advances generation for a provider-side model replacement that kept the same URL and model. Stored vectors stay until a later sweep replaces them or cleanup deletes them. Search stops using the old space because both ready bits clear and the generation no longer matches.

Delete of an in-use record removes the row and secret, leaves the purpose with no in-use service, makes Catalog Search lexical immediately, and does not clean either index or cancel an in-flight Job. Delete of a draft does not affect search.

## 5. Operator Actions

| Intent | Action | Search | Index / ready | Embed Job |
| --- | --- | --- | --- | --- |
| Pause remote calls | Close | Catalog lexical; Entity search refused | Both indexes kept; generation unchanged; control revision bumps | Due ticks skip until open |
| Resume using the current indexes | Open | Catalog vector iff its index is ready; Entity search iff its index is ready on this generation | Vectors unchanged | No |
| Drop stored vectors | Cleanup (closed or no in-use, and no embed Job running) | Catalog already lexical; Entity search stays unavailable | Both row sets deleted; neither ready bit set; no refill | No |
| Replace wiring, in-use URL, or in-use model | Set in use / patch URL / patch model (test first; URL change must resupply or explicitly clear the secret) | Catalog lexical; Entity search unavailable | Both ready bits cleared; generation increments; both schedules run now | Yes, one per domain |
| Replace an undisclosed provider model | Force generation | Catalog lexical; Entity search unavailable | Both ready bits cleared; vectors kept; generation increments; both schedules run now | Yes, one per domain |
| Rotate secret, timeout, or batch limit | Patch that field (secret is tested first) | Unchanged | Generation and both ready bits unchanged | No |
| Discard the record | Delete (in-use allowed) | Catalog lexical if it was in use | Indexes not cleaned; in-flight Jobs keep running | No |

Set in use while closed still clears both ready bits and runs both schedules now. Each Job skips while closed and does not set ready. The operator runs a schedule from Operations, or waits for the next due tick after open, to fill that index.

Display-name-only, timeout-only, and batch-limit-only edits do not require a test and do not rebuild. URL, model, or secret changes require a test before save. An in-use URL change must not reuse a stored secret against the new URL.

## 6. Rebuild Job

`catalog_embed` is a Job kind minted only by the site **Scheduled Task** (`key` `catalog_embed:site`), not by `POST /jobs` and not by MCP. Summary is `catalog_embed`. `trigger_kind` is `schedule`. Input is empty; the runner reads the live embedding runtime. Default cadence is daily `0 3 * * *`, evaluated in the site `schedule_timezone` (the parameter seed is UTC). The row is undeletable. Operators with `jobs:run` change cadence, enabled, and running time limit, and may run it now. Model Service HTTP does not pause it.

`entity_embed` is a separate kind with its own site schedule (`key` `entity_embed:site`). Its readiness rule is not this section. Rules: `docs/business-entity.md`.

Set in use, an in-use URL change, an in-use model change, and force generation clear both ready bits, increment generation, and call both schedules’ run-now. They do not cancel an in-flight Job. If generation or the in-use service changes while a Catalog Job is sweeping, that Job restarts the sweep itself.

After claim, the runner takes a site-wide **Kind execution lock** named `catalog_embed` (not per-**Source**). Contention ends that Job `succeeded` with `outcome=skipped` and `reason=already_active`. The Entity lock is a different name; holding one does not block the other sweep. No in-use service, or a closed purpose, is the same skip (`no_service` or `closed`) and does not set ready.

The Job rewrites object and column embedding rows for the current generation and deletes embedding rows whose catalog target is gone. Skip compares `(content_hash, generation)`: `content_hash` is the text sent to embed; generation is its own column. The Job result records attempted / written / failed / skipped counts per kind, `orphans_deleted`, and, on success, `failure_reasons` (distinct embed error messages with counts). The run log reports per-Source planned totals, throttled written/failed/skipped heartbeats, and the same deduplicated embed failure reasons. The sweep progress string and failure summary are stored on the Catalog index and returned on purpose state. They are not separate Job columns. Observe remains `GET /jobs` and the schedule’s related Jobs. Per-row embed failures do not fail the Job when at least one vector was written, except when client-deadline rows (connect or read) outnumber written rows: the Job then stops at the next batch boundary, fails, and does not set ready. A run that fails every pending row against a non-empty catalog fails and does not set ready; a run that skips every row because it is already current succeeds and may set ready. Success writes the Catalog index ready bit only when the Job’s service, generation, and control revision are still current, and writes the purpose `ready` column in that same publish. Failure leaves the service in use and Catalog Search lexical. Vector Search does not scan rows for a partial index. Cooperative cancel is honored at embed-batch boundaries. Cancel, abort, and restart are also noticed during catalog load, at the same cadence as the load heartbeat.

Structure commit and semantics writes do not call the embedding client. Catalog Search stays lexical until the Catalog index ready bit is set, so a half-written Catalog index is not a product state.

## 7. Catalog Search

Complete-state rank is vector nearest-neighbor when an embedding Model Service is in use, the purpose is not closed, and `catalog_index_state.ready` is true. Otherwise Catalog Search is the lexical ladder — a declared **process state**, not a second complete rank. Each search page names the path that produced it (`rank_mode`: `vector` or `lexical`). The two values do not mean "this request fell back". A failed query embedding call, a missed model API timeout, or a neighbor-score failure is `CATALOG_SEARCH_EMBED_FAILED` / `CATALOG_SEARCH_NEIGHBOR_FAILED` and does not close the purpose or clear ready. An empty neighbor list is a successful empty vector page. Catalog `index_status` and the Catalog ready bit describe index build, not the page. Serving-time path rate is `refraq_catalog_search_hybrid_total{outcome=vector|lexical}` on `/metrics`. `refraq_catalog_search_vector_errors_total{reason=embed_failed|no_vectors|neighbor_failed}` counts those errors. Catalog Search is a **Top-K Read** (no `total`; ADR 0043).

HTTP and MCP share this rank. Entity semantic search is not this rank and does not fall back to the lexical ladder.

## 8. Secrets And Environment

The API key is encrypted at rest, write-only, and never returned. Reads expose `has_secret`. An omitted key on patch keeps the stored secret when the URL is unchanged. A URL change (draft or in use, test or save) requires a new key or an explicit no-key declaration.

`REFRAQ_EMBEDDING_API_URL`, `REFRAQ_EMBEDDING_MODEL`, and `REFRAQ_EMBEDDING_TIMEOUT_SEC` are dead. They are ignored, reported at startup, and never imported into a Model Service.

## 9. Audit And Console

Create, update, test, set-in-use, force generation, close, open, cleanup, and delete produce **Management Audit Event**s (`resource_type` `model_service`). Audit detail must not include the API key. Run-now of a site schedule is a schedule audit, not a model-service audit.

The Console Module `model-services` lives in the `settings` nav group. The page title is Model services. Its description only registers endpoints; it does not mention closing vectors or one in-use service per purpose. Two tabs share that route: **Configure models** (default) and **Service status**. Tab choice is not in the URL; a refresh returns to Configure models.

Configure models is the record list. Add, test, edit, delete, and set-in-use stay there. Set-in-use on a draft row is labeled **Enable**; its confirm title is **Enable this service?**. Status remains **In use**. **Enable** is not **open**. Enable runs the connectivity test first.

Service status shows the shared Embedding model and, separately, the Catalog index and the Entity index. The shared model shows the open/closed badge, whether a service is in use, and the actions **Close vectors**, **Open vectors**, **Clean indexes**, and **New generation**. Open stays disabled when no service is in use. Each index shows its own status badge, generation, coverage, and schedule, and whether a rebuild is still owed. Progress and a failure summary appear when present. When the Entity index is ready, it states that ready does not mean every incremental target succeeded. **Rebuild Catalog index** asks only that schedule to run and does not rebuild the Entity index. **Rebuild Entity index** asks only that schedule to run and does not rebuild the Catalog index. Cadence edits stay on the Operations schedules module. When the operator has `jobs:run`, Service status links there.

**Close the shared model?** names the Catalog index and the Entity index, keeps both, and does not change generation. **Clean both indexes?** names both indexes, states that both ready marks clear, and states that cleanup does not start a refill. **Start a new shared generation?** advances the shared generation, clears both ready marks, and keeps stored vectors until each index is swept again.

Set in use confirms before it clears ready and runs the schedules. An in-use URL or model save that does the same stays a form submit and does not add a second confirm.

## 10. Non-Goals

- LLM purpose or a second protocol
- A System Parameter or env home for the embeddings URL
- A separate “clear in use” action
- Defaulting open to a rebuild, scanning the store for ready, or a Catalog “partially ready” product state
- Blue-green dual indexes, an in-process LiteLLM gateway, `/models` as the connectivity test, or sharing one record between chat and embedding
- MCP observe or mint of `catalog_embed` or `entity_embed`
- A Model Service action that inserts a `catalog_embed` or `entity_embed` Job row itself
- One ready bit that means both indexes are usable

## 11. References

- `docs/api-contracts-model-services.md`
- `docs/adr/0039-model-services-and-catalog-embed.md`
- `docs/adr/0043-catalog-search-vector-complete-state.md`
- `docs/business-metadata.md`
- `docs/business-entity.md`
- `docs/business-jobs.md`
