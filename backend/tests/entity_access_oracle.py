"""Test-only oracles and memory twins for Entity access.

Production evaluates access in the entity database (profile views and
``acl.ctx_payload``). These Python twins exist so conformance tests can compare
the SQL path with the normative definition in ``docs/business-entity-access.md``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass, fields, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from sqlalchemy import text

from backend.admin.role_store import get_role_store
from backend.admin.roles import SUPER_ADMIN_KEY, effective_permissions
from backend.core.time import utc_now
from backend.entity.access.compiler import (
    CompiledPolicy,
    Outcome,
    Policy,
    Shape,
    compile_policy,
    render_shape,
    subject_outcome,
)
from backend.entity.access.context import KeyRing, SigningKey
from backend.entity.access.dsl import eval_rule
from backend.entity.access import service
from backend.entity.access.errors import EntityAccessCombinationLimit
from backend.entity.access.plan import load_policy
from backend.entity.access.facts import AttrFact, GrantSpec, Narrow, Person, RestrictionSpec
from backend.entity.access.masks import CLEAR, ModeError
from backend.entity.access.records import GrantRecord
from backend.entity.access.seed import _ensure_profile, _grant_exists
from backend.entity.access.store import get_access_store
from backend.entity.access.views import rebuild_entity_views
from backend.entity.ids import new_access_grant_id
from backend.entity.lifecycle import PUBLISHED
from backend.entity.records import AttributeRecord
from backend.entity.store import get_entity_store
from backend.entity.table_name import published_attributes

__all__ = [
    "Projected",
    "install_signing_keys",
    "mask_value",
    "prepare_legacy_entity",
    "project_subject",
    "render_grant_select",
    "require_subject_view",
    "rotate_key",
    "seed_entity_entitlements",
    "stamped_attributes",
    "verify_token",
]


@dataclass(frozen=True, slots=True)
class Projected(Outcome):
    rows: tuple[dict[str, Any], ...] | None = None


def project_subject(
    compiled: CompiledPolicy,
    policy: Policy,
    person: Person,
    rows: list[dict[str, Any]],
    *,
    action: str = "read",
    narrow: Narrow | None = None,
) -> Outcome:
    """Normative cell rule over in-memory rows."""
    outcome = subject_outcome(compiled, policy, person, action=action, narrow=narrow)
    if outcome.hidden or outcome.over_limit or outcome.shape is None:
        return Projected(**{f.name: getattr(outcome, f.name) for f in fields(Outcome)})
    values = policy.subject_values.get(person.user_id, {})
    attrs = {item.attribute_id: item for item in policy.attributes}
    projected: list[dict[str, Any]] = []
    active = [grant for grant in outcome.shape.grants if grant.id in outcome.grant_ids]
    rules = _row_rules(policy, person, action, compiled.broken_restrictions)
    for row in rows:
        if not all(
            eval_rule(
                rule,
                row,
                attrs,
                subject_id=person.user_id,
                subject_values=values,
                now=policy.now,
            )
            for rule in rules
        ):
            continue
        covering = [
            grant
            for grant in active
            if eval_rule(
                grant.row_rule,
                row,
                attrs,
                subject_id=person.user_id,
                subject_values=values,
                now=policy.now,
            )
        ]
        if not covering:
            continue
        projected.append(_project_row(outcome.shape, row, covering))
    return Projected(
        hidden=False,
        over_limit=False,
        grant_ids=outcome.grant_ids,
        columns=outcome.columns,
        withheld_field=outcome.withheld_field,
        shape=outcome.shape,
        rows=tuple(projected),
    )


def render_grant_select(
    policy: Policy,
    grant: GrantSpec,
    *,
    subject_values: dict[str, tuple[Any, ...]] | None = None,
) -> str:
    """One grant as its own single-profile select, for the outer-join oracle."""
    compiled = compile_policy(policy)
    profile_ids = (grant.profile_id,)
    shape = next(
        item
        for item in compiled.shapes
        if item.action == "read"
        and item.profile_ids == profile_ids
        and not item.included_restrictions
    )
    return render_shape(
        shape,
        policy,
        acl=False,
        active=frozenset({grant.id}),
        subject_values=subject_values,
    )


def _project_row(
    shape: Shape, row: dict[str, Any], covering: list[GrantSpec]
) -> dict[str, Any]:
    out: dict[str, Any] = {"row_id": row.get("row_id")}
    withheld: list[str] = []
    sources: dict[str, list[str]] = {}
    covered = {grant.id for grant in covering}
    for column in shape.columns:
        matching = [
            (grant_id, mode)
            for grant_id, mode in column.grant_modes
            if grant_id in covered
        ]
        if not matching:
            out[column.attr.name] = None
            if column.may_be_withheld:
                withheld.append(column.attr.name)
            sources[column.attr.name] = []
            continue
        _grant_id, mode = matching[0]
        out[column.attr.name] = mask_value(row.get(column.attr.name), mode, column.attr)
        sources[column.attr.name] = [
            grant_id for grant_id, grant_mode in matching if grant_mode == mode
        ]
    if shape.withheld:
        out["__withheld"] = withheld
    out["__sources"] = sources
    return out


def _row_rules(
    policy: Policy,
    person: Person,
    action: str,
    broken: dict[str, tuple[str, ...]],
) -> tuple[dict[str, Any], ...]:
    found: list[dict[str, Any]] = []
    for item in policy.restrictions:
        if action not in item.actions or item.id in broken or item.row_rule is None:
            continue
        if item.mode == "all" or _applies(item, person):
            found.append(item.row_rule)
    return tuple(found)


def _applies(item: RestrictionSpec, person: Person) -> bool:
    hit = any(_person_hit(person, kind, sid) for kind, sid in item.subjects)
    return hit if item.mode == "only" else not hit


def _person_hit(person: Person, kind: str, subject_id: str) -> bool:
    if kind == "user":
        return person.user_id == subject_id
    if kind == "role":
        return person.role_id == subject_id
    return subject_id in person.group_ids


def mask_value(value: Any, mode: str | dict[str, Any], attr: AttrFact) -> Any:
    """Python twin of the inline mask expressions. Hash stays on acl.mask_hash."""
    if value is None or mode == CLEAR:
        return value
    assert isinstance(mode, dict)
    kind = str(mode["type"])
    if kind == "null":
        return None
    if kind == "partial":
        return _partial(str(value), int(mode["keep_first"]), int(mode["keep_last"]))
    if kind == "email":
        return _email(str(value))
    if kind == "redact":
        return "[redacted]"
    if kind == "hash":
        raise ModeError("hash preview requires acl.mask_hash")
    if kind == "truncate_date":
        return _truncate(value, str(mode["unit"]), attr)
    if kind == "bucket":
        return _bucket_value(value, mode["width"], attr)
    raise ModeError(f"unknown mask type '{kind}'")


def _partial(text: str, keep_first: int, keep_last: int) -> str:
    keep_first = min(max(keep_first, 0), 64)
    keep_last = min(max(keep_last, 0), 64)
    if len(text) <= keep_first + keep_last:
        return "*" * len(text)
    hidden = len(text) - keep_first - keep_last
    return text[:keep_first] + ("*" * hidden) + text[-keep_last:]


def _email(text: str) -> str:
    if "@" not in text:
        return (text[:1] + "***") if text else "***"
    local, _, domain = text.partition("@")
    return local[:1] + "***@" + domain


def _truncate(value: Any, unit: str, attr: AttrFact) -> Any:
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, date):
        moment = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    else:
        return value
    if unit == "year":
        clipped = moment.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    elif unit == "month":
        clipped = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        clipped = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    if attr.value_type() == "date":
        return clipped.date()
    return clipped


def _bucket_value(value: Any, width: Any, attr: AttrFact) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return value
    span = Decimal(str(width))
    if span <= 0:
        return None
    number = Decimal(str(value))
    if number.is_nan():
        return None
    floored = (number // span) * span
    kind = attr.value_type()
    if kind == "integer":
        return int(floored)
    if kind == "number":
        return float(floored)
    return floored


def require_subject_view(
    entity_id: str,
    user_id: str,
    *,
    action: str = "read",
    narrow: dict[str, Any] | None = None,
) -> Outcome:
    """Refuse until this subject's profile view matches the policy revision."""
    head, compiled, revision = service._live(entity_id)
    person = service._person(user_id)
    parsed = service._narrow(person, narrow)
    outcome = subject_outcome(
        compiled, load_policy(head, revision), person, action=action, narrow=parsed
    )
    if outcome.over_limit:
        raise EntityAccessCombinationLimit(
            "access configuration over limit for this subject"
        )
    service._ensure_generated(head, outcome, revision, user_id=user_id)
    return outcome


def install_signing_keys(conn: object, ring: KeyRing) -> None:
    """Install the ring into ``acl.signing_keys`` oldest first so the newest signs."""
    for key in ring.keys:
        conn.execute(  # type: ignore[union-attr]
            text("SELECT acl.install_key(:kid, :secret)"),
            {"kid": key.kid, "secret": key.secret},
        )


def rotate_key(ring: KeyRing, key: SigningKey) -> KeyRing:
    """Install ``key`` as the signer. A full ring drops the oldest key."""
    kept = [item for item in ring.keys if item.kid != key.kid]
    if len(kept) >= 2:
        kept = kept[-1:]
    return KeyRing(tuple([*kept, key]))


def verify_token(
    token: str,
    keys: Mapping[str, bytes],
    *,
    now: datetime,
) -> dict[str, Any] | None:
    """Python mirror of ``acl.ctx_payload``: bad signature, kid, or expiry yields None."""
    dot = token.find(".")
    if dot < 2:
        return None
    try:
        body = base64.b64decode(token[:dot], validate=True)
    except Exception:
        return None
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    kid = payload.get("kid")
    exp = payload.get("exp")
    if not isinstance(kid, str) or kid not in keys:
        return None
    if isinstance(exp, bool) or not isinstance(exp, (int, float)):
        return None
    secret = keys[kid]
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, token[dot + 1 :].lower()):
        return None
    if float(exp) <= now.timestamp():
        return None
    return payload


def seed_entity_entitlements(entity_id: str) -> bool:
    """all_clear profile and one grant per Role that holds data read or write.

    Memory twin of Alembic ``0054_entity_access_seed``.
    """
    attributes = stamped_attributes(entity_id)
    if not attributes:
        return False
    store = get_access_store()
    now = utc_now()
    profile = _ensure_profile(entity_id, attributes, now)
    inserted = False
    for role, actions in _entitled_roles():
        if _grant_exists(entity_id, "role", role.id, profile.id):
            continue
        store.insert_grant(
            GrantRecord(
                id=new_access_grant_id(),
                entity_id=entity_id,
                subject_type="role",
                subject_id=role.id,
                profile_id=profile.id,
                row_rule=None,
                actions=actions,
                status="active",
                valid_until=None,
                created_at=now,
                updated_at=now,
            )
        )
        inserted = True
    if inserted or store.revision(entity_id) == 0:
        store.set_revision(entity_id, store.revision(entity_id) + (1 if inserted else 0))
    return inserted


def prepare_legacy_entity(entity_id: str) -> None:
    """Give entitled Roles their seed grant and mark that Entity's views ready."""
    seed_entity_entitlements(entity_id)
    rebuild_entity_views(entity_id)


def _entitled_roles() -> list[tuple[Any, list[str]]]:
    roles, _total = get_role_store().list_roles(limit=None)
    found: list[tuple[Any, list[str]]] = []
    for role in roles:
        perms = set(effective_permissions(role))
        if role.key == SUPER_ADMIN_KEY:
            perms.update({"entity:data_read", "entity:data_write"})
        if "entity:data_read" not in perms and "entity:data_write" not in perms:
            continue
        actions = ["read"]
        if "entity:data_write" in perms:
            actions.append("write")
        found.append((role, actions))
    return found


def stamped_attributes(entity_id: str) -> list[AttributeRecord]:
    store = get_entity_store()
    versions = [
        item
        for item in store.list_all_versions(entity_id)
        if item.publish_status == PUBLISHED
    ]
    if not versions:
        return []
    version = max(versions, key=lambda item: item.version)
    changed = False
    attributes: list[AttributeRecord] = []
    for attr in version.attributes:
        if attr.attribute_id is None:
            attr = replace(attr, attribute_id=_stable_id(entity_id, attr.name))
            changed = True
        attributes.append(attr)
    stamped: list[dict] = []
    for item in version.materialized_attributes:
        payload = dict(item)
        if not isinstance(payload.get("attribute_id"), str):
            payload["attribute_id"] = _stable_id(entity_id, str(payload.get("name") or ""))
            changed = True
        stamped.append(payload)
    version = replace(version, attributes=attributes, materialized_attributes=stamped)
    if changed:
        store.save_version(replace(version, updated_at=utc_now()))
    return published_attributes(version)


def _stable_id(entity_id: str, name: str) -> str:
    digest = hashlib.sha256(f"{entity_id}\n{name}".encode()).hexdigest()[:12]
    return f"att_{digest}"
