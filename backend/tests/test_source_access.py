"""Connector Spec access interpretation, and Source Membership resolution.

Connector tests cover endpoint projection. Membership tests cover the Source
Access module through its public functions and the memory store.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from backend.admin.federation.config import validate_default_role
from backend.admin.federation.errors import ProviderDefaultRoleForbidden
from backend.admin.permissions import (
    ALL_PERMISSIONS,
    GRANTING_PERMISSIONS,
    PERMISSION_DESCRIPTIONS,
)
from backend.admin.role_store import RoleRecord, get_role_store
from backend.admin.roles import (
    OPERATOR_DEFAULT_PERMISSIONS,
    create_role,
    effective_permissions as role_permissions,
    seed_roles,
)
from backend.admin.subjects.service import add_member, create_group, delete_group, remove_member
from backend.admin.user_store import get_user_store
from backend.core.time import utc_now
from backend.metadata.connectors.specs import get_connector_spec
from backend.metadata.errors import SourceAccessInvalid
from backend.metadata.source_access import (
    EVERY_SOURCE_TARGET,
    SourceIdSet,
    SourceMembershipDuplicate,
    SourceMembershipLevelUnknown,
    SourceMembershipSubjectUnknown,
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
    reset_source_access_store,
    source_ids_for,
)
from backend.metadata.sources.access import (
    endpoint_from_access,
    project_access,
)
from backend.metadata.sources.store import SourceRecord, get_source_store, new_source_id


def _base_access(**scope: object) -> dict[str, Any]:
    access: dict[str, Any] = {
        "host": "db.example.internal",
        "port": 5432,
        "username": "meta",
        "password": "secret",
        "ssl_mode": "disable",
        "extra": {},
    }
    access.update(scope)
    return access


def test_postgres_endpoint_uses_database_and_schema() -> None:
    endpoint = endpoint_from_access(
        engine="postgresql",
        access=_base_access(database="mes", schema="public"),
    )
    assert endpoint.database_name == "mes"
    assert endpoint.schema_filter == "public"
    assert endpoint.host == "db.example.internal"
    assert endpoint.password == "secret"


def test_oracle_endpoint_uses_service_name_and_owner() -> None:
    endpoint = endpoint_from_access(
        engine="oracle",
        access=_base_access(
            port=1521,
            service_name="ORCL",
            owner="MES",
        ),
    )
    assert endpoint.database_name == "ORCL"
    assert endpoint.schema_filter == "MES"


def test_mssql_endpoint_uses_database_and_schema() -> None:
    endpoint = endpoint_from_access(
        engine="mssql",
        access=_base_access(port=1433, database="app", schema="dbo"),
    )
    assert endpoint.database_name == "app"
    assert endpoint.schema_filter == "dbo"


def test_scope_mapping_comes_from_spec_x_scope() -> None:
    pg = get_connector_spec("postgresql")["properties"]
    assert pg["database"]["x-scope"] == "catalog"
    assert pg["schema"]["x-scope"] == "schema"
    oracle = get_connector_spec("oracle")["properties"]
    assert oracle["service_name"]["x-scope"] == "catalog"
    assert oracle["owner"]["x-scope"] == "schema"


def test_endpoint_follows_synthetic_x_scope_not_engine_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = {
        "properties": {
            "host": {},
            "port": {},
            "username": {},
            "password": {},
            "lib": {"x-scope": "catalog"},
            "ns": {"x-scope": "schema"},
        }
    }
    monkeypatch.setattr(
        "backend.metadata.sources.access.connector_specs.get_connector_spec",
        lambda engine: spec,
    )
    endpoint = endpoint_from_access(
        engine="postgresql",
        access=_base_access(
            lib="CAT",
            ns="NS",
            database="would-be-wrong",
            schema="would-be-wrong",
        ),
    )
    assert endpoint.database_name == "CAT"
    assert endpoint.schema_filter == "NS"


def test_missing_x_scope_on_spec_is_authoring_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.metadata.sources.access.connector_specs.get_connector_spec",
        lambda engine: {"properties": {"database": {}}},
    )
    with pytest.raises(RuntimeError, match="must mark x-scope"):
        endpoint_from_access(engine="postgresql", access=_base_access())


def test_missing_scope_value_is_access_invalid() -> None:
    with pytest.raises(SourceAccessInvalid, match="access.database is required"):
        endpoint_from_access(
            engine="postgresql",
            access=_base_access(schema="public"),
        )


def test_project_access_strips_x_secret() -> None:
    projected = project_access(
        "postgresql",
        _base_access(
            database="mes",
            schema="public",
            ssl_root_cert="PEM",
        ),
    )
    assert "password" not in projected
    assert "ssl_root_cert" not in projected
    assert projected["host"] == "db.example.internal"
    assert projected["database"] == "mes"
    assert projected["schema"] == "public"


VIEWER_KEYS = frozenset(
    {"sources:read", "metadata:read", "catalog:sample", "query:run"}
)
STEWARD_KEYS = VIEWER_KEYS | frozenset({"metadata:write"})
MAINTAINER_KEYS = STEWARD_KEYS | frozenset({"sources:write", "jobs:run"})
NO_SOURCES = SourceIdSet(all_sources=False, source_ids=frozenset())
ALL_SOURCES = SourceIdSet(all_sources=True, source_ids=frozenset())


@pytest.fixture(autouse=True)
def _reset_source_access() -> None:
    reset_source_access_store()
    yield
    reset_source_access_store()


def _role(key: str, name: str, permissions: list[str]) -> RoleRecord:
    return create_role(get_role_store(), key=key, name=name, permissions=permissions)


def _user(
    account: str,
    display_name: str,
    role_id: str | None,
    *,
    status: str = "active",
) -> object:
    return get_user_store().create_user(
        account=account,
        display_name=display_name,
        password_hash=None,
        role_id=role_id,
        status=status,  # type: ignore[arg-type]
    )


def _register_source(key: str) -> str:
    now = utc_now()
    record = get_source_store().create_source(
        SourceRecord(
            id=new_source_id(),
            key=key,
            locator_key=f"src/postgresql/{key}",
            name=key,
            kind="database",
            status="active",
            description=None,
            engine="postgresql",
            access_ciphertext=None,
            access_updated_at=None,
            created_at=now,
            updated_at=now,
        )
    )
    return record.id


def _kinds(
    user_id: str, source_id: str
) -> tuple[str, set[tuple[str, str, str, str | None]]]:
    found = {item.source_id: item for item in explain_user(user_id)}
    item = found[source_id]
    return item.level, {
        (contribution.kind, contribution.subject_name, contribution.level, contribution.membership_id)
        for contribution in item.contributions
    }


def test_viewer_steward_and_maintainer_allow_the_ladder_keys() -> None:
    role = _role("analyst", "Analyst", sorted(MAINTAINER_KEYS))
    user = _user("ada", "Ada", role.id)
    target = "src_alpha"
    assert EVERY_SOURCE_TARGET == "*"
    assert effective_level(user.id, target) is None
    assert effective_permissions(user.id, target) == frozenset()

    created = create_membership(
        subject_type="user",
        subject_id=user.id,
        target=target,
        level="viewer",
    )
    assert re.fullmatch(r"smb_[0-9a-f]{12}", created.id)
    assert created.subject_name == "Ada"
    assert effective_level(user.id, target) == "viewer"
    assert effective_permissions(user.id, target) == VIEWER_KEYS

    change_level(created.id, "steward")
    assert effective_level(user.id, target) == "steward"
    assert effective_permissions(user.id, target) == STEWARD_KEYS

    change_level(created.id, "maintainer")
    assert effective_level(user.id, target) == "maintainer"
    assert effective_permissions(user.id, target) == MAINTAINER_KEYS


def test_effective_level_is_the_highest_match() -> None:
    role = _role("analyst", "Analyst", sorted(MAINTAINER_KEYS))
    other_role = _role("other", "Other", sorted(MAINTAINER_KEYS))
    user = _user("ada", "Ada", role.id)
    outsider = _user("bea", "Bea", other_role.id)
    group = create_group(
        key="warehouse",
        name="Warehouse",
        description=None,
        actor_user_id=user.id,
        actor_token_id=None,
    )
    ignored = create_group(
        key="ignored",
        name="Ignored",
        description=None,
        actor_user_id=user.id,
        actor_token_id=None,
    )
    add_member(group.id, user.id, actor_user_id=user.id, actor_token_id=None)
    alpha = _register_source("alpha")
    beta = _register_source("beta")
    gamma = _register_source("gamma")

    create_membership(
        subject_type="user", subject_id=user.id, target=alpha, level="viewer"
    )
    create_membership(
        subject_type="group", subject_id=group.id, target=alpha, level="steward"
    )
    create_membership(
        subject_type="role", subject_id=role.id, target=beta, level="maintainer"
    )
    create_membership(
        subject_type="group", subject_id=ignored.id, target=gamma, level="maintainer"
    )
    create_membership(
        subject_type="role", subject_id=other_role.id, target=gamma, level="maintainer"
    )
    create_membership(
        subject_type="user", subject_id=outsider.id, target=gamma, level="maintainer"
    )

    assert effective_level(user.id, alpha) == "steward"
    assert effective_level(user.id, beta) == "maintainer"
    assert effective_level(user.id, gamma) is None

    create_membership(
        subject_type="user",
        subject_id=user.id,
        target=EVERY_SOURCE_TARGET,
        level="viewer",
    )
    assert effective_level(user.id, alpha) == "steward"
    assert effective_level(user.id, beta) == "maintainer"
    assert effective_level(user.id, gamma) == "viewer"


def test_role_ceiling_keeps_a_level_when_the_key_is_missing() -> None:
    role = _role("narrow", "Narrow", ["console:access"])
    user = _user("ada", "Ada", role.id)
    bare = _user("bare", "Bare", None)
    target = "src_alpha"
    assert effective_level(user.id, target) is None
    assert effective_permissions(user.id, target) == frozenset()

    create_membership(
        subject_type="user", subject_id=user.id, target=target, level="maintainer"
    )
    assert effective_level(user.id, target) == "maintainer"
    assert effective_permissions(user.id, target) == frozenset()

    stored = get_role_store().get_by_id(role.id)
    assert stored is not None
    stored.permissions = ["sources:read", "metadata:write"]
    get_role_store().save(stored)
    assert effective_level(user.id, target) == "maintainer"
    assert effective_permissions(user.id, target) == frozenset(
        {"sources:read", "metadata:write"}
    )

    create_membership(
        subject_type="user", subject_id=bare.id, target=target, level="viewer"
    )
    assert effective_level(bare.id, target) == "viewer"
    assert effective_permissions(bare.id, target) == frozenset()
    assert source_ids_for(bare.id, "sources:read") == NO_SOURCES


def test_source_ids_for_is_all_or_a_finite_set() -> None:
    role = _role(
        "analyst",
        "Analyst",
        ["sources:read", "metadata:read", "metadata:write", "jobs:run"],
    )
    user = _user("ada", "Ada", role.id)
    registered = _register_source("kept")
    create_membership(
        subject_type="user", subject_id=user.id, target="src_a", level="viewer"
    )
    create_membership(
        subject_type="user", subject_id=user.id, target="src_b", level="steward"
    )

    assert source_ids_for(user.id, "sources:read") == SourceIdSet(
        all_sources=False, source_ids=frozenset({"src_a", "src_b"})
    )
    assert source_ids_for(user.id, "metadata:write") == SourceIdSet(
        all_sources=False, source_ids=frozenset({"src_b"})
    )
    assert source_ids_for(user.id, "jobs:run") == NO_SOURCES
    assert source_ids_for(user.id, "catalog:sample") == NO_SOURCES
    assert source_ids_for(user.id, "query:run") == NO_SOURCES
    assert source_ids_for(user.id, "sources:write") == NO_SOURCES
    assert source_ids_for(user.id, "channel:read") == NO_SOURCES
    assert source_ids_for(user.id, "sources:access_manage") == NO_SOURCES
    assert NO_SOURCES != ALL_SOURCES
    assert "src_a" not in {item.source_id for item in explain_user(user.id)}

    create_membership(
        subject_type="user",
        subject_id=user.id,
        target=EVERY_SOURCE_TARGET,
        level="maintainer",
    )
    assert source_ids_for(user.id, "sources:read") == ALL_SOURCES
    assert source_ids_for(user.id, "jobs:run") == ALL_SOURCES
    assert registered not in source_ids_for(user.id, "sources:read").source_ids
    assert source_ids_for(user.id, "sources:write") == NO_SOURCES
    assert source_ids_for(user.id, "catalog:sample") == NO_SOURCES
    assert source_ids_for(user.id, "channel:read") == NO_SOURCES
    assert source_ids_for("user_missing", "sources:read") == NO_SOURCES


def test_super_admin_is_maintainer_without_a_stored_row() -> None:
    role = _role("super_admin", "Super Admin", [])
    user = _user("root", "Root", role.id)
    alpha = _register_source("alpha")
    beta = _register_source("beta")

    assert list_memberships() == ()
    assert effective_level(user.id, alpha) == "maintainer"
    assert effective_level(user.id, "src_unregistered") == "maintainer"
    assert effective_permissions(user.id, alpha) == MAINTAINER_KEYS
    assert source_ids_for(user.id, "sources:read") == ALL_SOURCES
    assert source_ids_for(user.id, "jobs:run") == ALL_SOURCES
    assert source_ids_for(user.id, "channel:read") == NO_SOURCES
    assert source_ids_for(user.id, "sources:access_manage") == NO_SOURCES

    explained = {item.source_id: item for item in explain_user(user.id)}
    assert set(explained) == {alpha, beta}
    for source_id in (alpha, beta):
        assert explained[source_id].level == "maintainer"
        assert len(explained[source_id].contributions) == 1
        contribution = explained[source_id].contributions[0]
        assert contribution.kind == "identity"
        assert contribution.subject_name == "Super Admin"
        assert contribution.level == "maintainer"
        assert contribution.membership_id is None

    direct = create_membership(
        subject_type="user", subject_id=user.id, target=alpha, level="viewer"
    )
    level, kinds = _kinds(user.id, alpha)
    assert level == "maintainer"
    assert ("identity", "Super Admin", "maintainer", None) in kinds
    assert ("direct", "Root", "viewer", direct.id) in kinds

    get_role_store().delete(role.id)
    assert effective_level(user.id, alpha) == "viewer"
    assert effective_permissions(user.id, alpha) == frozenset()
    assert source_ids_for(user.id, "sources:read") == NO_SOURCES


def test_unresolved_subject_grants_nothing_and_stays_listed() -> None:
    role = _role("analyst", "Analyst", sorted(MAINTAINER_KEYS))
    user = _user("ada", "Ada", role.id)
    target = _register_source("alpha")
    created = create_membership(
        subject_type="role", subject_id=role.id, target=target, level="maintainer"
    )
    assert effective_level(user.id, target) == "maintainer"
    assert {item.source_id for item in explain_user(user.id)} == {target}
    get_role_store().delete(role.id)
    assert effective_level(user.id, target) is None
    assert effective_permissions(user.id, target) == frozenset()
    listed = list_memberships(target=target)
    assert len(listed) == 1
    assert listed[0].id == created.id
    assert listed[0].subject_type == "role"
    assert listed[0].subject_id == role.id
    assert listed[0].level == "maintainer"
    assert listed[0].subject_name is None
    assert explain_user(user.id) == ()

    holder = _role("holder", "Holder", sorted(MAINTAINER_KEYS))
    member = _user("bea", "Bea", holder.id)
    group = create_group(
        key="warehouse",
        name="Warehouse",
        description=None,
        actor_user_id=member.id,
        actor_token_id=None,
    )
    add_member(group.id, member.id, actor_user_id=member.id, actor_token_id=None)
    group_row = create_membership(
        subject_type="group",
        subject_id=group.id,
        target="src_beta",
        level="steward",
    )
    assert effective_level(member.id, "src_beta") == "steward"
    delete_group(group.id, actor_user_id=member.id, actor_token_id=None)
    assert effective_level(member.id, "src_beta") is None
    listed_group = list_memberships(target="src_beta")
    assert [row.id for row in listed_group] == [group_row.id]
    assert listed_group[0].subject_name is None


def test_group_membership_changes_apply_on_the_next_call() -> None:
    role = _role("analyst", "Analyst", sorted(MAINTAINER_KEYS))
    user = _user("ada", "Ada", role.id)
    group = create_group(
        key="warehouse",
        name="Warehouse",
        description=None,
        actor_user_id=user.id,
        actor_token_id=None,
    )
    target = "src_alpha"
    create_membership(
        subject_type="group", subject_id=group.id, target=target, level="steward"
    )
    assert effective_level(user.id, target) is None
    add_member(group.id, user.id, actor_user_id=user.id, actor_token_id=None)
    assert effective_level(user.id, target) == "steward"
    remove_member(group.id, user.id, actor_user_id=user.id, actor_token_id=None)
    assert effective_level(user.id, target) is None


def test_disabled_user_keeps_the_level() -> None:
    role = _role("analyst", "Analyst", sorted(VIEWER_KEYS))
    user = _user("ada", "Ada", role.id, status="disabled")
    target = "src_alpha"
    create_membership(
        subject_type="user", subject_id=user.id, target=target, level="viewer"
    )
    assert effective_level(user.id, target) == "viewer"
    assert effective_permissions(user.id, target) == VIEWER_KEYS


def test_create_rejects_unknown_subject_level_and_duplicate() -> None:
    role = _role("analyst", "Analyst", sorted(VIEWER_KEYS))
    user = _user("ada", "Ada", role.id)
    created = create_membership(
        subject_type="user", subject_id=user.id, target="src_alpha", level="viewer"
    )

    with pytest.raises(SourceMembershipSubjectUnknown) as unknown_user:
        create_membership(
            subject_type="user",
            subject_id="user_missing",
            target="src_beta",
            level="viewer",
        )
    assert unknown_user.value.code == "SOURCE_MEMBERSHIP_SUBJECT_UNKNOWN"
    assert unknown_user.value.http_status == 422

    with pytest.raises(SourceMembershipSubjectUnknown) as unknown_role:
        create_membership(
            subject_type="role",
            subject_id="role_missing",
            target="src_beta",
            level="viewer",
        )
    assert unknown_role.value.code == "SOURCE_MEMBERSHIP_SUBJECT_UNKNOWN"

    with pytest.raises(SourceMembershipSubjectUnknown) as unknown_group:
        create_membership(
            subject_type="group",
            subject_id="grp_missing",
            target="src_beta",
            level="viewer",
        )
    assert unknown_group.value.code == "SOURCE_MEMBERSHIP_SUBJECT_UNKNOWN"

    with pytest.raises(SourceMembershipSubjectUnknown):
        create_membership(
            subject_type="team",
            subject_id=user.id,
            target="src_beta",
            level="viewer",
        )

    with pytest.raises(SourceMembershipLevelUnknown) as unknown_level:
        create_membership(
            subject_type="user",
            subject_id=user.id,
            target="src_beta",
            level="owner",
        )
    assert unknown_level.value.code == "SOURCE_MEMBERSHIP_LEVEL_UNKNOWN"
    assert unknown_level.value.http_status == 422

    with pytest.raises(SourceMembershipDuplicate) as duplicate:
        create_membership(
            subject_type="user",
            subject_id=user.id,
            target="src_alpha",
            level="steward",
        )
    assert duplicate.value.code == "SOURCE_MEMBERSHIP_DUPLICATE"
    assert duplicate.value.http_status == 409

    assert [row.id for row in list_memberships()] == [created.id]
    second = create_membership(
        subject_type="role",
        subject_id=role.id,
        target="src_alpha",
        level="steward",
    )
    assert {row.id for row in list_memberships()} == {created.id, second.id}


def test_change_level_and_delete_operate_on_one_row() -> None:
    role = _role("analyst", "Analyst", sorted(MAINTAINER_KEYS))
    user = _user("ada", "Ada", role.id)
    first = create_membership(
        subject_type="user", subject_id=user.id, target="src_alpha", level="viewer"
    )
    second = create_membership(
        subject_type="user", subject_id=user.id, target="src_beta", level="viewer"
    )
    updated = change_level(first.id, "maintainer")
    assert updated is not None
    assert updated.level == "maintainer"
    assert effective_level(user.id, "src_alpha") == "maintainer"
    assert effective_level(user.id, "src_beta") == "viewer"

    with pytest.raises(SourceMembershipLevelUnknown):
        change_level(second.id, "owner")
    assert effective_level(user.id, "src_beta") == "viewer"
    assert change_level("smb_missing", "steward") is None
    assert delete_membership("smb_missing") is False

    assert delete_membership(first.id) is True
    assert effective_level(user.id, "src_alpha") is None
    assert effective_level(user.id, "src_beta") == "viewer"
    assert [row.id for row in list_memberships()] == [second.id]


def test_delete_for_source_leaves_every_source_rows() -> None:
    role = _role("analyst", "Analyst", sorted(MAINTAINER_KEYS))
    user = _user("ada", "Ada", role.id)
    on_alpha = create_membership(
        subject_type="user", subject_id=user.id, target="src_alpha", level="viewer"
    )
    on_beta = create_membership(
        subject_type="user", subject_id=user.id, target="src_beta", level="steward"
    )
    every = create_membership(
        subject_type="user",
        subject_id=user.id,
        target=EVERY_SOURCE_TARGET,
        level="viewer",
    )
    delete_for_source("src_alpha")
    remaining = {row.id for row in list_memberships()}
    assert on_alpha.id not in remaining
    assert remaining == {on_beta.id, every.id}
    delete_for_source(EVERY_SOURCE_TARGET)
    assert {row.id for row in list_memberships()} == {on_beta.id, every.id}


def test_explain_user_names_reached_sources_and_paths() -> None:
    role = _role("analyst", "Analyst", sorted(MAINTAINER_KEYS))
    user = _user("ada", "Ada", role.id)
    group = create_group(
        key="warehouse",
        name="Warehouse",
        description=None,
        actor_user_id=user.id,
        actor_token_id=None,
    )
    add_member(group.id, user.id, actor_user_id=user.id, actor_token_id=None)
    alpha = _register_source("alpha")
    beta = _register_source("beta")
    gamma = _register_source("gamma")

    direct = create_membership(
        subject_type="user", subject_id=user.id, target=alpha, level="viewer"
    )
    grouped = create_membership(
        subject_type="group", subject_id=group.id, target=alpha, level="steward"
    )
    by_role = create_membership(
        subject_type="role", subject_id=role.id, target=beta, level="maintainer"
    )
    assert {item.source_id for item in explain_user(user.id)} == {alpha, beta}
    alpha_level, alpha_kinds = _kinds(user.id, alpha)
    assert alpha_level == "steward"
    assert alpha_kinds == {
        ("direct", "Ada", "viewer", direct.id),
        ("group", "Warehouse", "steward", grouped.id),
    }
    beta_level, beta_kinds = _kinds(user.id, beta)
    assert beta_level == "maintainer"
    assert beta_kinds == {("role", "Analyst", "maintainer", by_role.id)}

    every = create_membership(
        subject_type="user",
        subject_id=user.id,
        target=EVERY_SOURCE_TARGET,
        level="viewer",
    )
    assert {item.source_id for item in explain_user(user.id)} == {alpha, beta, gamma}
    gamma_level, gamma_kinds = _kinds(user.id, gamma)
    assert gamma_level == "viewer"
    assert gamma_kinds == {("every", "Ada", "viewer", every.id)}
    _alpha_level, alpha_after = _kinds(user.id, alpha)
    assert ("every", "Ada", "viewer", every.id) in alpha_after
    assert explain_user("user_missing") == ()


def test_memory_writes_ignore_the_caller_session() -> None:
    role = _role("analyst", "Analyst", sorted(VIEWER_KEYS))
    user = _user("ada", "Ada", role.id)
    sentinel = object()
    created = create_membership_on(
        sentinel,
        subject_type="user",
        subject_id=user.id,
        target="src_alpha",
        level="viewer",
    )
    assert effective_level(user.id, "src_alpha") == "viewer"
    change_level_on(None, created.id, "steward")
    assert effective_level(user.id, "src_alpha") == "steward"
    kept = create_membership_on(
        None,
        subject_type="user",
        subject_id=user.id,
        target="src_beta",
        level="viewer",
    )
    delete_for_source_on(sentinel, "src_alpha")
    assert effective_level(user.id, "src_alpha") is None
    assert delete_membership_on(sentinel, kept.id) is True
    assert list_memberships() == ()


def test_sources_access_manage_is_a_granting_catalog_key() -> None:
    assert PERMISSION_DESCRIPTIONS["sources:access_manage"] == (
        "Manage Source memberships and Source access levels"
    )
    assert "sources:access_manage" in ALL_PERMISSIONS
    assert "sources:access_manage" in GRANTING_PERMISSIONS
    assert "sources:access_manage" not in OPERATOR_DEFAULT_PERMISSIONS
    assert list(OPERATOR_DEFAULT_PERMISSIONS) == ["console:access", "dashboard:read"]

    ceiling = RoleRecord(
        id="role_ceiling",
        key="ceiling",
        name="Ceiling",
        permissions=[
            "sources:read",
            "sources:write",
            "metadata:read",
            "metadata:write",
        ],
    )
    assert "sources:access_manage" not in role_permissions(ceiling)
    super_admin = RoleRecord(
        id="role_super_admin",
        key="super_admin",
        name="Super Admin",
        permissions=[],
    )
    assert "sources:access_manage" in role_permissions(super_admin)

    granting = RoleRecord(
        id="role_granting",
        key="access_admin",
        name="Access Admin",
        permissions=["sources:access_manage"],
    )
    with pytest.raises(ProviderDefaultRoleForbidden):
        validate_default_role(granting)
    operator = RoleRecord(
        id="role_operator",
        key="operator",
        name="Operator",
        permissions=list(OPERATOR_DEFAULT_PERMISSIONS),
    )
    validate_default_role(operator)

    seed_roles(get_role_store())
    seeded = get_role_store().get_by_key("operator")
    assert seeded is not None
    assert seeded.permissions == ["console:access", "dashboard:read"]
