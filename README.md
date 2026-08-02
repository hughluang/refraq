# refraq

refraq is a **Data Business Platform**, and more specifically a **Data Product Integration Platform**. It integrates data from distributed enterprise source systems and turns it into unified, consumable, and governable data products for internal teams.

It is designed to bring scattered operational data into one product experience so teams can work with governed, business-ready data instead of stitching together disconnected sources by hand.

## Core Capabilities

### Data Product Capabilities

These define the business identity of refraq:

- Integrate data from distributed enterprise source systems into consistent internal data products
- Support shared business entities and consumer-facing delivery layers for different use cases
- Enable governed, reusable, and auditable data consumption across internal teams

### Management Foundation

These are the enabling capabilities required to operate the platform in a controlled environment:

- Users (people), accounts, and login
- Sessions and authenticated state
- Configurable roles and a fixed permission catalog
- Reserved Client principals for later machine access

## Current Status

The repository is currently in the foundation stage.
The product identity is defined, while the implementation is still a scaffold for the first delivery slices.

The current delivery slice focuses on the **Management Console** and the **Management Foundation** (User login, session, Role management, and permission control). Business **Data Product Capabilities** are planned for later phases.

At this stage, the repository includes:

- a FastAPI backend foundation in `backend/`
- a Next.js frontend foundation in `frontend/`
- initial project documentation and architectural boundaries

It does not yet include full business APIs, production data workflows, or completed platform UI flows.

## Repository Structure

- `backend/`: backend foundation for APIs, platform services, and future domain implementation
- `frontend/`: frontend foundation for the platform console and user-facing workflows
- `docs/`: project documentation that captures architecture, modules, and execution planning
