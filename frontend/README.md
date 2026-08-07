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

Permanent read-only vs editable fields must look different. Prefer display-vs-input separation (same idea as react-admin Field / Odoo readonly plain text / Ant Design ProForm read mode)—do not disguise permanent read-only values as `TextInput readOnly`.

| Scenario | Control | Meaning |
| --- | --- | --- |
| Permanent read-only on this page | `DisplayField` (`src/components/display/DisplayField.tsx`) | Label + plain text (optional description); not a form control—no border / focus ring |
| Editable | `TextInput` / `Select` / `PasswordInput` / etc. | Normal interactive inputs |
| Temporarily locked (missing permission, edit-mode locked key) | Input + `disabled` | Still a form control; grayed to mean “would be editable, not now” |

Do not use `TextInput readOnly` for “looks like a form row” permanent display. Temporary locks (e.g. `RoleForm` key on edit) stay on `disabled`.

## Commands

```bash
npm install
npm run dev
npm run build
```

Default admin credentials come from backend `.env` (`INITIAL_ADMIN_ACCOUNT` / `INITIAL_ADMIN_PASSWORD`).
