# refraq Documentation Conventions

## 1. Scope

This document defines how committed documentation is typed, named, structured, and written: document types and homes, file naming, section skeleton, the norms-not-chronicle rule, terminology and formatting, cross-references, and the use of tables, diagrams, and code blocks. It also records the format for Architecture Decision Records that agents author locally.

It does not review prose quality, prescribe product UI copy, or govern code comments.

Related boundaries:

- Development conventions and repository boundary: `docs/development.md`
- Domain language: `docs/glossary.md`
- Agent Protocol Entry: root `AGENTS.md`

## 2. Document Types And Homes

| Type | Filename pattern | H1 | Owns |
| --- | --- | --- | --- |
| Business rules | `docs/business-<subject>.md` | `# refraq Business Rules: <Subject>` | Domain rules and invariants |
| API contracts | `docs/api-contracts-<subject>.md` | `# refraq API Contracts: <Subject>` | Request and response shapes, errors |
| Cross-cutting conventions | `docs/conventions-<subject>.md` | `# refraq <Subject> Conventions` | A single cross-cutting rule set |
| Architecture | `docs/architecture.md` | `# refraq Architecture` | System boundary, topology, dependency direction |
| Backend layout | `docs/backend-layout.md` | `# refraq Backend Layout Contract` | Package tiers, published APIs, placement |
| Modules | `docs/modules.md` | `# refraq Module Responsibilities` | Module ownership and allowed coupling |
| Environment | `docs/env.md` | `# refraq Environment Conventions` | Env files, variable ownership, secrets handling |
| Development | `docs/development.md` | `# refraq Development Guide` | Repository boundary, working style, local commands |
| UI layout | `docs/ui-<subject>.md` | `# refraq UI: <Subject>` | Console layout rules that are not a business domain |
| Glossary | `docs/glossary.md` | `# Refraq Glossary` | Term, definition, and an `Avoid ...` line under `### Term` |
| Product README | `README.md` | `# refraq` | Repository identity and product value |
| Agent Protocol Entry | `AGENTS.md` | `# refraq Agent Guide` | Stable repository guidance for tooling discovery |

The committed baseline is `docs/*.md` at the `docs/` root, `README.md`, and `AGENTS.md`.

The following paths are local-only and are not part of the committed baseline:

- `.process/` — **Process Workspace** for **Process Document**s
- `CONTEXT.md` — local domain-language draft
- `docs/adr/` — Architecture Decision Records
- `docs/product-core/` — long-horizon local reference
- `scripts/` — local helper scripts

Naming a local-only path to define this boundary is allowed. Citing one as authority is not (§7).

## 3. File Naming

- Use kebab-case.
- Use the category prefix from §2 (`business-`, `api-contracts-`, `conventions-`, `ui-`). One-off names in §2 stay as listed.
- The subject fragment matches the domain term in `docs/glossary.md` (`jobs`, `scheduled-tasks`, `system-parameters`), not an internal package or service name.
- Do not invent a new category prefix when an existing type already fits.

## 4. Document Skeleton

- H2 sections are numbered and Title Case: `## 3. Information Architecture`.
- Sub-sections are H3 that inherit the parent number: `### 3.1 Top Bar`. Never promote a dotted number to H2 (`## 3.1`).
- Section 1 is `Scope` (business rules and conventions) or `Purpose` (API contracts and architecture-family documents): one paragraph on what the document defines and what it does not, then a `Related boundaries:` bullet list.
- `Non-Goals` is the last content section, named exactly that — no `for this slice`, `(this slice)`, or `Business` qualifier.
- `References` is last when present.

## 5. Norms, Not Chronicle

A committed document states the rule that holds now, not how the project arrived at it.

Forbidden:

1. Delivery-status phrasing (`delivered`, `shipped`, `next`, `deferred`).
2. `P0` / `P1` / `P2` priority tables.
3. `Current Gap` / `Confirmed Direction` narrative.
4. Per-slice checklists and delivery-order sections.

Express genuine phasing as a boundary ("X is out of scope for this document"), not a timeline. Sequencing and status belong to **Process Document**s in the **Process Workspace**.

Test: if a sentence would become false purely by time passing, with no rule change, it does not belong in a committed document.

## 6. Terminology And Formatting

- Bold `**Term**` for a term defined in `docs/glossary.md`, at first meaningful use per section, not every occurrence.
- Backticks for paths, identifiers, module ids, permissions (`settings:read`), endpoints, and env vars.
- Brand copy is `Refraq`; the technical identifier is `refraq`.
- Committed documents stay English. The check is `python3 scripts/check_staged_cjk.py` (staged) or `--all` (working tree).
- `Forbidden` / `Anti-Patterns` sections are numbered lists of prohibitions.

## 7. Cross-References

- Cite as `` `docs/x.md` ``. Add `§N` only when pointing at a specific section.
- Renumbering a section obliges updating inbound `§N` citations.
- Committed documents must not cite local-only artifacts as authority or defer their content to them. Naming such a path to define a boundary is allowed.
- Existing citations of this kind are deviations: do not add new ones, and remove them when the citing document is next edited.

## 8. Tables, Diagrams, And Code Blocks

- Use a table when three or more items share the same fields; otherwise use prose.
- Use mermaid for topology and flow.
- Fence code and examples with a language tag.

## 9. ADR Conventions

Architecture Decision Records live under `docs/adr/` and are local-only (§2). Agents that author one use this format:

- Unique four-digit number; filename `NNNN-kebab-title.md`.
- H1 `# NNNN. <Decision stated as an assertion>`.
- Sections `Status`, `Context`, `Decision`, `Consequences`.
- English only.

## 10. Non-Goals

- Prose quality review, editorial voice guides, and UI copy.
- Code comment conventions.
- Retrofits of documents that predate this convention; those documents are brought into line when next edited.
- Making local-only paths part of the committed baseline.

## 11. References

- `docs/development.md`
- `docs/glossary.md`
- `AGENTS.md`
