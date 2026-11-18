"""Source Access: membership persistence and effective access on a Source."""

from backend.metadata.source_access.errors import (
    SourceMembershipDuplicate,
    SourceMembershipLevelUnknown,
    SourceMembershipSubjectUnknown,
)
from backend.metadata.source_access.records import (
    ACCESS_LEVELS,
    EVERY_SOURCE_TARGET,
    AccessContribution,
    ExplainedSource,
    SourceIdSet,
    SourceMembership,
)
from backend.metadata.source_access.service import (
    allows,
    authorize_source_read_on,
    change_level,
    change_level_on,
    create_membership,
    create_membership_on,
    delete_for_source,
    delete_for_source_on,
    delete_membership,
    delete_membership_on,
    effective_level,
    effective_permissions,
    explain_user,
    list_memberships,
    source_ids_for,
)
from backend.metadata.source_access.store import reset_source_access_store

__all__ = [
    "ACCESS_LEVELS",
    "allows",
    "authorize_source_read_on",
    "EVERY_SOURCE_TARGET",
    "AccessContribution",
    "ExplainedSource",
    "SourceIdSet",
    "SourceMembership",
    "SourceMembershipDuplicate",
    "SourceMembershipLevelUnknown",
    "SourceMembershipSubjectUnknown",
    "change_level",
    "change_level_on",
    "create_membership",
    "create_membership_on",
    "delete_for_source",
    "delete_for_source_on",
    "delete_membership",
    "delete_membership_on",
    "effective_level",
    "effective_permissions",
    "explain_user",
    "list_memberships",
    "reset_source_access_store",
    "source_ids_for",
]
