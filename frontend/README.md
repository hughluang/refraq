# refraq Frontend

Management Console UI for refraq. Management Foundation (login, session, RBAC) is delivered; next phase is the metadata foundation (`docs/business-metadata.md`).

## Stack

- Next.js App Router
- TypeScript
- Mantine v9
- Refine (`@refinedev/core` headless) + `@refinedev/nextjs-router`
- next-i18next (App Router, cookie locale) + react-i18next

## Layout

- `src/app/` — routes only (`/login`, `/403`, `/console/**`)
- `src/features/` — resource UI slices (e.g. users, roles)
- `src/providers/` — Refine auth/data/access/i18n/notification bridges
- `src/components/` — shared layout and feedback UI
- `src/lib/` — API helper
- `src/locales/` — translation dictionaries

Browser calls are same-origin via Next rewrite: `/api/*` → backend (`REFRAQ_API_UPSTREAM`).

## Form display

A form field has two presentations, chosen inside the field component by `editable` (`src/components/form/`). A value the actor cannot change is display mode, not a `disabled` or `readOnly` input. There is no third presentation (`locked`, `disabled`, `readOnly`).

| `editable` | Presentation |
| --- | --- |
| `true` | The matching editor (text, number, select, tags, switch, segmented control, cron builder). Required markers and errors appear only here. |
| `false` | Display for that value's shape: plain text (empty is an em dash), the option label, yes/no, or the current segmented label. |

`editable={false}` covers show, missing write permission, a key that is immutable after create, and a field that is temporarily not authorable inside an otherwise editable form. Save and connectivity tests keep the fields editable; the busy state stays on the button.

`DisplayField` (`src/components/display/DisplayField.tsx`) is for facts that are not form fields (timestamps, job ids). Record-form show uses the same field components as create and edit (`docs/ui-console-record-form.md`). The branch stays inside the field component.

## Commands

```bash
npm install
npm run dev
npm run build
```

`npm run dev` binds `127.0.0.1` so the sandbox Console is not reachable on the office network. A published site compose uses a separate host port (`docs/development.md`).

Default admin credentials come from backend `.env` (`INITIAL_ADMIN_ACCOUNT` / `INITIAL_ADMIN_PASSWORD`).
