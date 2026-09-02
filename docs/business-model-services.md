# refraq Business Rules: Model Services

## 1. Scope

This document defines **Model Service**: a site-wide, operator-managed external model endpoint. The first purpose is Catalog Search embedding. It does not define System Parameters, Source access, Identity Providers, or an LLM purpose.

Related boundaries:

- Terminology: `docs/glossary.md` and root `CONTEXT.md`.
- HTTP: `docs/api-contracts-model-services.md`.
- Catalog Search ranking: `docs/business-metadata.md` §10.5 and `docs/adr/0037-catalog-search-hybrid-ranking.md`.
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

`openai_compat` posts `{ "model", "input": [string, …] }` to the configured **full** embeddings URL and reads `{ "data": [{ "index", "embedding" }] }`. A configured API key is sent as `Authorization: Bearer`. The product does not append `/v1/embeddings`. Timeout is an in-code constant.

Model and protocol are editable on a draft (not in use). They are immutable while the record is in use. Changing model or protocol means create another record, test it, and set it in use.

## 4. In Use, Closed, And Ready

There is no separate “clear in use” action. Temporary stop uses **close**. Discarding a connection uses **delete**. Replacing a connection uses **set in use** (the previous in-use row becomes a draft). Absence of an in-use service comes from never setting one, or from deleting the in-use row.

**Close** is a purpose-level vector switch. It does not lock the form, change field rules, or forbid test / set-in-use / URL or secret edits / delete. Search is lexical while closed. Incremental structure and semantics embedding writes do not run while closed. Close does not cancel an in-flight `catalog_embed` Job.

**Open** tests the current in-use service first. Failure leaves the purpose closed. There is no in-use service → open is refused. After a successful test the operator chooses **no recompute** or **full recompute**. Open does not scan the index. No recompute does not mint a Job: hybrid returns only when the ready bit is still set; otherwise search stays lexical. Full recompute clears the ready bit and mints `catalog_embed`.

**Ready** is not computed by scanning vectors. It is a bit the last successful `catalog_embed` Job writes. Cleanup, or the start of any rebuild (set in use, in-use URL change, rebuild-now, or open with full recompute), clears it. Hybrid reads only this bit (plus in-use and not closed).

**Cleanup** is a one-shot: delete that purpose’s catalog embedding rows and clear ready. It is allowed only when the purpose is closed or has no in-use service. It is refused while open with an in-use service. It does not mint a Job. An in-flight `catalog_embed` Job is cancelled first.

Delete of an in-use record removes the row and secret, leaves the purpose with no in-use service, makes search lexical immediately, cancels an in-flight `catalog_embed` Job, and does not clean the index. Delete of a draft does not affect search or cancel a rebuild.

## 5. Operator Actions

| Intent | Action | Search | Index / ready | Rebuild Job |
| --- | --- | --- | --- | --- |
| Pause remote calls | Close | Lexical immediately | Kept | No |
| Resume using the current index | Open, no recompute | Hybrid iff ready | Unchanged | No |
| Resume and align the closed window | Open, full recompute | Lexical until Job success | Ready cleared at start | Yes |
| Drop stored vectors | Cleanup (closed or no in-use) | Already lexical | Rows deleted; ready cleared | No (cancel in-flight) |
| Index after cleanup | Rebuild-now, or open with full recompute | Lexical until success | Ready set on success | Yes |
| Replace wiring or change in-use URL | Set in use / patch URL (test first; URL change must resupply or explicitly clear the secret) | Lexical immediately | Ready cleared at start | Yes |
| Rotate secret only | Patch secret (test first) | Hybrid continues | Unchanged | No |
| Discard the record | Delete (in-use allowed) | Lexical if it was in use | Index not cleaned; cancel in-flight if in use | No |

Set in use while closed still starts a rebuild. Incremental writes stay off until open.

Display-name-only edits do not require a test. URL or secret changes require a test before save. An in-use URL change must not reuse a stored secret against the new URL.

## 6. Rebuild Job

`catalog_embed` is a Job kind minted by Model Service HTTP (`trigger_kind=user`), not by a **Scheduled Task**, not by `POST /jobs`, and not by MCP. Input includes `model_service_id` (and may include `generation`). Summary is `catalog_embed · {display_name}`.

Rebuilds that start from set-in-use, in-use URL change, rebuild-now, or open with full recompute cancel an in-flight same-kind Job cooperatively, then mint a new one. Cleanup and delete of the current in-use service cancel without minting.

After claim, the runner takes a site-wide **Kind execution lock** named `catalog_embed` (not per-**Source**). Contention ends that Job `failed` with `JOB_ALREADY_ACTIVE`.

The Job rewrites object and column embedding rows for the current generation. Skip compares `(content_hash, generation)`: `content_hash` is the text sent to embed; generation is its own column. The Job result records attempted / written / failed / skipped counts per kind and, on success, `failure_reasons` (distinct embed error messages with counts). The run log reports per-Source planned totals, throttled written/failed/skipped heartbeats, and the same deduplicated embed failure reasons. Progress and reasons are not written onto public Job fields or purpose state. Observe remains `GET /jobs`. Per-row embed failures do not fail the Job when at least one vector was written. A run that writes no vectors against a non-empty catalog fails and does not set ready; its `error_summary` includes the dominant embed reason when one was recorded. Success writes the ready bit only when the Job’s service and generation are still current. Failure leaves the service in use and search lexical. The operator starts another rebuild without switching services. Hybrid does not scan rows for a partial index. Cooperative cancel is honored at embed-batch boundaries.

While a rebuild runs, structure-commit and semantics incremental writes (if the purpose is not closed) use the new wiring and the current generation. Search stays lexical until ready is set, so a half-written index is not a product state.

## 7. Catalog Search

Hybrid rank is on only when an embedding Model Service is in use, the purpose is not closed, and ready is true. Otherwise Catalog Search is the lexical ladder — a complete rank, not a degraded mode. A failed query embedding call uses the lexical store page for that request and does not close the purpose or clear ready. Catalog Search `total` is the lexical filtered-set count on every path (ADR 0037).

HTTP, Console callers of those endpoints, and MCP share this rank.

## 8. Secrets And Environment

The API key is encrypted at rest, write-only, and never returned. Reads expose `has_secret`. An omitted key on patch keeps the stored secret when the URL is unchanged. A URL change (draft or in use, test or save) requires a new key or an explicit no-key declaration.

`REFRAQ_EMBEDDING_API_URL`, `REFRAQ_EMBEDDING_MODEL`, and `REFRAQ_EMBEDDING_TIMEOUT_SEC` are dead. They are ignored, reported at startup, and never imported into a Model Service.

## 9. Audit And Console

Create, update, test, set-in-use, close, open, cleanup, rebuild-now, and delete produce **Management Audit Event**s (`resource_type` `model_service`). Audit detail must not include the API key.

The Console Module `model-services` lives in the `settings` nav group. The page must show the closed-state note (structure and semantics edits during the closed window do not enter the index automatically) and the open confirmation as a choice, not an announcement. Set-in-use on a draft row is labeled **Enable**; its confirm title is **Enable this service?**. Status remains **In use**. **Enable** is not **open**. Any Console action that mints `catalog_embed` (set in use, rebuild-now, open with full recompute) confirms before minting. An in-use URL save that mints stays a form submit and does not add a second confirm.

## 10. Non-Goals

- LLM purpose or a second protocol
- A System Parameter or env home for the embeddings URL
- A separate “clear in use” action
- Defaulting open to a rebuild, scanning the store for ready, or a “partially ready” product state
- Blue-green dual indexes, an in-process LiteLLM gateway, `/models` as the connectivity test, or sharing one record between chat and embedding
- MCP observe or mint of `catalog_embed`

## 11. References

- `docs/api-contracts-model-services.md`
- `docs/adr/0039-model-services-and-catalog-embed.md`
- `docs/adr/0037-catalog-search-hybrid-ranking.md`
- `docs/business-metadata.md`
- `docs/business-jobs.md`
