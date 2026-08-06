# refraq

refraq is a **Data Business Platform**, and more specifically a **Data Product Integration Platform**. It integrates data from distributed enterprise source systems and turns it into unified, consumable, and governable data products for internal teams.

It is designed to bring scattered operational data into one product experience so teams can work with governed, business-ready data instead of stitching together disconnected sources by hand.

## Core Capabilities

### Data Product Capabilities

These define the business identity of refraq:

- Integrate data from distributed enterprise source systems into consistent internal data products
- Support shared business entities and consumer-facing delivery layers for different use cases
- Enable governed, reusable, and auditable data consumption across internal teams

### Metadata Foundation

The near-term substrate for product identity (documented; implementation next):

- Sources, Connections, and metadata ingestion
- Catalog structure, semantics, joins, and controlled read-only query
- User PAT and MCP access; companion secrets, queue/worker, and management audit

### Management Foundation

These are the enabling capabilities required to operate the platform in a controlled environment:

- Users (people), accounts, and login
- Sessions and authenticated state
- Configurable roles and a fixed permission catalog
- User PAT for non-browser API/MCP (person-owned); Client machine principals reserved for later

## Current Status

The Management Console login, session, permission, users, roles, and system-parameters slice is complete.
The next delivery phase is the **metadata foundation** (Sources, ingestion, MCP, User PAT, companion base). Start at [`docs/business-metadata.md`](docs/business-metadata.md), [`docs/business-user-tokens.md`](docs/business-user-tokens.md), and root [`CONTEXT.md`](CONTEXT.md). **Data Product** catalog / Entity capabilities remain later and are not delivered yet.

At this stage, the repository includes:

- a FastAPI backend for Foundation auth, users, roles, console navigation, and settings
- a Next.js Management Console for those Foundation flows
- project documentation for Foundation and the planned metadata foundation under `docs/`

## Repository Structure

- `backend/`: backend foundation for APIs, platform services, and future domain implementation
- `frontend/`: frontend foundation for the platform console and user-facing workflows
- `docs/`: committed source of truth for architecture, business rules, and API contracts (process checklists stay in `.process/`)
