"""Business Domain HTTP routers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord
from backend.core.pagination import PageParams, page_params
from backend.metadata.business_domains import service as domain_service
from backend.metadata.business_domains.store import BusinessDomainRecord
from backend.metadata.schemas.business_domains import (
    BusinessDomainCreateRequest,
    BusinessDomainListResponse,
    BusinessDomainOut,
    BusinessDomainPatchRequest,
    BusinessDomainResponse,
)

router = APIRouter(tags=["business-domains"])


def _domain_out(record: BusinessDomainRecord) -> BusinessDomainOut:
    return BusinessDomainOut(
        id=record.id,
        code=record.code,
        name=record.name,
        description=record.description,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get("/business-domains", response_model=BusinessDomainListResponse)
def list_business_domains(
    q: str | None = Query(default=None),
    page: PageParams = Depends(page_params(default_limit=100, max_limit=500)),
    _: UserRecord = Depends(require_permission("metadata:read")),
) -> BusinessDomainListResponse:
    items, total = domain_service.list_domains(
        q=q, limit=page.limit, offset=page.offset
    )
    return BusinessDomainListResponse(
        items=[_domain_out(i) for i in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "/business-domains",
    response_model=BusinessDomainResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_business_domain(
    body: BusinessDomainCreateRequest,
    user: UserRecord = Depends(require_permission("metadata:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> BusinessDomainResponse:
    record = domain_service.create_domain(
        code=body.code,
        name=body.name,
        description=body.description,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return BusinessDomainResponse(domain=_domain_out(record))


@router.patch("/business-domains/{domain_id}", response_model=BusinessDomainResponse)
def patch_business_domain(
    domain_id: str,
    body: BusinessDomainPatchRequest,
    user: UserRecord = Depends(require_permission("metadata:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> BusinessDomainResponse:
    record = domain_service.patch_domain(
        domain_id=domain_id,
        name=body.name,
        description=body.description,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return BusinessDomainResponse(domain=_domain_out(record))


@router.delete(
    "/business-domains/{domain_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_business_domain(
    domain_id: str,
    user: UserRecord = Depends(require_permission("metadata:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> Response:
    domain_service.delete_domain(
        domain_id=domain_id,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
