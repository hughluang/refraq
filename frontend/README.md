# refraq Frontend

This directory contains the frontend foundation for refraq, the data product integration platform.

## Responsibility

The frontend is the implementation home for the **Management Console** (the current delivery slice's administrator-facing UI surface), user workflows, route protection, and future data-product-facing UI experiences.

The Management Console is the UI surface for the current slice, not the product identity of refraq.

## Key Stack

- Next.js App Router
- TypeScript

## Current Stage

The frontend is still in scaffold form and currently includes:

- `src/app/`: route entrypoints and layouts
- `src/providers/`: future auth, data, access-control, and i18n providers
- `src/components/`: shared UI components
- `src/locales/`: locale resources

It does not yet include live backend integration, completed business pages, or generated API types.
