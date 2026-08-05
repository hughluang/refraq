# refraq Agent Guide

`refraq` is a standalone **Data Product Integration Platform** (a Data Business Platform).
New refraq implementation work belongs only in `backend/` and `frontend/`.

The Management Foundation login/session/permission slice (Management Console) is delivered. Next implementation phase is the **metadata foundation** (Source Systems, ingestion, MCP, User PAT, companion base) — see `docs/business-metadata.md`. Data Product catalog / Entity remain later. Process pointer: `.process/AGENTS.md`; source of truth stays under `docs/`.

## Repository Rules

- Do not move refraq feature work into any legacy repository.
- Use documents under `docs/` as the source of truth when code does not yet define behavior.
- Prefer small, verifiable changes.
- Never commit secrets or real credentials.

## Read First

For repository structure and long-lived development guidance, read:

1. `docs/development.md`
2. `docs/architecture.md`
3. `docs/modules.md`
4. domain or contract documents under `docs/` that match the task (metadata: `docs/business-metadata.md`, `docs/business-user-tokens.md`, matching `docs/api-contracts-*.md`)
5. root `CONTEXT.md` for domain language

## Notes

- This root file is an **Agent Protocol Entry** retained for tool discovery.
- Local **Process Documents** live under `.process/` (a **Process Workspace**) and are intentionally outside the committed baseline.
