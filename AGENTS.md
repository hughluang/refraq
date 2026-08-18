# refraq Agent Guide

`refraq` is a standalone **Data Product Integration Platform** (a Data Business Platform).
New refraq implementation work belongs only in `backend/` and `frontend/`.

The Management Foundation login/session/permission slice (Management Console) is delivered. Next implementation phase is the **metadata foundation** (Sources, catalog, MCP, User PAT, companion base) — see `docs/business-metadata.md`. **Job** and **Scheduled Task** are platform mechanisms (`docs/business-jobs.md`, `docs/business-scheduled-tasks.md`), not Metadata domain members. Data Product catalog / Entity remain later. Process pointer: `.process/AGENTS.md`; source of truth stays under `docs/`.

## Repository Rules

- Do not move refraq feature work into any legacy repository.
- Use documents under `docs/` as the source of truth when code does not yet define behavior.
- Prefer small, verifiable changes.
- Never commit secrets or real credentials.
- Committed code, comments, and docs stay English. Chinese UI copy belongs only in `frontend/src/locales/zh-CN/`; native locale labels may also live in `frontend/src/providers/locale-catalog.ts`. Do not put CJK in `docs/`, `CONTEXT.md`, ADRs, identifiers, or comments. Check: `python3 scripts/check_staged_cjk.py` (staged) or `--all` (working tree).

## Read First

For repository structure and long-lived development guidance, read:

1. `docs/development.md`
2. `docs/conventions-docs.md` (document types, skeleton, writing rules)
3. `docs/backend-layout.md` (backend package tiers, published APIs, placement)
4. `docs/architecture.md`
5. `docs/modules.md`
6. domain or contract documents under `docs/` that match the task (metadata: `docs/business-metadata.md`, `docs/business-user-tokens.md`; jobs/schedules: `docs/business-jobs.md`, `docs/business-scheduled-tasks.md`; matching `docs/api-contracts-*.md`)
7. root `CONTEXT.md` for domain language

## Notes

- This root file is an **Agent Protocol Entry** retained for tool discovery.
- Local **Process Documents** live under `.process/` (a **Process Workspace**) and are intentionally outside the committed baseline.
