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
- `src/components/icons.tsx` — console icon set (Tabler, default size and stroke)
- `src/components/display/` — collection frame (`ListTable`, `ListToolbar`, `RowActions`)
- `src/components/layout/CommandPalette.tsx` — command palette
- `src/theme/` — product theme (semantic tones, motion, radius, component defaults). Site Branding still supplies only the brand palette (`src/features/branding/theme.ts`)
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

API timestamps are decoded to `Instant` in `apiClient`. Display them only via `<Instant>` or `useFormatInstant`. Use `epochMs()` / `toJSON()` for non-display logic. `date`, `time`, durations, and cron wall-clock fields stay strings and are not timezone-shifted (`docs/conventions-time.md`).

## Form frame

`useConsoleForm` (`src/components/form/useConsoleForm.ts`) wraps `@mantine/form`. It keeps the loaded snapshot, exposes `dirty` (registered with the leave guard), and runs submit with `submitting` set so a second submit is ignored. A successful submit replaces the snapshot before the caller navigates. A thrown submit, or one that called `applyApiError`, releases leave-guard suppression and leaves the snapshot in place.

A 422 `details[]` entry maps `field` onto a form path by identity, then an optional alias. A `body.`, `query.`, `path.`, `header.`, or `cookie.` prefix is ignored the same way the API builds the path from a validation location. Mapped entries become field errors and focus moves to the first invalid field. Client rules run on blur for touched fields, on submit for every field, and again on change once an error is showing.

`saveFailureFrom` plus `FormErrorSummary` are the form-level error. The summary's main line is `problemMessage` (localized Problem Code, otherwise `problems.unknown`, never the server `detail`). Server `detail`, request id, and unmapped rows sit in a disclosure with click-to-copy. A 422 whose every row mapped onto a field does not show the summary.

`FormSection` is a titled group with an optional description and a one- or two-column grid (two columns once the section is at least 36rem wide). Field components take `helper` for a persistent line under the control. `FormDialog` is a real form: Cancel, then the primary action, Enter submits, the first field is focused, and closing a dirty dialog (Escape, close, Cancel) asks before discard. The overlay does not dismiss a dirty dialog.

## Composition rules

`src/compositionRules.test.ts` runs under `npm test` with the other console unit tests. It fails when console code bypasses the shared frames:

- `@mantine/notifications` outside the feedback layer (`src/providers/notification-provider.ts`, `src/app/providers.tsx`, `src/components/feedback/`)
- `@tabler/icons-react` outside `src/components/icons.tsx`
- `@mantine/spotlight` or `@mantine/nprogress` outside the shell (`src/components/layout/`, `src/app/providers.tsx`, `src/app/console/layout.tsx`)
- `useRouter` or `usePathname` from `next/navigation` inside `src/features/` (use `useConsoleNavigation`)
- `useSearchParams` inside `src/features/` unless the test lists that file with a reason (list and tab hooks cover the reads; the list is empty)
- `window.confirm` anywhere under `src/`
- a hex, `rgb()`, `rgba()`, `hsl()`, or `hsla()` literal in `src/features/` or any CSS file, except brand color math and its tests
- a raw Mantine `Table` root in `src/features/` except the static display tables named in the test

## End-to-end tests

Playwright drives a production Console against the API started as the ASGI app (`uvicorn backend.main:app`) with the memory Store Backend. Celery worker and Beat are not started. `frontend/playwright.config.mts` starts both processes. Ports default to API `8010` and Console `4173` (`E2E_API_PORT`, `E2E_CONSOLE_PORT`). The API process uses `backend/.venv/bin/python` when that interpreter exists, otherwise `E2E_PYTHON` or `python3`.

The suite signs in as the initial administrator (`INITIAL_ADMIN_ACCOUNT` / `INITIAL_ADMIN_PASSWORD`, default `root` / `change-me`) and reuses that session. Each test seeds its own records through `/api` with the session cookie. `npm run e2e` builds the Console when the standalone server is missing or was built for a different `REFRAQ_API_UPSTREAM`, then runs Chromium. The Console listens through `.next/standalone/server.js` because `output: "standalone"` does not support `next start`. `npm run e2e:ui` opens the Playwright UI.

## Commands

```bash
npm install
npm run dev
npm test
npm run typecheck
npm run build
npm run e2e
```

`npm run dev` binds `127.0.0.1` so the sandbox Console is not reachable on the office network. A published site compose uses a separate host port (`docs/development.md`).

Default admin credentials come from backend `.env` (`INITIAL_ADMIN_ACCOUNT` / `INITIAL_ADMIN_PASSWORD`).
