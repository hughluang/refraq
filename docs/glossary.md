# refraq Glossary

## Product Identity

### refraq

A standalone data business platform that unifies data-facing workflows and management capabilities in one product.
Avoid describing it as a scaffold only or an auth demo.

### Data Business Platform

An internal platform that combines data workflows, operational interfaces, and management capabilities into a single business system.
Avoid describing it as an auth shell or a generic admin starter.

### Data Product Integration Platform

An internal platform that integrates data from distributed business systems and turns it into unified, consumable data products.
This is the preferred, more specific product identity of refraq.
Avoid describing it as a generic admin platform or an auth-first product.

### Data Product Capability

A business-defining capability that turns distributed source-system data into unified, consumable, and governable data outputs.
Avoid treating it as a generic admin feature or a page-level function.

### Management Foundation

The generic administrative capabilities required by almost any internal system, such as users, organizations, roles, permissions, and login.
Avoid treating it as the core product identity or the differentiating business capability.

### Management Console

The administrator-facing UI surface of refraq for the current delivery slice, not the product identity.
Avoid treating it as the product definition, a standalone admin project, or a synonym for refraq itself.

## People And Access

### Administrator

An internal user allowed to access and operate the refraq Management Console.
This document does not use "customer user" or "end user" for the first slice.

### Account

The login identifier used by an Administrator.
Initially modeled as a single username-like field.
Avoid calling it a user id or employee id.

### Session

Server-managed authenticated state created after successful login and carried through a cookie.
Avoid calling it a token or a permanent login.

### Current User

The administrator resolved from the active session for the current request.

### Role

A named access level assigned to an Administrator.
The first version uses `super_admin`, `operator`, and `viewer`.
Avoid calling it a job title or department.

### Permission

A concrete allowed action expressed as `resource:action`, such as `dashboard:read`.
Avoid reducing it to a menu or a page label.

## Auth Concepts

### Authentication

The process of proving administrator identity, primarily through login and session validation.

### Authorization

The process of deciding whether an authenticated administrator can access a route or perform an action.

### Protected Route

A frontend route that requires a valid authenticated session.

### Forbidden

The state where a user is authenticated but does not hold the required permission.
Mapped to HTTP `403`.

### Unauthenticated

The state where no valid session is present.
Mapped to HTTP `401`.

### API Contract

The agreed request and response shape between frontend and backend.

## Repository And Process

### Project Boundary

The rule that new refraq code is implemented inside refraq as the standalone implementation home of the product.
Concretely, new logic belongs only in `backend/` and `frontend/`, not in the old system.
Avoid a hybrid home or temporary dual-write.

### Process Document

A transient repository document that captures execution sequencing or working guidance for a specific implementation phase.
Avoid treating it as a canonical spec, a durable product document, or a governance rule.

### Process Workspace

A repository-local location dedicated to Process Documents and excluded from the versioned product baseline.
In this repository it is `.process/`.
Avoid treating it as the docs directory or the committed documentation set.

### Agent Protocol Entry

A repository-root file with a conventional name that tooling may discover automatically to load stable repository guidance.
In this repository the root `AGENTS.md` is the Agent Protocol Entry.
Avoid treating it as a transient process note or a business specification.
