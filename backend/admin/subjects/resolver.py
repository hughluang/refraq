"""Subject resolution for Entity access (published through ``backend.admin.subjects``)."""

from __future__ import annotations

from collections.abc import Iterable

from backend.admin.subjects.records import SubjectAttributeRecord, SubjectValue, UserLabel
from backend.admin.subjects.service import effective_values_of, user_groups_of
from backend.admin.subjects.store import get_subject_store
from backend.admin.user_store import get_user_store

__all__ = [
    "effective_subject_values",
    "existing_group_ids",
    "existing_user_ids",
    "group_labels",
    "subject_attributes",
    "user_group_ids",
    "user_labels",
]


def user_group_ids(user_id: str) -> tuple[str, ...]:
    """Ids of the User Groups the User belongs to, by group key."""
    return tuple(group.id for group in user_groups_of(user_id))


def effective_subject_values(user_id: str) -> dict[str, tuple[SubjectValue, ...]]:
    """Per Subject Attribute key: the User's own values united with its groups' values."""
    return {key: tuple(items) for key, items in effective_values_of(user_id).items()}


def existing_user_ids(user_ids: Iterable[str]) -> frozenset[str]:
    users = get_user_store()
    return frozenset(
        user_id for user_id in set(user_ids) if users.get_by_id(user_id) is not None
    )


def existing_group_ids(group_ids: Iterable[str]) -> frozenset[str]:
    return get_subject_store().existing_group_ids(group_ids)


def subject_attributes() -> tuple[SubjectAttributeRecord, ...]:
    """Every Subject Attribute definition, in catalog order."""
    records, _total = get_subject_store().list_definitions(limit=None)
    return tuple(records)


def group_labels(group_ids: Iterable[str]) -> dict[str, str]:
    """Group name per existing User Group id; unknown ids are omitted."""
    store = get_subject_store()
    out: dict[str, str] = {}
    for group_id in set(group_ids):
        group = store.get_group(group_id)
        if group is not None:
            out[group_id] = group.name
    return out


def user_labels(user_ids: Iterable[str]) -> dict[str, UserLabel]:
    """Account and display name per existing User id; unknown ids are omitted."""
    users = get_user_store()
    out: dict[str, UserLabel] = {}
    for user_id in set(user_ids):
        user = users.get_by_id(user_id)
        if user is not None:
            out[user_id] = UserLabel(account=user.account, display_name=user.display_name)
    return out
