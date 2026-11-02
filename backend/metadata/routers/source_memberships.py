"""Source Membership HTTP. Resolution stays in the Source Access module."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response, status

from backend.admin.audit import persist_audit_event
from backend.admin.deps import (
    get_actor_token_id,
    get_current_user,
    require_permission,
    resolve_user_permissions,
)
from backend.admin.errors import AuthForbidden
from backend.admin.permissions import permissions_include
from backend.admin.role_store import get_role_store
from backend.admin.user_store import UserRecord
from backend.core.errors import AppError
from backend.metadata.errors import SourceNotFound
from backend.metadata.schemas.source_memberships import (
    MembershipCreateIn,
    MembershipLevelIn,
    MembershipListResponse,
    MembershipOut,
    MembershipResponse,
    MembershipSubjectOut,
)
from backend.metadata.source_access import (
    EVERY_SOURCE_TARGET,
    SourceMembership,
    change_level,
    create_membership,
    delete_membership,
    effective_level,
    explain_user,
    list_memberships,
)
from backend.metadata.sources.store import get_source_store

router = APIRouter(tags=["source-memberships"])

_MANAGE = require_permission("sources:access_manage")


class SourceMembershipNotFound(AppError):
    code = "SOURCE_MEMBERSHIP_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Source membership not found"


def explained_sources_for_user(user_id: str) -> list[dict[str, Any]]:
    """Effective Source access with key and name from the Source store.

    ``explain_user`` names the Source id, the level, and contributions. It does
    not carry the Source key or name.
    """
    explained = explain_user(user_id)
    if not explained:
        return []
    sources, _total = get_source_store().list_sources(limit=None)
    by_id = {source.id: source for source in sources}
    items: list[dict[str, Any]] = []
    for row in explained:
        source = by_id.get(row.source_id)
        if source is None:
            continue
        items.append(
            {
                "source_id": source.id,
                "key": source.key,
                "name": source.name,
                "level": row.level,
                "contributions": [
                    {"kind": item.kind, "subject_name": item.subject_name}
                    for item in row.contributions
                ],
            }
        )
    return items


def _holds_access_manage(user: UserRecord) -> bool:
    permissions = resolve_user_permissions(user, get_role_store())
    return permissions_include(permissions, "sources:access_manage")


def _require_source(source_id: str) -> None:
    if get_source_store().get_source(source_id) is None:
        raise SourceNotFound()


def _authorize_source_list(user: UserRecord, source_id: str) -> None:
    _require_source(source_id)
    if _holds_access_manage(user):
        return
    level = effective_level(user.id, source_id)
    if level == "maintainer":
        return
    if level is None:
        raise SourceNotFound()
    raise AuthForbidden()


def _membership_out(row: SourceMembership) -> MembershipOut:
    return MembershipOut(
        id=row.id,
        subject=MembershipSubjectOut(
            type=row.subject_type,
            id=row.subject_id,
            display_name=row.subject_name,
            missing=row.subject_name is None,
        ),
        target=row.target,
        level=row.level,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _list_response(target: str) -> MembershipListResponse:
    return MembershipListResponse(
        items=[_membership_out(row) for row in list_memberships(target=target)]
    )


def _on_target(target: str, membership_id: str) -> SourceMembership:
    for row in list_memberships(target=target):
        if row.id == membership_id:
            return row
    raise SourceMembershipNotFound()


def _audit(
    *,
    user: UserRecord,
    actor_token_id: str | None,
    action: str,
    row: SourceMembership,
    old_level: str | None,
    new_level: str | None,
) -> None:
    persist_audit_event(
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
        resource_type="source_membership",
        resource_id=row.id,
        action=action,
        result="success",
        detail={
            "subject": {"type": row.subject_type, "id": row.subject_id},
            "target": row.target,
            "old_level": old_level,
            "new_level": new_level,
        },
    )


def _create(
    target: str,
    body: MembershipCreateIn,
    request: Request,
    user: UserRecord,
) -> MembershipResponse:
    created = create_membership(
        subject_type=body.subject.type,
        subject_id=body.subject.id,
        target=target,
        level=body.level,
    )
    _audit(
        user=user,
        actor_token_id=get_actor_token_id(request),
        action="source_membership.create",
        row=created,
        old_level=None,
        new_level=created.level,
    )
    return MembershipResponse(membership=_membership_out(created))


def _change(
    target: str,
    membership_id: str,
    body: MembershipLevelIn,
    request: Request,
    user: UserRecord,
) -> MembershipResponse:
    current = _on_target(target, membership_id)
    updated = change_level(membership_id, body.level)
    if updated is None:
        raise SourceMembershipNotFound()
    _audit(
        user=user,
        actor_token_id=get_actor_token_id(request),
        action="source_membership.update",
        row=updated,
        old_level=current.level,
        new_level=updated.level,
    )
    return MembershipResponse(membership=_membership_out(updated))


def _delete(
    target: str,
    membership_id: str,
    request: Request,
    user: UserRecord,
) -> Response:
    current = _on_target(target, membership_id)
    if not delete_membership(membership_id):
        raise SourceMembershipNotFound()
    _audit(
        user=user,
        actor_token_id=get_actor_token_id(request),
        action="source_membership.delete",
        row=current,
        old_level=current.level,
        new_level=None,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sources/{source_id}/memberships", response_model=MembershipListResponse)
def list_source_memberships(
    source_id: str,
    user: UserRecord = Depends(get_current_user),
) -> MembershipListResponse:
    _authorize_source_list(user, source_id)
    return _list_response(source_id)


@router.post(
    "/sources/{source_id}/memberships",
    status_code=status.HTTP_201_CREATED,
    response_model=MembershipResponse,
)
def create_source_membership(
    source_id: str,
    body: MembershipCreateIn,
    request: Request,
    user: UserRecord = Depends(_MANAGE),
) -> MembershipResponse:
    _require_source(source_id)
    return _create(source_id, body, request, user)


@router.patch(
    "/sources/{source_id}/memberships/{membership_id}",
    response_model=MembershipResponse,
)
def change_source_membership(
    source_id: str,
    membership_id: str,
    body: MembershipLevelIn,
    request: Request,
    user: UserRecord = Depends(_MANAGE),
) -> MembershipResponse:
    _require_source(source_id)
    return _change(source_id, membership_id, body, request, user)


@router.delete(
    "/sources/{source_id}/memberships/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_source_membership(
    source_id: str,
    membership_id: str,
    request: Request,
    user: UserRecord = Depends(_MANAGE),
) -> Response:
    _require_source(source_id)
    return _delete(source_id, membership_id, request, user)


@router.get("/source-memberships", response_model=MembershipListResponse)
def list_every_source_memberships(
    _user: UserRecord = Depends(_MANAGE),
) -> MembershipListResponse:
    return _list_response(EVERY_SOURCE_TARGET)


@router.post(
    "/source-memberships",
    status_code=status.HTTP_201_CREATED,
    response_model=MembershipResponse,
)
def create_every_source_membership(
    body: MembershipCreateIn,
    request: Request,
    user: UserRecord = Depends(_MANAGE),
) -> MembershipResponse:
    return _create(EVERY_SOURCE_TARGET, body, request, user)


@router.patch(
    "/source-memberships/{membership_id}",
    response_model=MembershipResponse,
)
def change_every_source_membership(
    membership_id: str,
    body: MembershipLevelIn,
    request: Request,
    user: UserRecord = Depends(_MANAGE),
) -> MembershipResponse:
    return _change(EVERY_SOURCE_TARGET, membership_id, body, request, user)


@router.delete(
    "/source-memberships/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_every_source_membership(
    membership_id: str,
    request: Request,
    user: UserRecord = Depends(_MANAGE),
) -> Response:
    return _delete(EVERY_SOURCE_TARGET, membership_id, request, user)
