"""Compile an access policy to profile-view SQL and to per-subject cells.

The cell rule is the full outer join of each effective grant on ``row_id``,
taking the most revealing ladder level, then applying ceilings. View SQL uses
the single-profile and combination templates. Bindings are stored by the
caller; this module does not execute DDL.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.entity.access.combos import (
    combo_key,
    grant_reaches,
    held_profiles,
    identity_narrows,
    select_combinations,
)
from backend.entity.access.dsl import (
    RuleWarning,
    eval_rule,
    rule_sql,
    rule_warnings,
    validate_rule,
)
from backend.entity.access.dsl import RuleProblem
from backend.entity.access.facts import (
    ACTIONS,
    AttrFact,
    GrantSpec,
    Level,
    Narrow,
    Person,
    ProfileSpec,
    RestrictionSpec,
    SubjectAttrFact,
)
from backend.entity.access.masks import CLEAR, mask_sql, mask_value
from backend.entity.ddl import (
    ENTITY_ACCESS_SCHEMA,
    EXPOSURE_OWNER_ROLE,
    READER_ROLE,
    ident,
)

__all__ = [
    "Binding",
    "ColumnPlan",
    "CompiledPolicy",
    "Outcome",
    "Policy",
    "Shape",
    "compile_policy",
    "context_attribute_keys",
    "project_subject",
    "render_grant_select",
    "render_shape",
    "script_statements",
    "subject_outcome",
    "view_statements",
]


@dataclass(frozen=True, slots=True)
class Policy:
    entity_id: str
    table_name: str
    revision: int
    source_sql: str
    head_version_id: str | None
    attributes: tuple[AttrFact, ...]
    ladders: dict[str, tuple[Level, ...]]
    profiles: tuple[ProfileSpec, ...]
    grants: tuple[GrantSpec, ...]
    restrictions: tuple[RestrictionSpec, ...]
    people: tuple[Person, ...]
    subject_attrs: dict[str, SubjectAttrFact]
    subject_values: dict[str, dict[str, tuple[Any, ...]]]
    cap: int
    existing_combos: frozenset[str]
    now: datetime


@dataclass(frozen=True, slots=True)
class ColumnPlan:
    attr: AttrFact
    row_varying: bool
    may_be_withheld: bool
    grant_modes: tuple[tuple[str, str | dict[str, Any]], ...]
    levels: tuple[Level, ...]


@dataclass(frozen=True, slots=True)
class Shape:
    action: str
    profile_ids: tuple[str, ...]
    combo_key: str
    shape_key: str
    grants: tuple[GrantSpec, ...]
    columns: tuple[ColumnPlan, ...]
    row_rules: tuple[dict[str, Any], ...]
    included_restrictions: tuple[str, ...]
    excluded_restrictions: tuple[str, ...]
    hide_restrictions: tuple[str, ...]
    force_empty: bool
    withheld: bool
    view_name: str


@dataclass(frozen=True, slots=True)
class Binding:
    combo_key: str
    shape_key: str
    action: str
    profile_ids: tuple[str, ...]
    view_name: str
    sql: str
    columns: tuple[dict[str, Any], ...]
    ddl_sha256: str
    status: str
    withheld: bool


@dataclass(frozen=True, slots=True)
class CompiledPolicy:
    shapes: tuple[Shape, ...]
    bindings: tuple[Binding, ...]
    single_profile_views: int
    combinations: int
    subjects_over_limit: int
    over_limit_user_ids: frozenset[str]
    emitted_combos: frozenset[str]
    broken_profiles: dict[str, tuple[str, ...]]
    broken_grants: dict[str, tuple[str, ...]]
    broken_restrictions: dict[str, tuple[str, ...]]
    grant_warnings: dict[str, tuple[RuleWarning, ...]]
    context_keys: frozenset[str]


@dataclass(frozen=True, slots=True)
class Outcome:
    hidden: bool
    over_limit: bool
    grant_ids: tuple[str, ...]
    columns: tuple[ColumnPlan, ...]
    withheld_field: str | None
    shape: Shape | None
    rows: tuple[dict[str, Any], ...] | None = None


def compile_policy(policy: Policy) -> CompiledPolicy:
    attrs = {item.attribute_id: item for item in policy.attributes}
    profiles = {item.id: item for item in policy.profiles}
    broken_profiles = {
        item.id: _profile_reasons(item, policy, attrs) for item in policy.profiles
    }
    broken_profiles = {key: value for key, value in broken_profiles.items() if value}
    broken_grants = {
        item.id: _grant_reasons(item, policy, attrs, profiles, broken_profiles)
        for item in policy.grants
    }
    broken_grants = {key: value for key, value in broken_grants.items() if value}
    broken_restrictions = {
        item.id: _restriction_reasons(item, policy, attrs)
        for item in policy.restrictions
    }
    broken_restrictions = {
        key: value for key, value in broken_restrictions.items() if value
    }
    warnings = {
        item.id: _grant_warnings(item, profiles)
        for item in policy.grants
        if item.id not in broken_grants
    }
    broken_ids = frozenset(broken_grants)
    needed: set[frozenset[str]] = set()
    holders: list[tuple[Person, str, Narrow | None, frozenset[str]]] = []
    for person in policy.people:
        for action in ACTIONS:
            for narrow in identity_narrows(person):
                if _person_hidden(policy, person, action, broken_restrictions):
                    continue
                profiles_held = held_profiles(
                    person,
                    policy.grants,
                    action=action,
                    narrow=narrow,
                    now=policy.now,
                    broken_grant_ids=broken_ids,
                )
                holders.append((person, action, narrow, profiles_held))
                if len(profiles_held) >= 2:
                    needed.add(profiles_held)
    existing = {
        frozenset(key.split(","))
        for key in policy.existing_combos
        if key
    }
    emitted, over = select_combinations(needed, existing, policy.cap)
    emitted_keys = frozenset(combo_key(item) for item in emitted)
    over_users = frozenset(
        person.user_id
        for person, _action, _narrow, held in holders
        if held in over
    )
    shapes = _shapes(
        policy,
        attrs,
        profiles,
        broken_profiles,
        broken_ids,
        broken_restrictions,
        emitted,
        holders,
    )
    bindings = tuple(_binding(policy, shape) for shape in shapes)
    single = len({shape.combo_key for shape in shapes if len(shape.profile_ids) == 1})
    return CompiledPolicy(
        shapes=shapes,
        bindings=bindings,
        single_profile_views=single,
        combinations=len(emitted),
        subjects_over_limit=len(over_users),
        over_limit_user_ids=over_users,
        emitted_combos=emitted_keys,
        broken_profiles=broken_profiles,
        broken_grants=broken_grants,
        broken_restrictions=broken_restrictions,
        grant_warnings=warnings,
        context_keys=context_attribute_keys(policy),
    )


def context_attribute_keys(policy: Policy) -> frozenset[str]:
    keys: set[str] = set()
    attrs = {item.attribute_id: item for item in policy.attributes}
    for grant in policy.grants:
        if grant.row_rule is None:
            continue
        try:
            info = validate_rule(grant.row_rule, attrs, policy.subject_attrs)
        except RuleProblem:
            continue
        keys.update(info.subject_keys)
        if info.uses_subject_id:
            keys.add("__access_subject")
    for item in policy.restrictions:
        if item.row_rule is not None:
            try:
                info = validate_rule(item.row_rule, attrs, policy.subject_attrs)
            except RuleProblem:
                info = None
            if info is not None:
                keys.update(info.subject_keys)
                if info.uses_subject_id:
                    keys.add("__access_subject")
        if item.mode != "all":
            keys.add("__access_subject")
            if any(kind == "role" for kind, _sid in item.subjects):
                keys.add("__access_role")
            if any(kind == "group" for kind, _sid in item.subjects):
                keys.add("__access_groups")
    return frozenset(keys)


def subject_outcome(
    compiled: CompiledPolicy,
    policy: Policy,
    person: Person,
    *,
    action: str,
    narrow: Narrow | None,
) -> Outcome:
    if _person_hidden(policy, person, action, compiled.broken_restrictions):
        return _empty_outcome(hidden=True)
    broken_ids = frozenset(compiled.broken_grants)
    grant_ids = tuple(
        grant.id
        for grant in policy.grants
        if grant_reaches(
            grant,
            person,
            action=action,
            narrow=narrow,
            now=policy.now,
            broken_grant_ids=broken_ids,
        )
    )
    held = held_profiles(
        person,
        policy.grants,
        action=action,
        narrow=narrow,
        now=policy.now,
        broken_grant_ids=broken_ids,
    )
    if len(held) >= 2 and combo_key(held) not in compiled.emitted_combos:
        return Outcome(
            hidden=False,
            over_limit=True,
            grant_ids=grant_ids,
            columns=(),
            withheld_field=None,
            shape=None,
        )
    shape = _shape_for(compiled, policy, person, action, held)
    if shape is None:
        return Outcome(
            hidden=False,
            over_limit=False,
            grant_ids=grant_ids,
            columns=(),
            withheld_field=None,
            shape=None,
        )
    return Outcome(
        hidden=False,
        over_limit=False,
        grant_ids=grant_ids,
        columns=shape.columns,
        withheld_field="__withheld" if shape.withheld else None,
        shape=shape,
    )


def project_subject(
    compiled: CompiledPolicy,
    policy: Policy,
    person: Person,
    rows: list[dict[str, Any]],
    *,
    action: str = "read",
    narrow: Narrow | None = None,
) -> Outcome:
    outcome = subject_outcome(
        compiled, policy, person, action=action, narrow=narrow
    )
    if outcome.hidden or outcome.over_limit or outcome.shape is None:
        return outcome
    values = policy.subject_values.get(person.user_id, {})
    attrs = {item.attribute_id: item for item in policy.attributes}
    projected: list[dict[str, Any]] = []
    active = [
        grant
        for grant in outcome.shape.grants
        if grant.id in outcome.grant_ids
    ]
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
    return Outcome(
        hidden=False,
        over_limit=False,
        grant_ids=outcome.grant_ids,
        columns=outcome.columns,
        withheld_field=outcome.withheld_field,
        shape=outcome.shape,
        rows=tuple(projected),
    )


def render_shape(
    shape: Shape,
    policy: Policy,
    *,
    acl: bool,
    active: frozenset[str] | None = None,
    person: Person | None = None,
    subject_values: dict[str, tuple[Any, ...]] | None = None,
    grant_flags: bool = False,
) -> str:
    select = _select_sql(
        shape,
        policy,
        acl=acl,
        active=active,
        person=person,
        subject_values=subject_values or {},
        grant_flags=grant_flags,
    )
    if not acl:
        return select
    return ";\n".join(view_statements(shape.view_name, select)) + ";"


def view_statements(view_name: str, select: str) -> list[str]:
    """CREATE, grant, and owner for one profile view, as separate statements.

    The grant precedes the owner change: the creating role loses grant rights once it
    no longer owns the view, and ALTER OWNER carries existing grants to the new owner.
    """
    view = f"{ident(ENTITY_ACCESS_SCHEMA)}.{ident(view_name)}"
    return [
        f"CREATE VIEW {view} WITH (security_barrier = true) AS\n{select}",
        f"GRANT SELECT ON {view} TO {ident(READER_ROLE)}",
        f"ALTER VIEW {view} OWNER TO {ident(EXPOSURE_OWNER_ROLE)}",
    ]


def script_statements(view_name: str, script: str) -> list[str]:
    """Inverse of ``render_shape(acl=True)`` for a stored script.

    Splits on the known grant/owner suffix, never on ``;``: rule literals may contain it.
    """
    create, grant, owner = view_statements(view_name, "")
    suffix = f";\n{grant};\n{owner};"
    if not script.startswith(create) or not script.endswith(suffix):
        raise ValueError(f"stored script is not a profile view script for '{view_name}'")
    return [script[: -len(suffix)], grant, owner]


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


def _shapes(
    policy: Policy,
    attrs: dict[str, AttrFact],
    profiles: dict[str, ProfileSpec],
    broken_profiles: dict[str, tuple[str, ...]],
    broken_ids: frozenset[str],
    broken_restrictions: dict[str, tuple[str, ...]],
    emitted: tuple[frozenset[str], ...],
    holders: list[tuple[Person, str, Narrow | None, frozenset[str]]],
) -> tuple[Shape, ...]:
    built: dict[tuple[str, str, tuple[str, ...]], Shape] = {}
    for action in ACTIONS:
        sets = [frozenset({item.id}) for item in policy.profiles]
        sets.extend(emitted)
        for profile_ids in sets:
            built.setdefault(
                (action, combo_key(profile_ids), ()),
                _make_shape(
                    policy,
                    attrs,
                    profiles,
                    broken_profiles,
                    broken_ids,
                    broken_restrictions,
                    action,
                    profile_ids,
                    included=(),
                ),
            )
    for person, action, _narrow, held in holders:
        if not held:
            continue
        if len(held) >= 2 and combo_key(held) not in {
            combo_key(item) for item in emitted
        }:
            continue
        included = _included_ids(policy, person, action, broken_restrictions)
        if not included:
            continue
        built.setdefault(
            (action, combo_key(held), included),
            _make_shape(
                policy,
                attrs,
                profiles,
                broken_profiles,
                broken_ids,
                broken_restrictions,
                action,
                held,
                included=included,
            ),
        )
    return tuple(built.values())


def _make_shape(
    policy: Policy,
    attrs: dict[str, AttrFact],
    profiles: dict[str, ProfileSpec],
    broken_profiles: dict[str, tuple[str, ...]],
    broken_ids: frozenset[str],
    broken_restrictions: dict[str, tuple[str, ...]],
    action: str,
    profile_ids: frozenset[str],
    *,
    included: tuple[str, ...],
) -> Shape:
    ordered_ids = tuple(sorted(profile_ids))
    key = combo_key(profile_ids)
    subject_specific = tuple(
        item.id
        for item in policy.restrictions
        if item.mode != "all"
        and action in item.actions
        and item.id not in broken_restrictions
    )
    excluded = tuple(item for item in subject_specific if item not in included)
    hide = tuple(
        item.id
        for item in policy.restrictions
        if item.mode != "all"
        and action in item.actions
        and item.id in broken_restrictions
    )
    force_empty = any(
        item.mode == "all" and action in item.actions and item.id in broken_restrictions
        for item in policy.restrictions
    ) or any(profile_id in broken_profiles for profile_id in ordered_ids)
    denies, ceilings = _column_effects(
        policy, action, broken_restrictions, included
    )
    grants = tuple(
        sorted(
            (
                grant
                for grant in policy.grants
                if grant.profile_id in profile_ids
                and grant.status == "active"
                and action in grant.actions
                and grant.id not in broken_ids
            ),
            key=lambda item: item.id,
        )
    )
    columns = () if force_empty else _columns(
        policy, attrs, profiles, ordered_ids, grants, denies, ceilings
    )
    row_rules = tuple(
        item.row_rule
        for item in policy.restrictions
        if (item.mode == "all" or item.id in included)
        and action in item.actions
        and item.id not in broken_restrictions
        and item.row_rule is not None
    )
    withheld = any(column.row_varying for column in columns) and len(ordered_ids) > 1
    signature = f"{action}|{key}|{','.join(included)}|{','.join(excluded)}"
    shape_key = hashlib.sha256(signature.encode()).hexdigest()
    return Shape(
        action=action,
        profile_ids=ordered_ids,
        combo_key=key,
        shape_key=shape_key,
        grants=grants,
        columns=columns,
        row_rules=row_rules,
        included_restrictions=included,
        excluded_restrictions=excluded,
        hide_restrictions=hide,
        force_empty=force_empty,
        withheld=withheld,
        view_name=_view_name(policy.table_name, policy.entity_id, shape_key),
    )


def _columns(
    policy: Policy,
    attrs: dict[str, AttrFact],
    profiles: dict[str, ProfileSpec],
    profile_ids: tuple[str, ...],
    grants: tuple[GrantSpec, ...],
    denies: frozenset[str],
    ceilings: dict[str, tuple[str, ...]],
) -> tuple[ColumnPlan, ...]:
    chosen: list[ColumnPlan] = []
    for attr in policy.attributes:
        if attr.attribute_id in denies or attr.attribute_id not in attrs:
            continue
        levels_by_profile: dict[str, str] = {}
        for profile_id in profile_ids:
            profile = profiles.get(profile_id)
            if profile is None:
                continue
            for attribute_id, level_key in profile.columns:
                if attribute_id == attr.attribute_id:
                    levels_by_profile[profile_id] = level_key
        if not levels_by_profile:
            continue
        ladder = _ladder(policy, attr.attribute_id)
        distinct_keys = set(levels_by_profile.values())
        missing = len(levels_by_profile) < len(profile_ids)
        row_varying = missing or len(distinct_keys) > 1
        modes: list[tuple[str, str | dict[str, Any]]] = []
        presented: list[Level] = []
        seen_levels: set[str] = set()
        ranked: list[tuple[int, str, str | dict[str, Any]]] = []
        for grant in grants:
            level_key = levels_by_profile.get(grant.profile_id)
            if level_key is None:
                continue
            presented_key, mode = _lower(level_key, ladder, ceilings.get(attr.attribute_id, ()))
            rank = _index(ladder, presented_key)
            ranked.append((rank, grant.id, mode))
            if presented_key not in seen_levels:
                seen_levels.add(presented_key)
                presented.append(ladder[rank])
        ranked.sort(key=lambda item: (item[0], item[1]))
        modes = [(grant_id, mode) for _rank, grant_id, mode in ranked]
        presented.sort(key=lambda level: _index(ladder, level.key))
        chosen.append(
            ColumnPlan(
                attr=attr,
                row_varying=row_varying,
                may_be_withheld=missing,
                grant_modes=tuple(modes),
                levels=tuple(presented),
            )
        )
    return tuple(chosen)


def _binding(policy: Policy, shape: Shape) -> Binding:
    sql = render_shape(shape, policy, acl=True)
    view_name = shape.view_name
    columns = tuple(
        {
            "attribute_id": column.attr.attribute_id,
            "name": column.attr.name,
            "type": column.attr.type,
            "row_varying": column.row_varying,
            "may_be_withheld": column.may_be_withheld,
            "levels": [
                {"key": level.key, "mode": level.mode} for level in column.levels
            ],
        }
        for column in shape.columns
    )
    return Binding(
        combo_key=shape.combo_key,
        shape_key=shape.shape_key,
        action=shape.action,
        profile_ids=shape.profile_ids,
        view_name=view_name,
        sql=sql,
        columns=columns,
        ddl_sha256=hashlib.sha256(sql.encode()).hexdigest(),
        status="stored",
        withheld=shape.withheld,
    )


def _select_sql(
    shape: Shape,
    policy: Policy,
    *,
    acl: bool,
    active: frozenset[str] | None,
    person: Person | None,
    subject_values: dict[str, tuple[Any, ...]],
    grant_flags: bool,
) -> str:
    attrs = {item.attribute_id: item for item in policy.attributes}
    flags = [
        (
            grant.id,
            _grant_flag(
                grant,
                policy,
                attrs,
                acl=acl,
                active=active,
                subject_values=subject_values,
            ),
        )
        for grant in shape.grants
    ]
    predicates = _predicates(shape, policy, attrs, acl=acl, person=person)
    if shape.force_empty:
        predicates.append("FALSE")
    grant_or = "(" + " OR ".join(flag for _gid, flag in flags) + ")" if flags else "FALSE"
    if len(shape.profile_ids) <= 1 or not shape.withheld and not any(
        column.row_varying for column in shape.columns
    ):
        return _single_sql(
            shape, policy, flags, predicates, grant_or, acl=acl, grant_flags=grant_flags
        )
    return _combo_sql(
        shape, policy, flags, predicates, acl=acl, grant_flags=grant_flags
    )


def _single_sql(
    shape: Shape,
    policy: Policy,
    flags: list[tuple[str, str]],
    predicates: list[str],
    grant_or: str,
    *,
    acl: bool,
    grant_flags: bool,
) -> str:
    pieces = ["t.row_id"]
    for column in shape.columns:
        mode = column.grant_modes[0][1] if column.grant_modes else CLEAR
        expr = mask_sql(f"t.{ident(column.attr.name)}", mode, column.attr, acl=acl)
        pieces.append(f"{expr} AS {ident(column.attr.name)}")
    if grant_flags:
        for grant_id, flag in flags:
            pieces.append(f"{flag} AS {ident('__g_' + grant_id)}")
    where = " AND ".join([*predicates, grant_or])
    return (
        "SELECT "
        + ", ".join(pieces)
        + f"\nFROM {policy.source_sql} AS t\nWHERE {where}"
    )


def _combo_sql(
    shape: Shape,
    policy: Policy,
    flags: list[tuple[str, str]],
    predicates: list[str],
    *,
    acl: bool,
    grant_flags: bool,
) -> str:
    inner_cols = ["t.row_id"]
    for column in shape.columns:
        inner_cols.append(f"t.{ident(column.attr.name)} AS {ident(column.attr.name)}")
    for grant_id, flag in flags:
        inner_cols.append(f"{flag} AS {ident(grant_id)}")
    where = " AND ".join(predicates) if predicates else "TRUE"
    outer = ["m.row_id"]
    for column in shape.columns:
        expr = _combo_expr(column, acl=acl)
        outer.append(f"{expr} AS {ident(column.attr.name)}")
    if shape.withheld:
        outer.append(f"{_withheld_sql(shape)} AS {ident('__withheld')}")
    if grant_flags:
        for grant_id, _flag in flags:
            outer.append(f"m.{ident(grant_id)} AS {ident('__g_' + grant_id)}")
    grant_or = (
        "(" + " OR ".join(f"m.{ident(grant_id)}" for grant_id, _flag in flags) + ")"
        if flags
        else "FALSE"
    )
    inner = (
        "SELECT "
        + ", ".join(inner_cols)
        + f"\nFROM {policy.source_sql} AS t\nWHERE {where}"
    )
    return (
        "SELECT "
        + ", ".join(outer)
        + f"\nFROM (\n{inner}\n) AS m\nWHERE {grant_or}"
    )


def _combo_expr(column: ColumnPlan, *, acl: bool) -> str:
    raw = f"m.{ident(column.attr.name)}"
    if not column.row_varying:
        mode = column.grant_modes[0][1] if column.grant_modes else CLEAR
        return mask_sql(raw, mode, column.attr, acl=acl)
    whens = [
        f"WHEN m.{ident(grant_id)} THEN {mask_sql(raw, mode, column.attr, acl=acl)}"
        for grant_id, mode in column.grant_modes
    ]
    if not whens:
        return mask_sql(raw, CLEAR, column.attr, acl=acl)
    return "CASE " + " ".join(whens) + " END"


def _withheld_sql(shape: Shape) -> str:
    parts: list[str] = []
    for column in shape.columns:
        if not column.may_be_withheld:
            continue
        grant_ids = [grant_id for grant_id, _mode in column.grant_modes]
        if not grant_ids:
            parts.append(f"'{column.attr.name}'")
            continue
        cond = " OR ".join(f"m.{ident(grant_id)}" for grant_id in grant_ids)
        parts.append(f"CASE WHEN NOT ({cond}) THEN '{column.attr.name}' END")
    if not parts:
        return "ARRAY[]::text[]"
    return "array_remove(ARRAY[" + ", ".join(parts) + "], NULL)"


def _predicates(
    shape: Shape,
    policy: Policy,
    attrs: dict[str, AttrFact],
    *,
    acl: bool,
    person: Person | None,
) -> list[str]:
    rev = (
        f"(SELECT acl.rev_ok('{_escape(policy.entity_id)}', {int(policy.revision)}))"
        if acl
        else "TRUE"
    )
    parts = [rev]
    for rule in shape.row_rules:
        parts.append(
            rule_sql(rule, attrs, alias="t", acl=acl, subject_values={})
        )
    by_id = {item.id: item for item in policy.restrictions}
    for restriction_id in shape.included_restrictions:
        parts.append(_applies_sql(by_id[restriction_id], acl=acl, person=person))
    for restriction_id in (*shape.excluded_restrictions, *shape.hide_restrictions):
        parts.append(
            f"(NOT {_applies_sql(by_id[restriction_id], acl=acl, person=person)})"
        )
    return parts


def _grant_flag(
    grant: GrantSpec,
    policy: Policy,
    attrs: dict[str, AttrFact],
    *,
    acl: bool,
    active: frozenset[str] | None,
    subject_values: dict[str, tuple[Any, ...]],
) -> str:
    if acl:
        gate = f"(SELECT acl.grant_active('{_escape(grant.id)}'))"
    elif active is None or grant.id in active:
        gate = "TRUE"
    else:
        gate = "FALSE"
    rule = rule_sql(
        grant.row_rule,
        attrs,
        alias="t",
        acl=acl,
        subject_values=subject_values,
    )
    pred = gate if rule == "TRUE" else f"({gate} AND {rule})"
    return f"COALESCE({pred}, false)"


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
        sources[column.attr.name] = [grant_id for grant_id, grant_mode in matching if grant_mode == mode]
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


def _shape_for(
    compiled: CompiledPolicy,
    policy: Policy,
    person: Person,
    action: str,
    held: frozenset[str],
) -> Shape | None:
    if not held:
        return None
    included = _included_ids(policy, person, action, compiled.broken_restrictions)
    key = combo_key(held)
    for shape in compiled.shapes:
        if (
            shape.action == action
            and shape.combo_key == key
            and shape.included_restrictions == included
        ):
            return shape
    return None


def _included_ids(
    policy: Policy,
    person: Person,
    action: str,
    broken: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    found: list[str] = []
    for item in policy.restrictions:
        if item.mode == "all" or action not in item.actions or item.id in broken:
            continue
        if not _applies(item, person):
            continue
        if item.deny_columns or item.ceilings or item.row_rule is not None:
            found.append(item.id)
    return tuple(sorted(found))


def _column_effects(
    policy: Policy,
    action: str,
    broken: dict[str, tuple[str, ...]],
    included: tuple[str, ...],
) -> tuple[frozenset[str], dict[str, tuple[str, ...]]]:
    denies: set[str] = set()
    ceilings: dict[str, list[str]] = {}
    included_set = set(included)
    for item in policy.restrictions:
        if action not in item.actions or item.id in broken:
            continue
        if item.mode != "all" and item.id not in included_set:
            continue
        denies.update(item.deny_columns)
        for attribute_id, level_key in item.ceilings:
            ceilings.setdefault(attribute_id, []).append(level_key)
    return frozenset(denies), {key: tuple(value) for key, value in ceilings.items()}


def _person_hidden(
    policy: Policy,
    person: Person,
    action: str,
    broken: dict[str, tuple[str, ...]],
) -> bool:
    for item in policy.restrictions:
        if item.id not in broken or action not in item.actions:
            continue
        if item.mode == "all" or _applies(item, person):
            return True
    return False


def _applies(item: RestrictionSpec, person: Person) -> bool:
    if item.mode == "all":
        return True
    hit = any(_person_hit(person, kind, subject_id) for kind, subject_id in item.subjects)
    return hit if item.mode == "only" else not hit


def _person_hit(person: Person, kind: str, subject_id: str) -> bool:
    if kind == "user":
        return person.user_id == subject_id
    if kind == "role":
        return person.role_id == subject_id
    return subject_id in person.group_ids


def _applies_sql(
    item: RestrictionSpec, *, acl: bool, person: Person | None
) -> str:
    if item.mode == "all":
        return "TRUE"
    if not acl and person is not None:
        return "TRUE" if _applies(item, person) else "FALSE"
    match = _match_sql(item.subjects)
    if item.mode == "only":
        return match
    return f"(NOT {match})"


def _match_sql(subjects: tuple[tuple[str, str], ...]) -> str:
    if not subjects:
        return "FALSE"
    parts: list[str] = []
    for kind, subject_id in subjects:
        quoted = _escape(subject_id)
        if kind == "user":
            parts.append(f"(SELECT acl.subject_text('__access_subject')) = '{quoted}'")
        elif kind == "role":
            parts.append(f"(SELECT acl.subject_text('__access_role')) = '{quoted}'")
        else:
            parts.append(
                "(SELECT acl.subject_text_array('__access_groups')) "
                f"&& ARRAY['{quoted}']::text[]"
            )
    return "(" + " OR ".join(parts) + ")"


def _empty_outcome(*, hidden: bool) -> Outcome:
    return Outcome(
        hidden=hidden,
        over_limit=False,
        grant_ids=(),
        columns=(),
        withheld_field=None,
        shape=None,
    )


def _profile_reasons(
    profile: ProfileSpec, policy: Policy, attrs: dict[str, AttrFact]
) -> tuple[str, ...]:
    reasons: list[str] = []
    seen: set[str] = set()
    for attribute_id, level_key in profile.columns:
        if attribute_id in seen:
            reasons.append(f"attribute '{attribute_id}' is listed twice")
        seen.add(attribute_id)
        if attribute_id not in attrs:
            reasons.append(f"attribute '{attribute_id}' is not in the head")
            continue
        if _find_level(policy, attribute_id, level_key) is None:
            reasons.append(
                f"level '{level_key}' is not on the ladder for '{attribute_id}'"
            )
    return tuple(reasons)


def _grant_reasons(
    grant: GrantSpec,
    policy: Policy,
    attrs: dict[str, AttrFact],
    profiles: dict[str, ProfileSpec],
    broken_profiles: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if grant.profile_id not in profiles:
        reasons.append(f"profile '{grant.profile_id}' does not exist")
    elif grant.profile_id in broken_profiles:
        reasons.append(f"profile '{grant.profile_id}' is broken")
    if grant.row_rule is not None:
        try:
            validate_rule(grant.row_rule, attrs, policy.subject_attrs)
        except RuleProblem as exc:
            reasons.append(f"{exc.path}: {exc.detail}")
    return tuple(reasons)


def _restriction_reasons(
    item: RestrictionSpec, policy: Policy, attrs: dict[str, AttrFact]
) -> tuple[str, ...]:
    reasons: list[str] = []
    for attribute_id in item.deny_columns:
        if attribute_id not in attrs:
            reasons.append(f"attribute '{attribute_id}' is not in the head")
    for attribute_id, level_key in item.ceilings:
        if attribute_id not in attrs:
            reasons.append(f"attribute '{attribute_id}' is not in the head")
        elif _find_level(policy, attribute_id, level_key) is None:
            reasons.append(
                f"level '{level_key}' is not on the ladder for '{attribute_id}'"
            )
    if item.row_rule is not None:
        try:
            validate_rule(item.row_rule, attrs, policy.subject_attrs)
        except RuleProblem as exc:
            reasons.append(f"{exc.path}: {exc.detail}")
    return tuple(reasons)


def _grant_warnings(
    grant: GrantSpec, profiles: dict[str, ProfileSpec]
) -> tuple[RuleWarning, ...]:
    profile = profiles.get(grant.profile_id)
    if profile is None or grant.row_rule is None:
        return ()
    visible = frozenset(attribute_id for attribute_id, _level in profile.columns)
    return rule_warnings(grant.row_rule, visible_attribute_ids=visible)


def _ladder(policy: Policy, attribute_id: str) -> tuple[Level, ...]:
    found = policy.ladders.get(attribute_id)
    if found:
        return found
    return (Level(CLEAR, CLEAR),)


def _find_level(policy: Policy, attribute_id: str, key: str) -> Level | None:
    for level in _ladder(policy, attribute_id):
        if level.key == key:
            return level
    return None


def _lower(
    level_key: str, ladder: tuple[Level, ...], ceilings: tuple[str, ...]
) -> tuple[str, str | dict[str, Any]]:
    rank = _index(ladder, level_key)
    for key in ceilings:
        crank = _index(ladder, key)
        if crank > rank:
            rank = crank
    level = ladder[rank]
    return level.key, level.mode


def _index(ladder: tuple[Level, ...], key: str) -> int:
    for index, level in enumerate(ladder):
        if level.key == key:
            return index
    return len(ladder) - 1


def _view_name(stem: str, entity_id: str, shape_key: str) -> str:
    digest = hashlib.sha256(f"{entity_id}\n{shape_key}".encode()).hexdigest()[:8]
    suffix = f"__p_{digest}"
    if len(stem) + len(suffix) <= 63:
        return f"{stem}{suffix}"
    return f"{stem[: 63 - len(suffix)]}{suffix}"


def _escape(value: str) -> str:
    return value.replace("'", "''")
