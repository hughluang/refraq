"""Business Domain domain service (HTTP + MCP shared)."""

from __future__ import annotations

from backend.core.time import utc_now
from datetime import datetime

from backend.admin.audit import persist_audit_event
from backend.metadata.business_domains.store import (
    BusinessDomainRecord,
    get_business_domain_store,
    new_business_domain_id,
)
from backend.metadata.catalog.store import get_catalog_store
from backend.metadata.errors import (
    BusinessDomainInUse,
    BusinessDomainNotFound,
    BusinessDomainUnknown,
)

__all__ = [
    "create_domain",
    "delete_domain",
    "list_domains",
    "patch_domain",
    "require_domain",
    "require_domain_by_code",
]


def require_domain(domain_id: str) -> BusinessDomainRecord:
    record = get_business_domain_store().get(domain_id)
    if record is None:
        raise BusinessDomainNotFound()
    return record


def require_domain_by_code(code: str) -> BusinessDomainRecord:
    cleaned = (code or "").strip()
    if not cleaned:
        raise BusinessDomainUnknown()
    record = get_business_domain_store().get_by_code(cleaned)
    if record is None:
        raise BusinessDomainUnknown()
    return record


def list_domains(
    *, q: str | None = None, limit: int = 100, offset: int = 0
) -> tuple[list[BusinessDomainRecord], int]:
    return get_business_domain_store().list_domains(q=q, limit=limit, offset=offset)


def create_domain(
    *,
    code: str,
    name: str,
    description: str | None,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> BusinessDomainRecord:
    now = utc_now()
    record = BusinessDomainRecord(
        id=new_business_domain_id(),
        code=code.strip(),
        name=name.strip(),
        description=description.strip() if isinstance(description, str) else description,
        created_at=now,
        updated_at=now,
    )
    created = get_business_domain_store().create(record)
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="business_domain",
        resource_id=created.id,
        action="business_domain.create",
        result="success",
        detail={"code": created.code},
    )
    return created


def patch_domain(
    *,
    domain_id: str,
    name: str | None,
    description: str | None,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> BusinessDomainRecord:
    existing = require_domain(domain_id)
    changed: dict[str, object] = {}
    new_name = existing.name
    new_description = existing.description
    if name is not None:
        new_name = name.strip()
        changed["name"] = new_name
    if description is not None:
        new_description = description.strip() if description else None
        changed["description"] = new_description
    if not changed:
        return existing
    updated = get_business_domain_store().save(
        BusinessDomainRecord(
            id=existing.id,
            code=existing.code,
            name=new_name,
            description=new_description,
            created_at=existing.created_at,
            updated_at=utc_now(),
        )
    )
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="business_domain",
        resource_id=domain_id,
        action="business_domain.patch",
        result="success",
        detail={"changed": list(changed.keys())},
    )
    return updated


def delete_domain(
    *,
    domain_id: str,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> None:
    existing = require_domain(domain_id)
    refs = get_catalog_store().count_objects_for_domain(domain_id)
    if refs > 0:
        raise BusinessDomainInUse()
    deleted = get_business_domain_store().delete(domain_id)
    if not deleted:
        raise BusinessDomainNotFound()
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="business_domain",
        resource_id=domain_id,
        action="business_domain.delete",
        result="success",
        detail={"code": existing.code},
    )
