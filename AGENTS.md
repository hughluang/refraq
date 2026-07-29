# refraq Agent Guide

`refraq` is a standalone **Data Product Integration Platform** (a Data Business Platform).
New refraq implementation work belongs only in `backend/` and `frontend/`.

The current delivery slice is the **Management Console** and its **Management Foundation** (administrator login, session, permission control). Login/session/permission are enabling capabilities, not the product identity.

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
4. domain or contract documents under `docs/` that match the task

## Notes

- This root file is an **Agent Protocol Entry** retained for tool discovery.
- Local **Process Documents** live under `.process/` (a **Process Workspace**) and are intentionally outside the committed baseline.
