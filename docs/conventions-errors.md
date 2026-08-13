# Error and Request ID Conventions

Authoritative HTTP failure envelope, Problem Code identity, and request correlation for refraq.
Hard trade-offs: [`docs/adr/0023-api-problem-details.md`](adr/0023-api-problem-details.md).
Domain terms: root `CONTEXT.md`, [`docs/glossary.md`](glossary.md).

**Problem Code** in this document is the machine identity of a failure (`AUTH_UNAUTHENTICATED`). It is not a **Business Domain** `code`.

## 1. Identity layers (do not mix)

| Layer | What it is | Who branches on it |
|-------|------------|--------------------|
| **Problem Code** (`code`) | Cross-surface failure identity, `UPPER_SNAKE` | First party: Console i18n, Serving SDK, MCP tool results, Job `error_code`, probe `code` |
| **`type`** | RFC 9457 identifier on the HTTP envelope, **derived** from Problem Code | Generic RFC consumers; first party **must not** switch or i18n on `type` |
| **HTTP status** | Coarse class (401/403/422/500) | Gateways / generic HTTP software |

Today: `type` = `urn:refraq:problem:{CODE}` (CODE verbatim; no kebab; no product domain). URN is a legal URI. RFC allows non-dereferenceable URIs and warns that later swapping a non-dereferenceable URI for a dereferenceable one **changes the type identity**. Therefore:

- First party always branches on **`code`**.
- When a docs site exists, `type` **may** become `https://…/problems/{CODE}` (last path segment still the same CODE) **without changing `code`**. That is a derivation-rule change, not a new identity.
- Do not stand up a live problem catalog now; do not bind a placeholder https host.

Do not use `about:blank` as `type` for business errors (that would discard Problem Code and leave only HTTP status).

## 2. Surface split

| Surface | Envelope | Shared identity |
|---------|----------|-----------------|
| HTTP (Management now; Serving/Client later) | `Content-Type: application/problem+json` | Problem Code in `code` and in `type` |
| MCP **tool result** | `{ "error": { "code", "message" } }` | Problem Code string in `error.code`. Human text stays `message`, not `detail` |
| MCP JSON-RPC **protocol** `error.code` | Integer (JSON-RPC) | **Not** a Problem Code |
| Job row | `error_code` / `error_message` on a success GET | Problem Code in `error_code` |
| Source probe | HTTP 200 `{ "ok": false, "code", "message" }` | Problem Code in `code`. Result document, not a protocol failure (RFC 9457 §1) |
| Process probes (`/healthz`, `/readyz`) | Probe JSON (`status`, …) | Not Problem Details |

## 3. HTTP Problem Details

Success responses stay `application/json`. Every HTTP **failure** (including FastAPI 422, unmatched 404, unhandled 500) uses Problem Details.

Required body fields (OpenAPI `ProblemDetails`; `additionalProperties: true`):

```json
{
  "type": "urn:refraq:problem:AUTH_INVALID_CREDENTIALS",
  "status": 401,
  "detail": "Invalid account or password",
  "code": "AUTH_INVALID_CREDENTIALS",
  "request_id": "…"
}
```

| Field | Rule |
|-------|------|
| `type` | Derived URI; see §1 |
| `status` | Same integer as the HTTP status line |
| `detail` | English occurrence text (today's `AppError.message`). Not locale-negotiated. Clients localize UI by `code` |
| `code` | Problem Code |
| `request_id` | Same value as `X-Request-ID` |
| `details` | Only for `REQUEST_INVALID` (422); omit otherwise |
| `title` / `instance` | **Not sent now**; forever optional. Adding them does not change identity. If `instance` is added later, use the request URI or `urn:uuid:…` — never as request-id |

Frozen extension names: `code`, `request_id`, `details`. Do not introduce `correlationId`, `traceId`, `errorCode`, or a second array named `errors`.

JSON naming is **snake_case** (same as the rest of the HTTP API). Do not emit a top-level `message`.

Kernel codes owned by this contract:

| Problem Code | HTTP status | When |
|--------------|-------------|------|
| `REQUEST_INVALID` | 422 | Request validation failed |
| `INTERNAL_ERROR` | 500 | Unhandled exception (`detail` is generic English; never the exception text) |
| `HTTP_NOT_FOUND` | 404 | Unmatched route |
| `HTTP_METHOD_NOT_ALLOWED` | 405 | Wrong method on a known path |
| `HTTP_ERROR` | other 4xx from Starlette `HTTPException` | Framework HTTP errors that are not 404/405 |

Domain codes stay on `AppError` subclasses (`AUTH_*`, `SOURCE_*`, …).

### 422 validation

```json
{
  "type": "urn:refraq:problem:REQUEST_INVALID",
  "status": 422,
  "detail": "Request validation failed",
  "code": "REQUEST_INVALID",
  "request_id": "…",
  "details": [
    { "field": "account", "code": "VALUE_MISSING", "message": "Field required" }
  ]
}
```

- `field` is a business path (`account`, `access.host`), not JSON Pointer, not `body.account`.
- `details[].code` is `VALUE_MISSING` or `VALUE_INVALID` — not Pydantic/FastAPI type names.
- Do not echo Pydantic `loc`, `type`, or `input` (passwords can sit in `input`).
- Do not also send RFC example name `errors`. A future JSON Pointer may be an optional `pointer` beside `field`; do not rename `field`.

### OpenAPI

Document failures as `application/problem+json` with component `ProblemDetails`: required `type`, `status`, `detail`, `code`, `request_id`; `title` and `instance` present in the schema but **not** required; `additionalProperties: true`.

## 4. Request ID

- Header name: `X-Request-ID`. Body field: `request_id`. Same value.
- Inbound: accept UUID or 32-char hex (including nginx `$request_id`); otherwise mint a new 32-hex id (reject log injection).
- Echo the header on **every** HTTP response (success and failure). Success **bodies** do not include `request_id`.
- Not Job id, not OTel `trace_id` / `traceparent`, not an idempotency key, not RFC `instance`.
- Celery: copy into task headers and worker log context. **Do not** add a Job column.
- Later tracing may add a separate `traceparent` header; never reuse `X-Request-ID` / `request_id` for that.

## 5. i18n

`detail` (HTTP) and MCP `error.message` are stable English fallbacks. Console and other first-party UIs localize by Problem Code. Never localize `code`. Do not make `Accept-Language` part of the identity. Future Serving may add `Content-Language` without changing `code`.

## 6. Implementation entry

- In-process primitive: `backend.core.errors.AppError` (`code` + `http_status` + `message`).
- HTTP mapping and Problem serialization: `backend.core.errors` + composition [`backend/main.py`](../backend/main.py).
- Request ID middleware, log filter, Celery header helpers: `backend.core.request_id`; Celery signals bound in `backend.worker.app`.

## 7. Forbidden

- Top-level HTTP `message` (including a dual-write shim)
- `about:blank`, relative URI, or kebab-case `type` for business errors
- First-party branching on `type` instead of `code`
- RFC `instance` or OTel fields used as request-id
- Job.`request_id` column
- Probe HTTP 200 `{ok:false}` rewritten as 4xx Problem Details
- Pydantic `input` / `loc` / framework `type` in the HTTP body
- JSON:API error envelope or Google HTTP `{error:{code,message,status,details}}` wrapper
- Renaming 422 `details` to `errors`, or replacing `field` with JSON Pointer
- `fastapi-problem` (default relative kebab `type` is out of contract)
