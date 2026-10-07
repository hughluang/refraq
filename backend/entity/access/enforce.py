"""Data-plane access decision: visibility, shape, write attribution, and the log."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace

from backend.admin.roles import effective_permissions
from backend.admin.role_store import get_role_store
from backend.admin.user_store import UserRecord
from backend.core.config import get_settings
from backend.core.db import map_platform_db_error
from backend.core.request_id import get_request_id
from backend.core.time import utc_now
from backend.entity.access.context import KeyRing, issue_context, load_shared_ring
from backend.entity.access.compiler import (
    CompiledPolicy,
    Outcome,
    Policy,
    compile_policy,
    subject_outcome,
)
from backend.entity.access.dsl import eval_rule
from backend.entity.access.errors import (
    EntityAccessCombinationLimit,
    EntityAccessPending,
    EntityAccessWriteDenied,
)
from backend.entity.access.facts import GrantSpec, Narrow, Person
from backend.entity.ids import new_access_log_id
from backend.entity.access.plan import Head, load_head, load_policy
from backend.entity.access.records import AccessLogRecord
from backend.entity.access.service import _ensure_generated, _narrow, _person, view_ready
from backend.entity.access.store import get_access_store
from backend.entity.ddl import ENTITY_ACCESS_SCHEMA, qualified_table
from backend.entity.entity_db import get_entity_engine
from backend.entity.data.head import HeadTarget, resolve_head
from backend.entity.errors import EntityNotFound, EntityRequestInvalid
from backend.entity.store import get_entity_store

__all__ = [
    "DataAccess",
    "begin_data",
    "definition_allows",
    "sees_every_definition",
    "read_context",
    "read_view",
    "require_write_grant",
    "reset_signing_ring",
    "row_visible",
    "shape_names",
    "writable_names",
    "write_locator_target",
]


@dataclass
class DataAccess:
    user: UserRecord
    head: Head
    target: HeadTarget
    full: HeadTarget
    outcome: Outcome
    policy: Policy
    compiled: CompiledPolicy
    person: Person
    narrow: Narrow | None
    revision: int
    action: str
    started: float

    def log(self, *, row_count: int | None, outcome_code: str, verb: str) -> None:
        elapsed = int((time.perf_counter() - self.started) * 1000)
        view_name = self.outcome.shape.view_name if self.outcome.shape is not None else None
        narrowing = None if self.narrow is None else {"type": self.narrow.kind, "id": self.narrow.id}
        get_access_store().append_log(
            AccessLogRecord(
                id=new_access_log_id(),
                created_at=utc_now(),
                user_id=self.user.id,
                pat_id=None,
                request_id=get_request_id(),
                entity_id=self.target.entity.id,
                verb=verb,
                effective_grant_ids=list(self.outcome.grant_ids),
                narrowing=narrowing,
                view_name=view_name,
                policy_revision=self.revision,
                row_count=row_count,
                outcome_code=outcome_code,
                preview_subject_user_id=None,
                duration_ms=elapsed,
            )
        )


def begin_data(
    table_name: str,
    user: UserRecord,
    body: dict,
    *,
    action: str,
    for_write: bool,
) -> DataAccess:
    """Visibility, then configuration, then lifecycle, then narrow."""
    started = time.perf_counter()
    entity = get_entity_store_entity(table_name)
    if entity is None:
        raise _missing(table_name)
    head = load_head(entity.id)
    revision = get_access_store().revision(entity.id)
    person = _person(user.id)
    policy = load_policy(head, revision, people=(person,))
    compiled = compile_policy(policy)
    base = _subject_outcome(head, revision, person, policy, compiled, action, None)
    if base.over_limit:
        raise EntityAccessCombinationLimit(
            "access configuration over limit for this subject"
        )
    if not base.grant_ids:
        raise _missing(table_name)
    try:
        _ensure_generated(head, base, revision, user_id=user.id)
    except EntityAccessPending:
        _log_pending(user, entity.id, base, revision, action, started)
        raise
    target = resolve_head(table_name, for_write=for_write)
    narrow = _read_narrow(body, person, action=action)
    outcome = _subject_outcome(head, revision, person, policy, compiled, action, narrow)
    if outcome.over_limit:
        raise EntityAccessCombinationLimit(
            "access configuration over limit for this subject"
        )
    if not outcome.grant_ids or outcome.shape is None:
        raise _missing(table_name)
    try:
        _ensure_generated(head, outcome, revision, user_id=user.id)
    except EntityAccessPending:
        _log_pending(user, entity.id, outcome, revision, action, started)
        raise
    names = shape_names(outcome)
    shaped = tuple(attr for attr in target.attributes if attr.name in names)
    view = qualified_table(ENTITY_ACCESS_SCHEMA, outcome.shape.view_name)
    narrowed = replace(target, attributes=shaped, read_relation=view)
    return DataAccess(
        user=user,
        head=head,
        target=narrowed,
        full=target,
        outcome=outcome,
        policy=policy,
        compiled=compiled,
        person=person,
        narrow=narrow,
        revision=revision,
        action=action,
        started=started,
    )


def row_visible(access: DataAccess, row: dict) -> bool:
    outcome = subject_outcome(
        access.compiled,
        access.policy,
        access.person,
        action="read",
        narrow=access.narrow,
    )
    attrs = {item.attribute_id: item for item in access.policy.attributes}
    values = access.policy.subject_values.get(access.person.user_id, {})
    covered = False
    for grant_id in outcome.grant_ids:
        grant = _grant(access, grant_id)
        if grant is None:
            continue
        if eval_rule(
            grant.row_rule,
            row,
            attrs,
            subject_id=access.person.user_id,
            subject_values=values,
            now=access.policy.now,
        ):
            covered = True
            break
    if not covered:
        return False
    for item in access.policy.restrictions:
        if "read" not in item.actions or item.id in access.compiled.broken_restrictions:
            continue
        if item.mode != "all" and not _restriction_applies(item, access.person):
            continue
        if not eval_rule(
            item.row_rule,
            row,
            attrs,
            subject_id=access.person.user_id,
            subject_values=values,
            now=access.policy.now,
        ):
            return False
    return True


def writable_names(access: DataAccess) -> set[str]:
    outcome = subject_outcome(
        access.compiled,
        access.policy,
        access.person,
        action="write",
        narrow=None,
    )
    names: set[str] = set()
    for grant_id in outcome.grant_ids:
        grant = _grant(access, grant_id)
        if grant is not None and "write" in grant.actions:
            names |= _clear_names(access, grant)
    return names


def shape_names(outcome: Outcome) -> set[str]:
    return {column.attr.name for column in outcome.columns}


def require_write_grant(
    access: DataAccess,
    *,
    written: set[str],
    before: list[dict],
    after: list[dict],
) -> GrantSpec:
    """One write grant must cover every column and every pre-image and post-image."""
    matches: list[GrantSpec] = []
    grants = {
        grant.id: grant
        for grant in access.policy.grants
        if grant.id in access.outcome.grant_ids and "write" in grant.actions
    }
    # Recompute write grants; the opened outcome may be the read action.
    write_outcome = subject_outcome(
        access.compiled,
        access.policy,
        access.person,
        action="write",
        narrow=None,
    )
    for grant_id in write_outcome.grant_ids:
        grant = grants.get(grant_id) or _grant(access, grant_id)
        if grant is None or "write" not in grant.actions:
            continue
        if not written <= _clear_names(access, grant):
            continue
        if all(
            _row_ok(access, grant, row) for row in [*before, *after]
        ):
            matches.append(grant)
    if not matches:
        raise EntityAccessWriteDenied()
    return matches[0]


def sees_every_definition(user: UserRecord) -> bool:
    perms = _permissions(user)
    return "entity:write" in perms or "entity:access_manage" in perms


def definition_allows(user: UserRecord, entity_id: str) -> tuple[bool, bool, set[str] | None]:
    """Return (visible, physical names, shape names or None for every column)."""
    perms = _permissions(user)
    if "entity:write" in perms or "entity:access_manage" in perms:
        return True, "entity:write" in perms, None
    try:
        person = _person(user.id)
    except Exception:
        return False, False, set()
    head = load_head(entity_id)
    revision = get_access_store().revision(entity_id)
    policy = load_policy(head, revision, people=(person,))
    compiled = compile_policy(policy)
    outcome = subject_outcome(compiled, policy, person, action="read", narrow=None)
    if not outcome.grant_ids:
        return False, False, set()
    return True, False, shape_names(outcome)


def read_context(access: DataAccess) -> str | None:
    """Sign with the entity database's current acl key. None only in the memory backend.

    A failure is raised: a read without the context would silently see no rows.
    """
    if get_settings().store_backend != "persistent":
        return None
    try:
        ring = _signing_ring()
    except Exception as exc:
        mapped = map_platform_db_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise
    return issue_context(
        access.policy,
        access.compiled,
        access.person,
        ring,
        action=access.action,
        narrow=access.narrow,
        request_id=get_request_id() or "",
    )


def read_view(access: DataAccess) -> DataAccess | None:
    """The caller's read shape on the same Entity, for presenting written rows.

    None when the caller has no read grant or that view is not generated yet.
    """
    if access.action == "read":
        return access
    outcome = _subject_outcome(
        access.head,
        access.revision,
        access.person,
        access.policy,
        access.compiled,
        "read",
        None,
    )
    if outcome.over_limit or not outcome.grant_ids or outcome.shape is None:
        return None
    if not view_ready(access.head, outcome, access.revision):
        return None
    names = shape_names(outcome)
    target = replace(
        access.full,
        attributes=tuple(attr for attr in access.full.attributes if attr.name in names),
        read_relation=qualified_table(ENTITY_ACCESS_SCHEMA, outcome.shape.view_name),
    )
    return replace(access, target=target, outcome=outcome, action="read", narrow=None)


def write_locator_target(access: DataAccess) -> HeadTarget:
    """Write filters and locators compare stored values, so they may name only clear columns."""
    clear = writable_names(access)
    return replace(
        access.target,
        attributes=tuple(attr for attr in access.target.attributes if attr.name in clear),
    )


_RING_TTL_SEC = 30.0
_ring_cache: tuple[float, KeyRing] | None = None


def _signing_ring() -> KeyRing:
    """The newest acl signing key, re-read at most every ``_RING_TTL_SEC``.

    Both installed keys verify, so a cached ring stays valid across one rotation.
    """
    global _ring_cache
    now = time.monotonic()
    if _ring_cache is not None and now - _ring_cache[0] < _RING_TTL_SEC:
        return _ring_cache[1]
    with get_entity_engine().connect() as conn:
        ring = load_shared_ring(conn)
        conn.commit()
    _ring_cache = (now, ring)
    return ring


def reset_signing_ring() -> None:
    global _ring_cache
    _ring_cache = None


def _subject_outcome(
    head: Head,
    revision: int,
    person: Person,
    policy: Policy,
    compiled: CompiledPolicy,
    action: str,
    narrow: Narrow | None,
) -> Outcome:
    """Outcome from a one-subject compile; the full population decides the cap only when needed.

    Shapes and view names do not depend on other Users, so a generated view is served
    without loading them. A missing view is either new or over the combination cap.
    """
    outcome = subject_outcome(compiled, policy, person, action=action, narrow=narrow)
    if outcome.shape is None or view_ready(head, outcome, revision):
        return outcome
    full_policy = load_policy(head, revision)
    full = subject_outcome(
        compile_policy(full_policy), full_policy, person, action=action, narrow=narrow
    )
    return full if full.over_limit else outcome


def _clear_names(access: DataAccess, grant: GrantSpec) -> set[str]:
    profiles = {item.id: item for item in access.policy.profiles}
    profile = profiles.get(grant.profile_id)
    if profile is None:
        return set()
    denied = _denied_ids(access)
    names: set[str] = set()
    facts = {item.attribute_id: item for item in access.policy.attributes}
    for attribute_id, level_key in profile.columns:
        if attribute_id in denied or level_key != "clear":
            continue
        fact = facts.get(attribute_id)
        if fact is not None:
            names.add(fact.name)
    return names


def _denied_ids(access: DataAccess) -> set[str]:
    denied: set[str] = set()
    for item in access.policy.restrictions:
        if "write" not in item.actions or item.id in access.compiled.broken_restrictions:
            continue
        if item.mode != "all" and not _restriction_applies(item, access.person):
            continue
        denied.update(item.deny_columns)
        for attribute_id, level_key in item.ceilings:
            if level_key != "clear":
                denied.add(attribute_id)
    return denied


def _row_ok(access: DataAccess, grant: GrantSpec, row: dict) -> bool:
    attrs = {item.attribute_id: item for item in access.policy.attributes}
    values = access.policy.subject_values.get(access.person.user_id, {})
    if not eval_rule(
        grant.row_rule,
        row,
        attrs,
        subject_id=access.person.user_id,
        subject_values=values,
        now=access.policy.now,
    ):
        return False
    for item in access.policy.restrictions:
        if "write" not in item.actions or item.id in access.compiled.broken_restrictions:
            continue
        if item.mode != "all" and not _restriction_applies(item, access.person):
            continue
        if not eval_rule(
            item.row_rule,
            row,
            attrs,
            subject_id=access.person.user_id,
            subject_values=values,
            now=access.policy.now,
        ):
            return False
    return True


def _restriction_applies(item: object, person: Person) -> bool:
    mode = getattr(item, "mode")
    if mode == "all":
        return True
    hit = False
    for kind, subject_id in getattr(item, "subjects"):
        if kind == "user" and person.user_id == subject_id:
            hit = True
        elif kind == "role" and person.role_id == subject_id:
            hit = True
        elif kind == "group" and subject_id in person.group_ids:
            hit = True
    return hit if mode == "only" else not hit


def _grant(access: DataAccess, grant_id: str) -> GrantSpec | None:
    for grant in access.policy.grants:
        if grant.id == grant_id:
            return grant
    return None


def _read_narrow(body: dict, person: Person, *, action: str) -> Narrow | None:
    if "narrow" not in body:
        return None
    if action == "write":
        raise EntityRequestInvalid("narrow is not accepted on write")
    return _narrow(person, body.get("narrow"))


def _missing(table_name: str) -> EntityNotFound:
    return EntityNotFound(
        f"Business Entity with table_name '{table_name}' was not found"
    )


def _permissions(user: UserRecord) -> set[str]:
    if not user.role_id:
        return set()
    role = get_role_store().get_by_id(user.role_id)
    if role is None:
        return set()
    return set(effective_permissions(role))


def _log_pending(
    user: UserRecord,
    entity_id: str,
    outcome: Outcome,
    revision: int,
    verb: str,
    started: float,
) -> None:
    get_access_store().append_log(
        AccessLogRecord(
            id=new_access_log_id(),
            created_at=utc_now(),
            user_id=user.id,
            pat_id=None,
            request_id=get_request_id(),
            entity_id=entity_id,
            verb=verb,
            effective_grant_ids=list(outcome.grant_ids),
            narrowing=None,
            view_name=None,
            policy_revision=revision,
            row_count=None,
            outcome_code="ENTITY_ACCESS_PENDING",
            preview_subject_user_id=None,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    )


def get_entity_store_entity(table_name: str):
    return get_entity_store().get_entity_by_table_name(table_name)
