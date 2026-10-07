"""Profile combinations actually held by current subjects, and the per-entity cap."""

from __future__ import annotations

from datetime import datetime

from backend.entity.access.facts import ACTIONS, GrantSpec, Narrow, Person

__all__ = [
    "combo_key",
    "grant_reaches",
    "held_profiles",
    "select_combinations",
]


def combo_key(profile_ids: frozenset[str]) -> str:
    return ",".join(sorted(profile_ids))


def select_combinations(
    needed: set[frozenset[str]],
    existing: set[frozenset[str]],
    cap: int,
) -> tuple[tuple[frozenset[str], ...], frozenset[frozenset[str]]]:
    """Keep already-emitted sets first. New sets fill the remaining cap."""
    multi = {item for item in needed if len(item) >= 2}
    kept = sorted((item for item in multi if item in existing), key=combo_key)
    fresh = sorted((item for item in multi if item not in existing), key=combo_key)
    emitted: list[frozenset[str]] = []
    for item in kept + fresh:
        if len(emitted) >= cap:
            break
        emitted.append(item)
    chosen = set(emitted)
    return tuple(emitted), frozenset(multi - chosen)


def held_profiles(
    person: Person,
    grants: tuple[GrantSpec, ...],
    *,
    action: str,
    narrow: Narrow | None,
    now: datetime,
    broken_grant_ids: frozenset[str],
) -> frozenset[str]:
    return frozenset(
        grant.profile_id
        for grant in grants
        if grant_reaches(
            grant,
            person,
            action=action,
            narrow=narrow,
            now=now,
            broken_grant_ids=broken_grant_ids,
        )
    )


def grant_reaches(
    grant: GrantSpec,
    person: Person,
    *,
    action: str,
    narrow: Narrow | None,
    now: datetime,
    broken_grant_ids: frozenset[str],
) -> bool:
    if grant.id in broken_grant_ids or grant.status != "active":
        return False
    if action not in grant.actions:
        return False
    if grant.valid_until is not None and now >= grant.valid_until:
        return False
    if narrow is None:
        return _subject_hit(grant, person)
    if narrow.kind == "user":
        return grant.subject_type == "user" and grant.subject_id == person.user_id
    if narrow.kind == "role":
        return (
            grant.subject_type == "role"
            and grant.subject_id == narrow.id
            and person.role_id == narrow.id
        )
    return (
        grant.subject_type == "group"
        and grant.subject_id == narrow.id
        and narrow.id in person.group_ids
    )


def identity_narrows(person: Person) -> tuple[Narrow | None, ...]:
    """Un-narrowed, plus every one-identity narrowing this person can name."""
    options: list[Narrow | None] = [None, Narrow("user")]
    if person.role_id:
        options.append(Narrow("role", person.role_id))
    options.extend(Narrow("group", group_id) for group_id in person.group_ids)
    return tuple(options)


def actions() -> tuple[str, ...]:
    return ACTIONS


def _subject_hit(grant: GrantSpec, person: Person) -> bool:
    if grant.subject_type == "user":
        return grant.subject_id == person.user_id
    if grant.subject_type == "role":
        return grant.subject_id == person.role_id
    return grant.subject_id in person.group_ids
