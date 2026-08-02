# refraq Frontend

Management Console UI for refraq (Management Foundation first slice: login, session, RBAC).

## Stack

- Next.js App Router
- TypeScript
- Mantine v9
- Refine (`@refinedev/core` headless) + `@refinedev/nextjs-router`
- react-i18next

## Layout

- `src/app/` — routes only (`/login`, `/403`, `/console/**`)
- `src/features/` — resource UI slices (e.g. users, roles)
- `src/providers/` — Refine auth/data/access/i18n/notification bridges
- `src/components/` — shared layout and feedback UI
- `src/lib/` — API helper
- `src/locales/` — translation dictionaries

Browser calls are same-origin via Next rewrite: `/api/*` → backend (`REFRAQ_API_UPSTREAM`).

## Commands

```bash
npm install
npm run dev
npm run build
```

Default admin credentials come from backend `.env` (`INITIAL_ADMIN_ACCOUNT` / `INITIAL_ADMIN_PASSWORD`).
