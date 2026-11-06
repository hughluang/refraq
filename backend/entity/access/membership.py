"""Which Entities one caller can see, without compiling access views.

List membership asks a boolean. View generation asks ``load_policy`` to load
every User so it can emit combination shapes. Those are different questions.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from backend.admin.subjects import subject_attributes, user_group_ids
from backend.admin.user_store import UserRecord
from backend.core.time import utc_now
from backend.entity.access.compiler import compile_policy, subject_outcome
from backend.entity.access.facts import Person, SubjectAttrFact
from backend.entity.access.plan import Head, head_from, policy_for_membership
from backend.entity.access.records import MembershipFacts
from backend.entity.access.store import get_access_store
from backend.entity.store import get_entity_store

__all__ = [
    "person_of",
    "readable_entity_ids",
]


def person_of(user: UserRecord) -> Person:
    return Person(
        user_id=user.id,
        role_id=user.role_id,
        group_ids=user_group_ids(user.id),
    )


def readable_entity_ids(
    entity_ids: Sequence[str], person: Person
) -> frozenset[str]:
    """Entity ids this person can read. Missing ids are omitted.

    The decision matches ``subject_outcome(..., action="read", narrow=None)``
    on a policy that carries this Entity's grants and head, and no population.
    """

    ids = frozenset(entity_ids)
    if not ids:
        return frozenset()
    sources = get_entity_store().membership_sources(ids)
    facts = get_access_store().membership_facts(frozenset(sources))
    subject_attrs = {
        item.key: SubjectAttrFact(
            key=item.key,
            value_type=item.value_type,
            dictionary_id=item.dictionary_id,
            multi_value=item.multi_value,
        )
        for item in subject_attributes()
    }
    now = utc_now()
    visible: set[str] = set()
    for entity_id, (entity, version) in sources.items():
        if _can_read(
            head_from(entity, version),
            facts[entity_id],
            person,
            subject_attrs=subject_attrs,
            now=now,
        ):
            visible.add(entity_id)
    return frozenset(visible)


def _can_read(
    head: Head,
    facts: MembershipFacts,
    person: Person,
    *,
    subject_attrs: dict[str, SubjectAttrFact],
    now: datetime,
) -> bool:
    policy = policy_for_membership(
        head,
        ladders=facts.ladders,
        profiles=facts.profiles,
        grants=facts.grants,
        restrictions=facts.restrictions,
        subject_attrs=subject_attrs,
        now=now,
    )
    compiled = compile_policy(policy)
    outcome = subject_outcome(compiled, policy, person, action="read", narrow=None)
    return bool(outcome.grant_ids)
