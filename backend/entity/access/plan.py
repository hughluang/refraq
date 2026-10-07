"""Load one Entity head and the policy the compiler and view generator share."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.admin.subjects import (
    effective_subject_values,
    subject_attributes,
    user_group_ids,
)
from backend.admin.user_store import get_user_store
from backend.core.time import utc_now
from backend.entity.access.compiler import Policy
from backend.entity.errors import EntityNotFound
from backend.entity.access.facts import (
    AttrFact,
    GrantSpec,
    Level,
    Person,
    ProfileSpec,
    RestrictionSpec,
    SubjectAttrFact,
)
from backend.entity.access.records import RestrictionRecord
from backend.entity.access.store import get_access_store
from backend.entity.ddl import ENTITY_DATA_SCHEMA, qualified_table
from backend.entity.lifecycle import PUBLISHED
from backend.entity.parameters import max_profile_combinations
from backend.entity.records import AttributeRecord, attribute_from_dict
from backend.entity.store import get_entity_store
from backend.entity.table_name import physical_table_name, table_present

__all__ = [
    "Head",
    "attribute_fact",
    "load_head",
    "load_policy",
    "make_head",
]


@dataclass
class Head:
    entity_id: str
    table_name: str
    version_id: str | None
    version: Any
    attributes: tuple[AttributeRecord, ...]
    facts: tuple[AttrFact, ...]
    physical: str | None
    source_sql: str


def make_head(
    *,
    entity_id: str,
    table_name: str,
    version_id: str | None,
    version: Any,
    attributes: tuple[AttributeRecord, ...],
    physical: str | None,
) -> Head:
    facts = tuple(
        attribute_fact(attr, version) for attr in attributes if attr.attribute_id
    )
    source = qualified_table(ENTITY_DATA_SCHEMA, physical) if physical else ""
    return Head(
        entity_id=entity_id,
        table_name=table_name,
        version_id=version_id,
        version=version,
        attributes=attributes,
        facts=facts,
        physical=physical,
        source_sql=source,
    )


def load_head(entity_id: str) -> Head:
    entity = get_entity_store().get_entity(entity_id)
    if entity is None:
        raise EntityNotFound()
    versions = get_entity_store().list_all_versions(entity_id)
    published = [item for item in versions if item.publish_status == PUBLISHED]
    if not published:
        return make_head(
            entity_id=entity.id,
            table_name=entity.table_name,
            version_id=None,
            version=None,
            attributes=(),
            physical=None,
        )
    version = max(published, key=lambda item: item.version)
    raw = version.materialized_attributes or [
        {"name": attr.name, "type": attr.type, "attribute_id": attr.attribute_id}
        for attr in version.attributes
    ]
    attributes = tuple(attribute_from_dict(item) for item in raw)
    physical = (
        physical_table_name(version, entity.table_name) if table_present(version) else None
    )
    return make_head(
        entity_id=entity.id,
        table_name=entity.table_name,
        version_id=version.id,
        version=version,
        attributes=attributes,
        physical=physical,
    )


def attribute_fact(attr: AttributeRecord, head: Any) -> AttrFact:
    version = head.version if isinstance(head, Head) else head
    codes: tuple[str, ...] | None = None
    reference_type = None
    reference_length = None
    if version is not None:
        snapshot = version.dictionary_snapshots.get(attr.name)
        if isinstance(snapshot, dict):
            codes = tuple(str(code) for code in (snapshot.get("codes") or []))
        ref = version.reference_snapshots.get(attr.name)
        if isinstance(ref, dict):
            reference_type = ref.get("type") if isinstance(ref.get("type"), str) else None
            length = ref.get("max_length")
            reference_length = length if isinstance(length, int) else None
    return AttrFact(
        attribute_id=attr.attribute_id or "",
        name=attr.name,
        type=attr.type,
        dictionary_id=attr.dictionary_id,
        max_length=attr.max_length,
        precision=attr.precision,
        scale=attr.scale,
        codes=codes,
        reference_key_type=reference_type,
        reference_max_length=reference_length,
    )


def load_policy(
    head: Head, revision: int, *, people: tuple[Person, ...] | None = None
) -> Policy:
    """``people=None`` loads every User, which view generation needs to pick combinations.

    A request passes only its subject: shapes and view names do not depend on the
    rest of the population, but the combination cap does (see ``enforce``).
    """
    store = get_access_store()
    facts = {item.attribute_id: item for item in head.facts}
    ladders = {
        record.attribute_id: tuple(
            Level(str(item["key"]), item["mode"]) for item in record.levels
        )
        for record in store.ladders(head.entity_id)
        if record.attribute_id in facts
    }
    profiles = tuple(
        ProfileSpec(
            id=item.id,
            key=item.key,
            columns=tuple(
                (str(column["attribute_id"]), str(column["level"]))
                for column in item.columns
            ),
        )
        for item in store.profiles(head.entity_id)
    )
    grants = tuple(
        GrantSpec(
            id=item.id,
            subject_type=item.subject_type,  # type: ignore[arg-type]
            subject_id=item.subject_id,
            profile_id=item.profile_id,
            row_rule=item.row_rule,
            actions=frozenset(item.actions),
            status=item.status,
            valid_until=item.valid_until,
        )
        for item in store.grants(head.entity_id)
    )
    restrictions = tuple(
        _restriction_spec(item) for item in store.restrictions(head.entity_id)
    )
    people, values = _population() if people is None else _subjects(people)
    existing = frozenset(
        item.combo_key for item in store.bindings(head.entity_id) if "," in item.combo_key
    )
    return Policy(
        entity_id=head.entity_id,
        table_name=head.table_name,
        revision=revision,
        source_sql=head.source_sql or 'entity_data."unbound"',
        head_version_id=head.version_id,
        attributes=head.facts,
        ladders=ladders,
        profiles=profiles,
        grants=grants,
        restrictions=restrictions,
        people=people,
        subject_attrs={
            item.key: SubjectAttrFact(
                key=item.key,
                value_type=item.value_type,
                dictionary_id=item.dictionary_id,
                multi_value=item.multi_value,
            )
            for item in subject_attributes()
        },
        subject_values=values,
        cap=max_profile_combinations(),
        existing_combos=existing,
        now=utc_now(),
    )


def _restriction_spec(item: RestrictionRecord) -> RestrictionSpec:
    applies = item.applies_to
    subjects = tuple(
        (str(subject["type"]), str(subject["id"])) for subject in applies.get("subjects") or []
    )
    return RestrictionSpec(
        id=item.id,
        mode=str(applies.get("mode") or "all"),  # type: ignore[arg-type]
        subjects=subjects,
        row_rule=item.row_rule,
        deny_columns=tuple(item.deny_columns),
        ceilings=tuple(
            (str(ceiling["attribute_id"]), str(ceiling["level"])) for ceiling in item.ceilings
        ),
        actions=frozenset(item.actions),
    )


def _population() -> tuple[tuple[Person, ...], dict[str, dict[str, tuple[Any, ...]]]]:
    users, _total = get_user_store().list_users(limit=None)
    people: list[Person] = []
    values: dict[str, dict[str, tuple[Any, ...]]] = {}
    for user in users:
        groups = user_group_ids(user.id)
        people.append(Person(user_id=user.id, role_id=user.role_id, group_ids=groups))
        values[user.id] = _values_of(user.id)
    return tuple(people), values


def _subjects(
    people: tuple[Person, ...],
) -> tuple[tuple[Person, ...], dict[str, dict[str, tuple[Any, ...]]]]:
    return people, {person.user_id: _values_of(person.user_id) for person in people}


def _values_of(user_id: str) -> dict[str, tuple[Any, ...]]:
    return {key: tuple(items) for key, items in effective_subject_values(user_id).items()}
