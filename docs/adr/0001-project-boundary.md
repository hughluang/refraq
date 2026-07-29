# ADR 0001: Keep refraq Independent From The Old System

## Status

Accepted

## Date

2026-07-29

## Context

`refraq` was created as a new standalone project.
There is an existing older FastAPI base in a legacy repository, which may appear tempting as a shortcut for adding new refraq logic.

If new refraq code is spread across both places, the project will quickly lose clarity in:

- ownership
- deployment boundary
- future refactoring scope
- AI execution targets

Because the repository is expected to be used by follow-up AI agents, the implementation boundary must be explicit and stable.

## Decision

All new refraq business logic must be implemented only inside:

- `backend/`
- `frontend/`

No new refraq feature work should be added to:

- any legacy codebase path

## Alternatives Considered

### Alternative A: Continue extending the old FastAPI base

Pros:

- less short-term setup
- could reuse existing patterns immediately

Cons:

- keeps refraq coupled to unrelated legacy concerns
- makes future extraction harder
- makes AI execution ambiguous

### Alternative B: Hybrid approach during transition

Pros:

- can spread work gradually

Cons:

- creates unclear ownership
- increases documentation burden
- encourages accidental long-term dual-home logic

## Consequences

Positive:

- refraq has a clear implementation home
- future AI agents can operate with less ambiguity
- architecture, docs, and delivery scope stay aligned

Negative:

- some functionality may need to be reimplemented instead of reused directly from the old system
- initial setup work is slightly higher

## Follow-Up Implications

- documentation must keep pointing to `refraq/backend` and `refraq/frontend`
- tasks that attempt to add refraq code into the old base should be rejected or redirected
- if shared code is needed later, it should be extracted deliberately rather than by silent back-reference
