"""Entity access management HTTP."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from backend.admin.deps import get_actor_token_id, require_permission, resolve_user_permissions
from backend.admin.role_store import get_role_store
from backend.admin.user_store import UserRecord
from backend.core.pagination import PageParams, page_params
from backend.entity.data.capabilities import PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MAX
from backend.entity.schemas.access import (
    GrantCreate,
    GrantPatch,
    LadderPut,
    PreviewIn,
    ProfileCopy,
    ProfileCreate,
    ProfilePatch,
    RestrictionCreate,
    RestrictionPatch,
)
from backend.entity.access import service

router = APIRouter(tags=["entity-access"])


def _caller_permissions(user: UserRecord) -> set[str]:
    return set(resolve_user_permissions(user, get_role_store()))


@router.get("/entities/{entity_id}/access")
def http_access_summary(
    entity_id: str,
    _: UserRecord = Depends(require_permission("entity:access_manage")),
) -> dict:
    return service.summary(entity_id)


@router.get("/entities/{entity_id}/access/ladders")
def http_list_ladders(
    entity_id: str,
    _: UserRecord = Depends(require_permission("entity:access_manage")),
) -> dict:
    return service.list_ladders(entity_id)


@router.put("/entities/{entity_id}/access/ladders/{attribute_id}")
def http_put_ladder(
    entity_id: str,
    attribute_id: str,
    body: LadderPut,
    user: UserRecord = Depends(require_permission("entity:access_manage")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> dict:
    return service.put_ladder(
        entity_id,
        attribute_id,
        [item.model_dump() for item in body.levels],
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )


@router.get("/entities/{entity_id}/access/profiles")
def http_list_profiles(
    entity_id: str,
    _: UserRecord = Depends(require_permission("entity:access_manage")),
) -> dict:
    return service.list_profiles(entity_id)


@router.post("/entities/{entity_id}/access/profiles", status_code=201)
def http_create_profile(
    entity_id: str,
    body: ProfileCreate,
    user: UserRecord = Depends(require_permission("entity:access_manage")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> dict:
    return service.create_profile(
        entity_id,
        key=body.key,
        name=body.name,
        description=body.description,
        columns=[item.model_dump() for item in body.columns],
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )


@router.post("/entities/{entity_id}/access/profiles/copy", status_code=201)
def http_copy_profile(
    entity_id: str,
    body: ProfileCopy,
    user: UserRecord = Depends(require_permission("entity:access_manage")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> dict:
    return service.copy_profile(
        entity_id,
        source_entity_id=body.source_entity_id,
        source_profile_id=body.source_profile_id,
        key=body.key,
        name=body.name,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )


@router.get("/entities/{entity_id}/access/profiles/{profile_id}")
def http_get_profile(
    entity_id: str,
    profile_id: str,
    _: UserRecord = Depends(require_permission("entity:access_manage")),
) -> dict:
    return service.get_profile(entity_id, profile_id)


@router.patch("/entities/{entity_id}/access/profiles/{profile_id}")
def http_update_profile(
    entity_id: str,
    profile_id: str,
    body: ProfilePatch,
    user: UserRecord = Depends(require_permission("entity:access_manage")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> dict:
    return service.update_profile(
        entity_id,
        profile_id,
        fields=set(body.model_fields_set),
        name=body.name,
        description=body.description,
        columns=(
            [item.model_dump() for item in body.columns]
            if body.columns is not None
            else None
        ),
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )


@router.delete("/entities/{entity_id}/access/profiles/{profile_id}", status_code=204)
def http_delete_profile(
    entity_id: str,
    profile_id: str,
    user: UserRecord = Depends(require_permission("entity:access_manage")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> Response:
    service.delete_profile(
        entity_id,
        profile_id,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return Response(status_code=204)


@router.get("/entities/{entity_id}/access/grants")
def http_list_grants(
    entity_id: str,
    page: PageParams = Depends(
        page_params(default_limit=PAGE_LIMIT_DEFAULT, max_limit=PAGE_LIMIT_MAX)
    ),
    _: UserRecord = Depends(require_permission("entity:access_manage")),
) -> dict:
    return service.list_grants(entity_id, limit=page.limit, offset=page.offset)


@router.post("/entities/{entity_id}/access/grants", status_code=201)
def http_create_grant(
    entity_id: str,
    body: GrantCreate,
    user: UserRecord = Depends(require_permission("entity:access_manage")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> dict:
    return service.create_grant(
        entity_id,
        subject=body.subject.model_dump(),
        profile_id=body.profile_id,
        row_rule=body.row_rule,
        actions=body.actions,
        status=body.status,
        valid_until=body.valid_until,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )


@router.get("/entities/{entity_id}/access/grants/{grant_id}")
def http_get_grant(
    entity_id: str,
    grant_id: str,
    _: UserRecord = Depends(require_permission("entity:access_manage")),
) -> dict:
    return service.get_grant(entity_id, grant_id)


@router.patch("/entities/{entity_id}/access/grants/{grant_id}")
def http_update_grant(
    entity_id: str,
    grant_id: str,
    body: GrantPatch,
    user: UserRecord = Depends(require_permission("entity:access_manage")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> dict:
    return service.update_grant(
        entity_id,
        grant_id,
        fields=set(body.model_fields_set),
        profile_id=body.profile_id,
        row_rule=body.row_rule,
        actions=body.actions,
        status=body.status,
        valid_until=body.valid_until,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )


@router.delete("/entities/{entity_id}/access/grants/{grant_id}", status_code=204)
def http_delete_grant(
    entity_id: str,
    grant_id: str,
    user: UserRecord = Depends(require_permission("entity:access_manage")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> Response:
    service.delete_grant(
        entity_id,
        grant_id,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return Response(status_code=204)


@router.get("/entities/{entity_id}/access/restrictions")
def http_list_restrictions(
    entity_id: str,
    _: UserRecord = Depends(require_permission("entity:access_manage")),
) -> dict:
    return service.list_restrictions(entity_id)


@router.post("/entities/{entity_id}/access/restrictions", status_code=201)
def http_create_restriction(
    entity_id: str,
    body: RestrictionCreate,
    user: UserRecord = Depends(require_permission("entity:access_manage")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> dict:
    return service.create_restriction(
        entity_id,
        applies_to=body.applies_to.model_dump(),
        row_rule=body.row_rule,
        deny_columns=body.deny_columns,
        ceilings=[item.model_dump() for item in body.ceilings],
        actions=body.actions,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )


@router.get("/entities/{entity_id}/access/restrictions/{restriction_id}")
def http_get_restriction(
    entity_id: str,
    restriction_id: str,
    _: UserRecord = Depends(require_permission("entity:access_manage")),
) -> dict:
    return service.get_restriction(entity_id, restriction_id)


@router.patch("/entities/{entity_id}/access/restrictions/{restriction_id}")
def http_update_restriction(
    entity_id: str,
    restriction_id: str,
    body: RestrictionPatch,
    user: UserRecord = Depends(require_permission("entity:access_manage")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> dict:
    return service.update_restriction(
        entity_id,
        restriction_id,
        fields=set(body.model_fields_set),
        applies_to=body.applies_to.model_dump() if body.applies_to is not None else None,
        row_rule=body.row_rule,
        deny_columns=body.deny_columns,
        ceilings=(
            [item.model_dump() for item in body.ceilings]
            if body.ceilings is not None
            else None
        ),
        actions=body.actions,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )


@router.delete(
    "/entities/{entity_id}/access/restrictions/{restriction_id}", status_code=204
)
def http_delete_restriction(
    entity_id: str,
    restriction_id: str,
    user: UserRecord = Depends(require_permission("entity:access_manage")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> Response:
    service.delete_restriction(
        entity_id,
        restriction_id,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return Response(status_code=204)


@router.post("/entities/{entity_id}/access/preview")
def http_preview(
    entity_id: str,
    body: PreviewIn,
    user: UserRecord = Depends(require_permission("entity:access_manage")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> dict:
    return service.preview(
        entity_id,
        subject=body.subject.model_dump(),
        narrow=body.narrow.model_dump() if body.narrow is not None else None,
        include_rows=body.include_rows,
        filters=body.filters,
        limit=body.limit,
        offset=body.offset,
        caller_user_id=user.id,
        caller_permissions=_caller_permissions(user),
        actor_token_id=actor_token_id,
    )
