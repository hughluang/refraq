"""Access-policy use cases. Policy writes enqueue profile-view regeneration."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from backend.admin.audit import persist_audit_event
from backend.admin.errors import AuthForbidden
from backend.admin.role_store import get_role_store
from backend.admin.subjects import (
    existing_group_ids,
    existing_user_ids,
    group_labels,
    subject_attributes,
    user_group_ids,
    user_labels,
)
from backend.admin.user_store import get_user_store
from backend.core.request_id import get_request_id
from backend.core.time import format_instant, utc_now
from backend.entity.access.compiler import (
    CompiledPolicy,
    Outcome,
    Policy,
    compile_policy,
    render_shape,
    subject_outcome,
)
from backend.entity.access.dsl import RuleProblem, validate_rule
from backend.entity.access.errors import (
    EntityAccessCombinationLimit,
    EntityAccessGrantNotFound,
    EntityAccessInUse,
    EntityAccessInvalid,
    EntityAccessKeyDup,
    EntityAccessPending,
    EntityAccessProfileNotFound,
    EntityAccessRestrictionNotFound,
)
from backend.entity.access.facts import (
    ACTIONS,
    Narrow,
    Person,
    SubjectAttrFact,
)
from backend.entity.access.jobs import (
    enqueue_view_job,
    failed_recently,
    view_generation_state,
)
from backend.entity.access.plan import Head as _Head
from backend.entity.access.plan import attribute_fact as _fact
from backend.entity.access.plan import load_head as _require_head
from backend.entity.access.plan import load_policy as _policy
from backend.entity.access.masks import CLEAR, ModeError, validate_levels
from backend.entity.access.records import (
    AccessLogRecord,
    GrantRecord,
    LadderRecord,
    ProfileRecord,
    RestrictionRecord,
)
from backend.entity.access.store import get_access_store
from backend.entity.data.filters import compile_filters
from backend.entity.data.head import HeadTarget
from backend.entity.data.schema import build_schema
from backend.entity.entity_db import get_entity_engine
from backend.entity.errors import EntityNotServing, EntityRowInvalid
from backend.entity.ids import (
    new_access_grant_id,
    new_access_log_id,
    new_access_profile_id,
    new_access_restriction_id,
)
from backend.entity.parameters import max_profile_combinations
from backend.entity.records import AttributeRecord
from backend.entity.store import get_entity_store

__all__ = [
    "copy_profile",
    "create_grant",
    "create_profile",
    "create_restriction",
    "delete_grant",
    "delete_profile",
    "delete_restriction",
    "get_grant",
    "get_profile",
    "get_restriction",
    "list_grants",
    "list_ladders",
    "list_profiles",
    "list_restrictions",
    "preview",
    "put_ladder",
    "summary",
    "update_grant",
    "update_profile",
    "update_restriction",
    "view_ready",
]

_KEY = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_SYSTEM_RETRY_AFTER = timedelta(seconds=60)


def summary(entity_id: str) -> dict[str, Any]:
    head, compiled, revision = _live(entity_id)
    return {
        "entity_id": entity_id,
        "head_version_id": head.version_id,
        "policy_revision": revision,
        "views": _views(entity_id, head, compiled, revision),
        "ladders": _ladder_outs(head),
        "profiles": [_profile_out(head, compiled, item) for item in _ordered_profiles(entity_id)],
        "grants": [_grant_out(head, compiled, item) for item in _ordered_grants(entity_id)],
        "restrictions": [
            _restriction_out(head, compiled, item) for item in _ordered_restrictions(entity_id)
        ],
    }


def list_ladders(entity_id: str) -> dict[str, Any]:
    head, _compiled, _revision = _live(entity_id)
    return {"ladders": _ladder_outs(head)}


def put_ladder(
    entity_id: str,
    attribute_id: str,
    levels: list[dict[str, Any]],
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> dict[str, Any]:
    head = _require_head(entity_id)
    attr = _attr(head, attribute_id)
    try:
        parsed = validate_levels(levels, _fact(attr, head))
    except ModeError as exc:
        raise EntityAccessInvalid(exc.detail) from exc
    removed = _removed_levels(entity_id, attribute_id, {key for key, _mode in parsed})
    if removed:
        raise EntityAccessInUse("level is used by " + ", ".join(removed))
    now = utc_now()

    def mutate() -> None:
        get_access_store().save_ladder(
            LadderRecord(
                entity_id=entity_id,
                attribute_id=attribute_id,
                levels=[{"key": key, "mode": mode} for key, mode in parsed],
                updated_at=now,
            )
        )

    revision = _commit(
        entity_id,
        mutate,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        action="update",
        resource_type="entity_access_ladder",
        resource_id=attribute_id,
    )
    fresh, compiled, _revision = _live(entity_id)
    ladder = next(item for item in _ladder_outs(fresh) if item["attribute_id"] == attribute_id)
    return {"ladder": ladder, "policy_revision": revision}


def list_profiles(entity_id: str) -> dict[str, Any]:
    head, compiled, _revision = _live(entity_id)
    return {
        "profiles": [
            _profile_out(head, compiled, item) for item in _ordered_profiles(entity_id)
        ]
    }


def create_profile(
    entity_id: str,
    *,
    key: str,
    name: str,
    description: str | None,
    columns: list[dict[str, str]],
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> dict[str, Any]:
    head = _require_head(entity_id)
    _check_key(key)
    _check_columns(head, columns)
    if get_access_store().profile_by_key(entity_id, key) is not None:
        raise EntityAccessKeyDup()
    now = utc_now()
    record = ProfileRecord(
        id=new_access_profile_id(),
        entity_id=entity_id,
        key=key,
        name=name,
        description=description,
        columns=columns,
        created_at=now,
        updated_at=now,
    )

    def mutate() -> None:
        get_access_store().insert_profile(record)

    revision = _commit(
        entity_id,
        mutate,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        action="create",
        resource_type="entity_access_profile",
        resource_id=record.id,
    )
    fresh, compiled, _revision = _live(entity_id)
    return {
        "profile": _profile_out(fresh, compiled, record),
        "policy_revision": revision,
    }


def copy_profile(
    entity_id: str,
    *,
    source_entity_id: str,
    source_profile_id: str,
    key: str,
    name: str,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> dict[str, Any]:
    target = _require_head(entity_id)
    source = _require_head(source_entity_id)
    _check_key(key)
    found = get_access_store().profile(source_profile_id)
    if found is None or found.entity_id != source_entity_id:
        raise EntityAccessProfileNotFound()
    if get_access_store().profile_by_key(entity_id, key) is not None:
        raise EntityAccessKeyDup()
    columns, dropped = _copy_columns(source, target, found.columns)
    now = utc_now()
    record = ProfileRecord(
        id=new_access_profile_id(),
        entity_id=entity_id,
        key=key,
        name=name,
        description=found.description,
        columns=columns,
        created_at=now,
        updated_at=now,
    )

    def mutate() -> None:
        get_access_store().insert_profile(record)

    revision = _commit(
        entity_id,
        mutate,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        action="copy",
        resource_type="entity_access_profile",
        resource_id=record.id,
    )
    fresh, compiled, _revision = _live(entity_id)
    return {
        "profile": _profile_out(fresh, compiled, record),
        "dropped_columns": dropped,
        "policy_revision": revision,
    }


def get_profile(entity_id: str, profile_id: str) -> dict[str, Any]:
    head, compiled, _revision = _live(entity_id)
    return {"profile": _profile_out(head, compiled, _owned_profile(entity_id, profile_id))}


def update_profile(
    entity_id: str,
    profile_id: str,
    *,
    fields: set[str],
    name: str | None,
    description: str | None,
    columns: list[dict[str, str]] | None,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> dict[str, Any]:
    head = _require_head(entity_id)
    current = _owned_profile(entity_id, profile_id)
    if "columns" in fields and columns is not None:
        _check_columns(head, columns)
        current.columns = columns
    if "name" in fields and name is not None:
        current.name = name
    if "description" in fields:
        current.description = description
    current.updated_at = utc_now()

    def mutate() -> None:
        get_access_store().update_profile(current)

    revision = _commit(
        entity_id,
        mutate,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        action="update",
        resource_type="entity_access_profile",
        resource_id=profile_id,
    )
    fresh, compiled, _revision = _live(entity_id)
    return {
        "profile": _profile_out(fresh, compiled, current),
        "policy_revision": revision,
    }


def delete_profile(
    entity_id: str,
    profile_id: str,
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> None:
    _require_head(entity_id)
    _owned_profile(entity_id, profile_id)
    used = get_access_store().grants_for_profile(profile_id)
    if any(item.entity_id == entity_id for item in used):
        raise EntityAccessInUse("profile is referenced by a grant")

    def mutate() -> None:
        get_access_store().delete_profile(profile_id)

    _commit(
        entity_id,
        mutate,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        action="delete",
        resource_type="entity_access_profile",
        resource_id=profile_id,
    )


def list_grants(entity_id: str, *, limit: int, offset: int) -> dict[str, Any]:
    head, compiled, _revision = _live(entity_id)
    ordered = _ordered_grants(entity_id)
    page = ordered[offset : offset + limit]
    return {
        "items": [_grant_out(head, compiled, item) for item in page],
        "total": len(ordered),
        "limit": limit,
        "offset": offset,
    }


def create_grant(
    entity_id: str,
    *,
    subject: dict[str, str],
    profile_id: str,
    row_rule: dict[str, Any] | None,
    actions: list[str],
    status: str,
    valid_until: datetime | None,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> dict[str, Any]:
    head = _require_head(entity_id)
    _require_subject(subject)
    _owned_profile(entity_id, profile_id)
    normalized = _actions(actions)
    _check_rule(head, row_rule)
    now = utc_now()
    record = GrantRecord(
        id=new_access_grant_id(),
        entity_id=entity_id,
        subject_type=subject["type"],
        subject_id=subject["id"],
        profile_id=profile_id,
        row_rule=row_rule,
        actions=normalized,
        status=status,
        valid_until=valid_until,
        created_at=now,
        updated_at=now,
    )

    def mutate() -> None:
        get_access_store().insert_grant(record)

    revision = _commit(
        entity_id,
        mutate,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        action="create",
        resource_type="entity_access_grant",
        resource_id=record.id,
    )
    fresh, compiled, _revision = _live(entity_id)
    return {"grant": _grant_out(fresh, compiled, record), "policy_revision": revision}


def get_grant(entity_id: str, grant_id: str) -> dict[str, Any]:
    head, compiled, _revision = _live(entity_id)
    return {"grant": _grant_out(head, compiled, _owned_grant(entity_id, grant_id))}


def update_grant(
    entity_id: str,
    grant_id: str,
    *,
    fields: set[str],
    profile_id: str | None,
    row_rule: dict[str, Any] | None,
    actions: list[str] | None,
    status: str | None,
    valid_until: datetime | None,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> dict[str, Any]:
    head = _require_head(entity_id)
    current = _owned_grant(entity_id, grant_id)
    if "profile_id" in fields and profile_id is not None:
        _owned_profile(entity_id, profile_id)
        current.profile_id = profile_id
    if "row_rule" in fields:
        _check_rule(head, row_rule)
        current.row_rule = row_rule
    if "actions" in fields and actions is not None:
        current.actions = _actions(actions)
    if "status" in fields and status is not None:
        current.status = status
    if "valid_until" in fields:
        current.valid_until = valid_until
    current.updated_at = utc_now()

    def mutate() -> None:
        get_access_store().update_grant(current)

    revision = _commit(
        entity_id,
        mutate,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        action="update",
        resource_type="entity_access_grant",
        resource_id=grant_id,
    )
    fresh, compiled, _revision = _live(entity_id)
    return {"grant": _grant_out(fresh, compiled, current), "policy_revision": revision}


def delete_grant(
    entity_id: str,
    grant_id: str,
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> None:
    _require_head(entity_id)
    _owned_grant(entity_id, grant_id)

    def mutate() -> None:
        get_access_store().delete_grant(grant_id)

    _commit(
        entity_id,
        mutate,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        action="delete",
        resource_type="entity_access_grant",
        resource_id=grant_id,
    )


def list_restrictions(entity_id: str) -> dict[str, Any]:
    head, compiled, _revision = _live(entity_id)
    return {
        "restrictions": [
            _restriction_out(head, compiled, item)
            for item in _ordered_restrictions(entity_id)
        ]
    }


def create_restriction(
    entity_id: str,
    *,
    applies_to: dict[str, Any],
    row_rule: dict[str, Any] | None,
    deny_columns: list[str],
    ceilings: list[dict[str, str]],
    actions: list[str] | None,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> dict[str, Any]:
    head = _require_head(entity_id)
    normalized_applies = _applies(applies_to)
    normalized_actions = _actions(actions if actions is not None else list(ACTIONS))
    _check_restriction_body(head, row_rule, deny_columns, ceilings)
    now = utc_now()
    record = RestrictionRecord(
        id=new_access_restriction_id(),
        entity_id=entity_id,
        applies_to=normalized_applies,
        row_rule=row_rule,
        deny_columns=deny_columns,
        ceilings=ceilings,
        actions=normalized_actions,
        created_at=now,
        updated_at=now,
    )

    def mutate() -> None:
        get_access_store().insert_restriction(record)

    revision = _commit(
        entity_id,
        mutate,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        action="create",
        resource_type="entity_access_restriction",
        resource_id=record.id,
    )
    fresh, compiled, _revision = _live(entity_id)
    return {
        "restriction": _restriction_out(fresh, compiled, record),
        "policy_revision": revision,
    }


def get_restriction(entity_id: str, restriction_id: str) -> dict[str, Any]:
    head, compiled, _revision = _live(entity_id)
    return {
        "restriction": _restriction_out(
            head, compiled, _owned_restriction(entity_id, restriction_id)
        )
    }


def update_restriction(
    entity_id: str,
    restriction_id: str,
    *,
    fields: set[str],
    applies_to: dict[str, Any] | None,
    row_rule: dict[str, Any] | None,
    deny_columns: list[str] | None,
    ceilings: list[dict[str, str]] | None,
    actions: list[str] | None,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> dict[str, Any]:
    head = _require_head(entity_id)
    current = _owned_restriction(entity_id, restriction_id)
    if "applies_to" in fields and applies_to is not None:
        current.applies_to = _applies(applies_to)
    if "row_rule" in fields:
        current.row_rule = row_rule
    if "deny_columns" in fields and deny_columns is not None:
        current.deny_columns = deny_columns
    if "ceilings" in fields and ceilings is not None:
        current.ceilings = ceilings
    if "actions" in fields and actions is not None:
        current.actions = _actions(actions)
    _check_restriction_body(
        head, current.row_rule, list(current.deny_columns), list(current.ceilings)
    )
    current.updated_at = utc_now()

    def mutate() -> None:
        get_access_store().update_restriction(current)

    revision = _commit(
        entity_id,
        mutate,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        action="update",
        resource_type="entity_access_restriction",
        resource_id=restriction_id,
    )
    fresh, compiled, _revision = _live(entity_id)
    return {
        "restriction": _restriction_out(fresh, compiled, current),
        "policy_revision": revision,
    }


def delete_restriction(
    entity_id: str,
    restriction_id: str,
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> None:
    _require_head(entity_id)
    _owned_restriction(entity_id, restriction_id)

    def mutate() -> None:
        get_access_store().delete_restriction(restriction_id)

    _commit(
        entity_id,
        mutate,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        action="delete",
        resource_type="entity_access_restriction",
        resource_id=restriction_id,
    )


def preview(
    entity_id: str,
    *,
    subject: dict[str, str],
    narrow: dict[str, Any] | None,
    include_rows: bool,
    filters: dict[str, Any] | None,
    limit: int,
    offset: int,
    caller_user_id: str,
    caller_permissions: set[str],
    actor_token_id: str | None,
) -> dict[str, Any]:
    if subject.get("type") != "user":
        raise EntityAccessInvalid("preview subject type must be user")
    if include_rows and "entity:data_read" not in caller_permissions:
        raise AuthForbidden()
    user_id = str(subject.get("id") or "")
    if user_id not in existing_user_ids([user_id]):
        raise EntityAccessInvalid(f"unknown user '{user_id}'")
    head, compiled, revision = _live(entity_id)
    person = _person(user_id)
    parsed_narrow = _narrow(person, narrow)
    policy = _policy(head, revision)
    outcome = subject_outcome(
        compiled, policy, person, action="read", narrow=parsed_narrow
    )
    if outcome.over_limit:
        if include_rows:
            _write_log(
                caller_user_id,
                actor_token_id,
                entity_id,
                user_id,
                revision,
                outcome,
                parsed_narrow,
                row_count=None,
                outcome_code="ENTITY_ACCESS_COMBINATION_LIMIT",
            )
        raise EntityAccessCombinationLimit(
            "access configuration over limit for this subject"
        )
    schema = _schema(head, compiled, policy, person, parsed_narrow, outcome, revision)
    body: dict[str, Any] = {
        "policy_revision": revision,
        "effective_grants": list(outcome.grant_ids),
        "schema": schema,
        "rows": None,
    }
    if not include_rows:
        return body
    if head.physical is None or outcome.shape is None:
        _write_log(
            caller_user_id,
            actor_token_id,
            entity_id,
            user_id,
            revision,
            outcome,
            parsed_narrow,
            row_count=0 if outcome.shape is None else None,
            outcome_code="ok" if outcome.shape is None else "ENTITY_NOT_SERVING",
        )
        if outcome.shape is None:
            body["rows"] = {"items": [], "total": 0, "limit": limit, "offset": offset}
            return body
        raise EntityNotServing()
    try:
        _ensure_generated(head, outcome, revision, user_id=user_id)
    except EntityAccessPending:
        _write_log(
            caller_user_id,
            actor_token_id,
            entity_id,
            user_id,
            revision,
            outcome,
            parsed_narrow,
            row_count=None,
            outcome_code="ENTITY_ACCESS_PENDING",
        )
        raise
    try:
        rows, total = _read_rows(
            head, policy, person, outcome, filters, limit, offset
        )
    except Exception as exc:
        code = getattr(exc, "code", None) or "error"
        _write_log(
            caller_user_id,
            actor_token_id,
            entity_id,
            user_id,
            revision,
            outcome,
            parsed_narrow,
            row_count=None,
            outcome_code=str(code),
        )
        raise
    _write_log(
        caller_user_id,
        actor_token_id,
        entity_id,
        user_id,
        revision,
        outcome,
        parsed_narrow,
        row_count=len(rows),
        outcome_code="ok",
    )
    body["rows"] = {"items": rows, "total": total, "limit": limit, "offset": offset}
    return body


def _live(entity_id: str) -> tuple[_Head, CompiledPolicy, int]:
    head = _require_head(entity_id)
    revision = get_access_store().revision(entity_id)
    compiled = compile_policy(_policy(head, revision))
    return head, compiled, revision


def _commit(
    entity_id: str,
    mutate,
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str,
) -> int:
    store = get_access_store()
    with store.transaction() as session:
        mutate()
        revision = store.revision(entity_id) + 1
        store.set_revision(entity_id, revision)
        persist_audit_event(
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            result="success",
            detail={"entity_id": entity_id, "policy_revision": revision},
            session=session,
        )
    head = _require_head(entity_id)
    if head.physical is not None:
        enqueue_view_job(
            entity_id,
            policy_revision=revision,
            trigger_kind="user" if actor_user_id else "system",
            trigger_ref=actor_user_id,
            created_by=actor_user_id,
            label=head.table_name,
        )
    return revision


def _person(user_id: str) -> Person:
    user = get_user_store().get_by_id(user_id)
    if user is None:
        raise EntityAccessInvalid(f"unknown user '{user_id}'")
    return Person(user_id=user.id, role_id=user.role_id, group_ids=user_group_ids(user.id))


def _narrow(person: Person, raw: dict[str, Any] | None) -> Narrow | None:
    if raw is None:
        return None
    kind = raw.get("type")
    ident = raw.get("id")
    if kind == "user":
        if ident not in (None, person.user_id):
            raise EntityAccessInvalid("narrow user id must be the preview subject")
        return Narrow("user")
    if kind == "role":
        if not isinstance(ident, str) or ident != person.role_id:
            raise EntityAccessInvalid("narrow role is not an identity of the subject")
        return Narrow("role", ident)
    if kind == "group":
        if not isinstance(ident, str) or ident not in person.group_ids:
            raise EntityAccessInvalid("narrow group is not an identity of the subject")
        return Narrow("group", ident)
    raise EntityAccessInvalid("narrow type must be user, role, or group")


def view_ready(head: _Head, outcome: Outcome, revision: int) -> bool:
    """True when nothing is left to generate for this outcome at this revision."""
    if outcome.shape is None or head.physical is None:
        return True
    store = get_access_store()
    if store.views_revision(head.entity_id) != revision:
        return False
    return any(
        item.shape_key == outcome.shape.shape_key
        and item.policy_revision == revision
        for item in store.bindings(head.entity_id)
    )


def _ensure_generated(
    head: _Head, outcome: Outcome, revision: int, *, user_id: str
) -> None:
    if view_ready(head, outcome, revision):
        return
    if failed_recently(head.entity_id, now=utc_now(), within=_SYSTEM_RETRY_AFTER):
        raise EntityAccessPending("access configuration generation failed; retrying later")
    enqueue_view_job(
        head.entity_id,
        policy_revision=revision,
        trigger_kind="system",
        trigger_ref=user_id,
        created_by=None,
        label=head.table_name,
    )
    raise EntityAccessPending("access configuration generating")


def _views(
    entity_id: str, head: _Head, compiled: CompiledPolicy, revision: int
) -> dict[str, Any]:
    state = view_generation_state(
        entity_id,
        policy_revision=revision,
        has_head=head.physical is not None,
    )
    return {
        "state": state["state"],
        "revision": revision,
        "single_profile_views": compiled.single_profile_views,
        "combinations": compiled.combinations,
        "combination_limit": max_profile_combinations(),
        "subjects_over_limit": compiled.subjects_over_limit,
        "latest_job_id": state["latest_job_id"],
    }


def _ladder_outs(head: _Head) -> list[dict[str, Any]]:
    stored = {item.attribute_id: item.levels for item in get_access_store().ladders(head.entity_id)}
    outs: list[dict[str, Any]] = []
    for attr in head.attributes:
        if not attr.attribute_id:
            continue
        levels = stored.get(attr.attribute_id) or [{"key": CLEAR, "mode": CLEAR}]
        outs.append(
            {
                "attribute_id": attr.attribute_id,
                "attribute_name": attr.name,
                "type": attr.type,
                "levels": levels,
            }
        )
    return outs


def _profile_out(head: _Head, compiled: CompiledPolicy, record: ProfileRecord) -> dict[str, Any]:
    names = {attr.attribute_id: attr.name for attr in head.attributes if attr.attribute_id}
    reasons = list(compiled.broken_profiles.get(record.id, ()))
    return {
        "id": record.id,
        "entity_id": record.entity_id,
        "key": record.key,
        "name": record.name,
        "description": record.description,
        "columns": [
            {
                "attribute_id": column["attribute_id"],
                "attribute_name": names.get(column["attribute_id"]),
                "level": column["level"],
            }
            for column in record.columns
        ],
        "broken": bool(reasons),
        "broken_reasons": reasons,
        "created_at": format_instant(record.created_at),
        "updated_at": format_instant(record.updated_at),
    }


def _grant_out(head: _Head, compiled: CompiledPolicy, record: GrantRecord) -> dict[str, Any]:
    reasons = list(compiled.broken_grants.get(record.id, ()))
    warnings = [
        {
            "path": item.path,
            "attribute_id": item.attribute_id,
            "message": item.message,
        }
        for item in compiled.grant_warnings.get(record.id, ())
    ]
    return {
        "id": record.id,
        "entity_id": record.entity_id,
        "subject": _subject_out(record.subject_type, record.subject_id),
        "profile_id": record.profile_id,
        "row_rule": record.row_rule,
        "actions": list(record.actions),
        "status": record.status,
        "valid_until": format_instant(record.valid_until) if record.valid_until else None,
        "broken": bool(reasons),
        "broken_reasons": reasons,
        "warnings": warnings,
        "created_at": format_instant(record.created_at),
        "updated_at": format_instant(record.updated_at),
    }


def _restriction_out(
    head: _Head, compiled: CompiledPolicy, record: RestrictionRecord
) -> dict[str, Any]:
    del head
    reasons = list(compiled.broken_restrictions.get(record.id, ()))
    applies = {
        "mode": record.applies_to.get("mode"),
        "subjects": [
            _subject_out(str(item["type"]), str(item["id"]))
            for item in record.applies_to.get("subjects") or []
        ],
    }
    return {
        "id": record.id,
        "entity_id": record.entity_id,
        "applies_to": applies,
        "row_rule": record.row_rule,
        "deny_columns": list(record.deny_columns),
        "ceilings": list(record.ceilings),
        "actions": list(record.actions),
        "broken": bool(reasons),
        "broken_reasons": reasons,
        "created_at": format_instant(record.created_at),
        "updated_at": format_instant(record.updated_at),
    }


def _subject_out(kind: str, subject_id: str) -> dict[str, Any]:
    display = None
    missing = True
    if kind == "user":
        label = user_labels([subject_id]).get(subject_id)
        if label is not None:
            display = label.display_name
            missing = False
    elif kind == "role":
        role = get_role_store().get_by_id(subject_id)
        if role is not None:
            display = role.name
            missing = False
    else:
        name = group_labels([subject_id]).get(subject_id)
        if name is not None:
            display = name
            missing = False
    return {"type": kind, "id": subject_id, "display_name": display, "missing": missing}


def _schema(
    head: _Head,
    compiled: CompiledPolicy,
    policy: Policy,
    person: Person,
    narrow: Narrow | None,
    outcome: Outcome,
    revision: int,
) -> dict[str, Any]:
    write = subject_outcome(compiled, policy, person, action="write", narrow=narrow)
    writable: set[str] = set()
    if write.shape is not None:
        active = set(write.grant_ids)
        for column in write.shape.columns:
            if any(
                grant_id in active and mode == CLEAR
                for grant_id, mode in column.grant_modes
            ):
                writable.add(column.attr.name)
    full: dict[str, Any] | None = None
    target = _target(head)
    if target is not None:
        try:
            full = build_schema(target)
        except EntityNotServing:
            full = None
    by_name = {}
    if full is not None:
        by_name = {item["name"]: dict(item) for item in full["attributes"]}
    attributes = []
    for column in outcome.columns:
        payload = by_name.get(column.attr.name, {"name": column.attr.name, "type": column.attr.type})
        payload["attribute_id"] = column.attr.attribute_id
        payload["presentation"] = {
            "row_varying": column.row_varying,
            "levels": [{"key": level.key, "mode": level.mode} for level in column.levels],
            "may_be_withheld": column.may_be_withheld,
        }
        payload["writable"] = column.attr.name in writable
        attributes.append(payload)
    return {
        "attributes": attributes,
        "withheld_field": outcome.withheld_field,
        "access": {"policy_revision": revision, "narrowed": narrow is not None},
    }


def _target(head: _Head) -> HeadTarget | None:
    if head.version is None or head.physical is None or not head.source_sql:
        return None
    entity = get_entity_store().get_entity(head.entity_id)
    if entity is None:
        return None
    return HeadTarget(
        entity=entity,
        head=head.version,
        attributes=head.attributes,
        physical_table=head.physical,
        qualified_table=head.source_sql,
        writable=True,
    )


def _read_rows(
    head: _Head,
    policy: Policy,
    person: Person,
    outcome: Outcome,
    filters: dict[str, Any] | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    assert outcome.shape is not None
    values = policy.subject_values.get(person.user_id, {})
    sql = render_shape(
        outcome.shape,
        policy,
        acl=False,
        active=frozenset(outcome.grant_ids),
        person=person,
        subject_values=values,
        grant_flags=True,
    )
    params: dict[str, Any] = {}
    if filters:
        _reject_filter_fields(filters, {column.attr.name for column in outcome.columns})
        target = _target(head)
        if target is None:
            raise EntityNotServing()
        compiled = compile_filters(filters, target)
        if compiled is not None:
            sql = f"SELECT * FROM ({sql}) AS preview_filtered WHERE {compiled.sql}"
            params.update(compiled.params)
    rows, total = query_preview_page(sql, params, limit=limit, offset=offset)
    return [_public_row(outcome, row) for row in rows], total


def query_preview_page(
    sql: str, params: dict[str, Any], *, limit: int, offset: int
) -> tuple[list[dict[str, Any]], int]:
    count_sql = f"SELECT count(*) FROM ({sql}) AS preview_rows"
    page_sql = (
        f"SELECT * FROM ({sql}) AS preview_rows "
        "ORDER BY row_id LIMIT :_access_limit OFFSET :_access_offset"
    )
    bound = {**params, "_access_limit": limit, "_access_offset": offset}
    engine = get_entity_engine()
    with engine.connect() as conn:
        total = int(conn.execute(text(count_sql), bound).scalar_one())
        fetched = conn.execute(text(page_sql), bound).mappings().all()
    return [dict(item) for item in fetched], total


def _public_row(outcome: Outcome, row: dict[str, Any]) -> dict[str, Any]:
    flags = {
        key.removeprefix("__g_"): bool(value)
        for key, value in row.items()
        if str(key).startswith("__g_")
    }
    out: dict[str, Any] = {}
    sources: dict[str, list[str]] = {}
    for column in outcome.columns:
        out[column.attr.name] = _json_value(row.get(column.attr.name))
        matching = [
            (grant_id, mode)
            for grant_id, mode in column.grant_modes
            if flags.get(grant_id)
        ]
        if not matching:
            sources[column.attr.name] = []
            continue
        mode = matching[0][1]
        sources[column.attr.name] = [
            grant_id for grant_id, grant_mode in matching if grant_mode == mode
        ]
    if outcome.withheld_field:
        withheld = row.get("__withheld") or []
        out["__withheld"] = list(withheld)
    out["__sources"] = sources
    if "row_id" in row:
        out["row_id"] = row["row_id"]
    return out


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return format_instant(value)
    if hasattr(value, "isoformat") and not isinstance(value, str):
        return value.isoformat()
    return value


def _reject_filter_fields(node: Any, allowed: set[str]) -> None:
    if isinstance(node, dict):
        if "field" in node:
            field = node["field"]
            if field == "__withheld" or field not in allowed and field != "row_id":
                raise EntityRowInvalid(f"Unknown filter field '{field}'")
        for key in ("all", "any"):
            items = node.get(key)
            if isinstance(items, list):
                for item in items:
                    _reject_filter_fields(item, allowed)
    elif isinstance(node, list):
        for item in node:
            _reject_filter_fields(item, allowed)


def _write_log(
    caller_user_id: str,
    actor_token_id: str | None,
    entity_id: str,
    subject_user_id: str,
    revision: int,
    outcome: Outcome,
    narrow: Narrow | None,
    *,
    row_count: int | None,
    outcome_code: str,
) -> None:
    narrowing = None if narrow is None else {"type": narrow.kind, "id": narrow.id}
    view_name = outcome.shape.view_name if outcome.shape is not None else None
    get_access_store().append_log(
        AccessLogRecord(
            id=new_access_log_id(),
            created_at=utc_now(),
            user_id=caller_user_id,
            pat_id=actor_token_id,
            request_id=get_request_id(),
            entity_id=entity_id,
            verb="preview",
            effective_grant_ids=list(outcome.grant_ids),
            narrowing=narrowing,
            view_name=view_name,
            policy_revision=revision,
            row_count=row_count,
            outcome_code=outcome_code,
            preview_subject_user_id=subject_user_id,
        )
    )


def _ordered_profiles(entity_id: str) -> list[ProfileRecord]:
    return sorted(get_access_store().profiles(entity_id), key=lambda item: (item.key, item.id))


def _ordered_grants(entity_id: str) -> list[GrantRecord]:
    return sorted(
        get_access_store().grants(entity_id),
        key=lambda item: (item.created_at, item.id),
        reverse=True,
    )


def _ordered_restrictions(entity_id: str) -> list[RestrictionRecord]:
    return sorted(
        get_access_store().restrictions(entity_id),
        key=lambda item: (item.created_at, item.id),
        reverse=True,
    )


def _owned_profile(entity_id: str, profile_id: str) -> ProfileRecord:
    found = get_access_store().profile(profile_id)
    if found is None or found.entity_id != entity_id:
        raise EntityAccessProfileNotFound()
    return found


def _owned_grant(entity_id: str, grant_id: str) -> GrantRecord:
    found = get_access_store().grant(grant_id)
    if found is None or found.entity_id != entity_id:
        raise EntityAccessGrantNotFound()
    return found


def _owned_restriction(entity_id: str, restriction_id: str) -> RestrictionRecord:
    found = get_access_store().restriction(restriction_id)
    if found is None or found.entity_id != entity_id:
        raise EntityAccessRestrictionNotFound()
    return found


def _attr(head: _Head, attribute_id: str) -> AttributeRecord:
    for attr in head.attributes:
        if attr.attribute_id == attribute_id:
            return attr
    raise EntityAccessInvalid(f"unknown attribute '{attribute_id}'")


def _check_key(key: str) -> None:
    if not _KEY.fullmatch(key):
        raise EntityAccessInvalid("key must match [a-z][a-z0-9_]* and be at most 63 characters")


def _check_columns(head: _Head, columns: list[dict[str, str]]) -> None:
    seen: set[str] = set()
    facts = {item.attribute_id: item for item in head.facts}
    ladders = {
        item.attribute_id: {level["key"] for level in item.levels}
        for item in get_access_store().ladders(head.entity_id)
    }
    for column in columns:
        attribute_id = column["attribute_id"]
        if attribute_id in seen:
            raise EntityAccessInvalid(f"duplicate attribute '{attribute_id}'")
        seen.add(attribute_id)
        fact = facts.get(attribute_id)
        if fact is None:
            raise EntityAccessInvalid(f"unknown attribute '{attribute_id}'")
        allowed = ladders.get(attribute_id, {CLEAR})
        if column["level"] not in allowed:
            raise EntityAccessInvalid(
                f"level '{column['level']}' is not on the ladder for '{attribute_id}'"
            )


def _check_rule(head: _Head, rule: dict[str, Any] | None) -> None:
    if rule is None:
        return
    facts = {item.attribute_id: item for item in head.facts}
    subjects = {
        item.key: SubjectAttrFact(
            key=item.key,
            value_type=item.value_type,
            dictionary_id=item.dictionary_id,
            multi_value=item.multi_value,
        )
        for item in subject_attributes()
    }
    try:
        validate_rule(rule, facts, subjects)
    except RuleProblem as exc:
        raise EntityAccessInvalid(f"{exc.path}: {exc.detail}") from exc


def _check_restriction_body(
    head: _Head,
    row_rule: dict[str, Any] | None,
    deny_columns: list[str],
    ceilings: list[dict[str, str]],
) -> None:
    if row_rule is None and not deny_columns and not ceilings:
        raise EntityAccessInvalid(
            "a restriction needs a row rule, a denied column, or a ceiling"
        )
    _check_rule(head, row_rule)
    facts = {item.attribute_id: item for item in head.facts}
    ladders = {
        item.attribute_id: {level["key"] for level in item.levels}
        for item in get_access_store().ladders(head.entity_id)
    }
    for attribute_id in deny_columns:
        if attribute_id not in facts:
            raise EntityAccessInvalid(f"unknown attribute '{attribute_id}'")
    for ceiling in ceilings:
        attribute_id = ceiling["attribute_id"]
        if attribute_id not in facts:
            raise EntityAccessInvalid(f"unknown attribute '{attribute_id}'")
        allowed = ladders.get(attribute_id, {CLEAR})
        if ceiling["level"] not in allowed:
            raise EntityAccessInvalid(
                f"level '{ceiling['level']}' is not on the ladder for '{attribute_id}'"
            )


def _copy_columns(
    source: _Head, target: _Head, columns: list[dict[str, str]]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    source_by_id = {attr.attribute_id: attr for attr in source.attributes if attr.attribute_id}
    target_by_name = {attr.name: attr for attr in target.attributes if attr.attribute_id}
    target_ladders = {
        item.attribute_id: {level["key"] for level in item.levels}
        for item in get_access_store().ladders(target.entity_id)
    }
    kept: list[dict[str, str]] = []
    dropped: list[dict[str, str]] = []
    for column in columns:
        source_attr = source_by_id.get(column["attribute_id"])
        name = source_attr.name if source_attr is not None else column["attribute_id"]
        target_attr = target_by_name.get(name) if source_attr is not None else None
        if source_attr is None or target_attr is None or not target_attr.attribute_id:
            dropped.append({"attribute_name": name, "reason": "no attribute of the same name"})
            continue
        if not _compatible(source_attr, target_attr):
            dropped.append({"attribute_name": name, "reason": "incompatible attribute type"})
            continue
        allowed = target_ladders.get(target_attr.attribute_id, {CLEAR})
        if column["level"] not in allowed:
            dropped.append(
                {
                    "attribute_name": name,
                    "reason": f"level {column['level']} is not on the target ladder",
                }
            )
            continue
        kept.append({"attribute_id": target_attr.attribute_id, "level": column["level"]})
    return kept, dropped


def _compatible(source: AttributeRecord, target: AttributeRecord) -> bool:
    if source.type != target.type:
        return False
    if source.type == "dictionary" and source.dictionary_id != target.dictionary_id:
        return False
    if source.type == "reference" and source.target_entity_id != target.target_entity_id:
        return False
    return True


def _removed_levels(entity_id: str, attribute_id: str, kept: set[str]) -> list[str]:
    used: list[str] = []
    for profile in get_access_store().profiles(entity_id):
        for column in profile.columns:
            if column["attribute_id"] == attribute_id and column["level"] not in kept:
                used.append(f"profile {profile.key}")
    for restriction in get_access_store().restrictions(entity_id):
        for ceiling in restriction.ceilings:
            if ceiling["attribute_id"] == attribute_id and ceiling["level"] not in kept:
                used.append(f"restriction {restriction.id}")
    return used


def _actions(values: list[str]) -> list[str]:
    if not values:
        raise EntityAccessInvalid("actions must not be empty")
    unknown = sorted({item for item in values if item not in ACTIONS})
    if unknown:
        raise EntityAccessInvalid("unknown action " + ", ".join(unknown))
    if "write" in values and "read" not in values:
        raise EntityAccessInvalid("write requires read")
    return [item for item in ACTIONS if item in values]


def _applies(raw: dict[str, Any]) -> dict[str, Any]:
    mode = raw.get("mode")
    subjects = raw.get("subjects") or []
    if mode not in {"all", "only", "except"}:
        raise EntityAccessInvalid("applies_to.mode must be all, only, or except")
    if mode == "all" and subjects:
        raise EntityAccessInvalid("applies_to all must not list subjects")
    if mode != "all" and not subjects:
        raise EntityAccessInvalid("applies_to only and except need a subject list")
    cleaned = []
    for subject in subjects:
        _require_subject(subject)
        cleaned.append({"type": subject["type"], "id": subject["id"]})
    return {"mode": mode, "subjects": cleaned}


def _require_subject(subject: dict[str, str]) -> None:
    kind = subject.get("type")
    subject_id = subject.get("id")
    if kind not in {"user", "role", "group"} or not isinstance(subject_id, str):
        raise EntityAccessInvalid("subject requires type and id")
    if kind == "user" and subject_id not in existing_user_ids([subject_id]):
        raise EntityAccessInvalid(f"unknown user '{subject_id}'")
    if kind == "role" and get_role_store().get_by_id(subject_id) is None:
        raise EntityAccessInvalid(f"unknown role '{subject_id}'")
    if kind == "group" and subject_id not in existing_group_ids([subject_id]):
        raise EntityAccessInvalid(f"unknown group '{subject_id}'")

