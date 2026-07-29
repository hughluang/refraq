# refraq Backend

This directory contains the backend foundation for refraq, the data product integration platform.

## Responsibility

The backend is the implementation home for API contracts, platform services, and domain logic. For the current slice it carries the **Management Foundation** (authentication, authorization, administrator management); in later phases it will carry the **Data Product Capabilities** behind refraq's data product workflows.

## Current Stage

The backend is still in scaffold form and currently includes:

- `main.py`: FastAPI entrypoint and `GET /healthz`
- `config.py`: runtime settings for the scaffold stage
- `admin/`: future platform and access-control domain logic
- `routers/`: future route definitions
- `repositories/`: future data access layer
- `schemas/`: future request and response models
- `tests/`: backend tests

It does not yet include production business APIs, persistence models, migrations, or completed authentication flows.
