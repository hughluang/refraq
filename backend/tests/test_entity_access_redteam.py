"""Red-team and cross-channel checks that do not need a live database.

PostgreSQL cases stay in ``test_entity_access_views_pg.py`` and skip when the
server rejects the documented password. This module does not start Docker.
"""

from __future__ import annotations

import os
import re
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone

import pytest

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.pop("ENTITY_DATABASE_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.roles import create_role, seed_roles  # noqa: E402
from backend.admin.role_store import get_role_store  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import UserRecord, get_user_store  # noqa: E402
from backend.entity.access.compiler import (  # noqa: E402
    compile_policy,
    render_shape,
    subject_outcome,
)
from backend.entity.access.context import (  # noqa: E402
    KeyRing,
    SigningKey,
    issue_context,
    sign_payload,
)
from backend.entity.access.dsl import rule_sql  # noqa: E402
from backend.entity.access.errors import EntityAccessPending  # noqa: E402
from backend.entity.access.plan import Head  # noqa: E402
from backend.entity.access.seed import (  # noqa: E402
    ALL_CLEAR_KEY,
    ensure_creator_grant,
)
from backend.entity.access.service import (  # noqa: E402
    _schema,
    create_grant,
    create_profile,
)
from backend.entity.access.store import get_access_store  # noqa: E402
from backend.entity.bootstrap import role_statements, schema_statements  # noqa: E402
from backend.entity.data.filters import compile_filters  # noqa: E402
from backend.entity.data.head import HeadTarget  # noqa: E402
from backend.entity.data.service import (  # noqa: E402
    _resolve_fields,
    get_row,
    query_rows,
    upsert_one,
)
from backend.entity.data import sql as data_sql  # noqa: E402
from backend.entity.ddl import (  # noqa: E402
    READER_ROLE,
    table_security_statements,
)
from backend.entity.errors import (  # noqa: E402
    EntityNotFound,
    EntityRequestInvalid,
    EntityRowConflict,
    EntityRowInvalid,
    EntityRowNotFound,
)
from backend.entity import service as entity_service  # noqa: E402
from backend.entity.access.enforce import begin_data  # noqa: E402
from backend.entity.ids import new_entity_id, new_version_id  # noqa: E402
from backend.entity.lifecycle import PUBLISHED, UNPUBLISHED  # noqa: E402
from backend.entity.parameters import ENTITY_PARAMETER_SPECS  # noqa: E402
from backend.entity.records import (  # noqa: E402
    AttributeRecord,
    BusinessEntityRecord,
    EntityVersionRecord,
    attribute_to_dict,
)
from backend.entity.store import get_entity_store  # noqa: E402
from backend.admin.system_parameters import (  # noqa: E402
    is_registry_frozen,
    register_parameters,
)
from backend.tests.entity_access_oracle import (  # noqa: E402
    prepare_legacy_entity,
    project_subject,
    require_subject_view,
    seed_entity_entitlements,
    verify_token,
)
from backend.tests.test_entity_access_compiler import (  # noqa: E402
    _customer_policy,
    _rows,
)

NOW = datetime(2026, 10, 7, tzinfo=timezone.utc)
_ALIAS = re.compile(r'AS "([^"]+)"')


@pytest.fixture(autouse=True)
def _entity_parameters() -> None:
    if not is_registry_frozen():
        register_parameters(ENTITY_PARAMETER_SPECS, group_order=("entity_access",))


def _aliases(sql: str) -> set[str]:
    return set(_ALIAS.findall(sql))


def _shape(compiled, profile_id: str):
    return next(
        shape
        for shape in compiled.shapes
        if shape.action == "read" and shape.profile_ids == (profile_id,)
    )


def test_forged_and_expired_context_activate_no_grants() -> None:
    policy, people = _customer_policy()
    compiled = compile_policy(policy)
    ring = KeyRing((SigningKey("k1", b"k" * 32),))
    token = issue_context(
        policy, compiled, people["liu"], ring, action="read", now=NOW
    )
    keys = ring.by_kid()
    assert verify_token(token, keys, now=NOW) is not None
    forged = token[:-1] + ("0" if token[-1] != "0" else "1")
    assert verify_token(forged, keys, now=NOW) is None
    payload = verify_token(token, keys, now=NOW)
    assert payload is not None
    payload["grants"] = ["g_fin_audit", "g_not_mine"]
    resigned_body = sign_payload(payload, b"other-secret")
    assert verify_token(resigned_body, keys, now=NOW) is None
    expired = sign_payload(
        {**payload, "grants": ["g_sales_region"], "exp": int(NOW.timestamp()) - 1, "kid": "k1"},
        ring.current().secret,
    )
    assert verify_token(expired, keys, now=NOW) is None


def test_reader_role_sql_is_not_a_reset_role_path() -> None:
    statements = role_statements(
        owner_password="owner-secret",
        reader_password="reader-secret",
        existing=frozenset(),
    )
    reader = next(line for line in statements if f"ROLE {READER_ROLE}" in line or f"ROLE \"{READER_ROLE}\"" in line)
    assert "NOSUPERUSER" in reader
    assert "NOINHERIT" in reader
    assert "NOBYPASSRLS" in reader
    set_grants = [line for line in statements if "SET TRUE" in line]
    assert set_grants
    assert all(READER_ROLE not in line for line in set_grants)
    schema = "\n".join(schema_statements())
    assert f'REVOKE ALL ON SCHEMA "entity_data" FROM "{READER_ROLE}"' in schema
    table = "\n".join(table_security_statements("entity_data", "customer__v1__old"))
    assert f'REVOKE ALL ON "entity_data"."customer__v1__old" FROM "{READER_ROLE}"' in table
    assert f'GRANT SELECT ON "entity_data"."customer__v1__old" TO "{READER_ROLE}"' not in table


def test_reader_sql_uses_the_profile_view_not_physical_tables() -> None:
    policy, _people = _customer_policy()
    compiled = compile_policy(policy)
    sales = _shape(compiled, "eap_sales")
    finance = _shape(compiled, "eap_finance")
    sales_sql = render_shape(sales, policy, acl=True)
    finance_sql = render_shape(finance, policy, acl=True)
    assert sales_sql.startswith('CREATE VIEW "entity_access".')
    assert "customer__v2__" not in sales_sql
    assert "customer__v3__9f1c2a7b4d6e8f00" in sales_sql
    assert 'GRANT SELECT ON "entity_access".' in sales_sql
    assert "row_to_json" not in sales_sql
    assert "t.*" not in sales_sql
    assert "credit_limit" not in _aliases(sales_sql)
    assert "acl.grant_active('g_sales_region')" in sales_sql
    assert "acl.grant_active('g_fin_audit')" not in sales_sql
    assert "acl.grant_active('g_fin_audit')" in finance_sql
    assert "acl.grant_active('g_fin_user')" in finance_sql
    assert "credit_limit" in _aliases(finance_sql)
    assert "acl.rev_ok('ent_customer', 42)" in sales_sql
    assert "acl.rev_ok('ent_customer', 99)" not in sales_sql
    assert "security_barrier = true" in sales_sql


def test_or_and_not_compile_into_sql() -> None:
    policy, _people = _customer_policy()
    attrs = {item.attribute_id: item for item in policy.attributes}
    sql = rule_sql(
        {
            "or": [
                {"eq": {"attr": "att_region", "value": "EAST"}},
                {"not": {"eq": {"attr": "att_region", "value": "TEST"}}},
            ]
        },
        attrs,
        alias="t",
        acl=True,
    )
    assert " OR " in sql
    assert "(NOT " in sql
    assert "att_region" not in sql or '"region"' in sql


def test_customer_channels_share_one_shape() -> None:
    policy, people = _customer_policy()
    compiled = compile_policy(policy)
    outcome = subject_outcome(
        compiled, policy, people["liu"], action="read", narrow=None
    )
    assert outcome.shape is not None
    sql = render_shape(outcome.shape, policy, acl=True)
    aliases = _aliases(sql)
    names = [column.attr.name for column in outcome.shape.columns]
    assert set(names) <= aliases
    assert "id_card_no" in names and "credit_limit" in names and "mobile" in names
    preview = _schema(
        Head("ent_customer", "customer", None, None, (), (), None, ""),
        compiled,
        policy,
        people["liu"],
        None,
        outcome,
        policy.revision,
    )
    assert [item["name"] for item in preview["attributes"]] == names
    projected = project_subject(compiled, policy, people["liu"], _rows())
    assert projected.rows is not None
    cell_keys = set(projected.rows[0]) - {"__withheld", "__sources"}
    assert cell_keys == set(names) | {"row_id"}
    sales = _shape(compiled, "eap_sales")
    target = _shape_target(sales)
    kept = compile_filters(
        {"field": "name", "op": "eq", "value": "Zhang"}, target
    )
    assert kept is not None and '"name"' in kept.sql
    hidden = _unknown_filter(target, "credit_limit")
    missing = _unknown_filter(target, "no_such_column")
    assert hidden.code == missing.code == "ENTITY_ROW_INVALID"
    assert hidden.message == "Unknown filter field 'credit_limit'"
    assert missing.message == "Unknown filter field 'no_such_column'"
    hidden_field = _unknown_field(target, "credit_limit")
    missing_field = _unknown_field(target, "no_such_column")
    assert hidden_field.code == missing_field.code == "ENTITY_ROW_INVALID"
    assert hidden_field.message == "Unknown field 'credit_limit'"
    assert missing_field.message == "Unknown field 'no_such_column'"


def test_sort_is_rejected_before_a_hidden_column_can_order() -> None:
    user, table = _seeded_reader()
    with pytest.raises(EntityRequestInvalid, match="unknown top-level key"):
        query_rows(table, {"sort": [{"field": "note", "dir": "asc"}]}, user)


def test_definition_rights_do_not_bypass_data_denial() -> None:
    user, table = _designer_without_data_grant()
    assert entity_service._sees_every_definition(user) is True
    missing = _not_found("missing_table_redteam", user)
    hidden = _not_found(table, user)
    assert missing.code == hidden.code == "ENTITY_NOT_FOUND"
    assert hidden.http_status == 404
    assert table in hidden.message
    assert "row_id" not in hidden.message


def test_invisible_business_key_matches_missing_row(monkeypatch: pytest.MonkeyPatch) -> None:
    user, table = _seeded_reader(business_key=True)
    seen: list[str] = []

    class _Result:
        def one_or_none(self):
            return None

    class _Conn:
        def execute(self, statement, params=None):
            seen.append(str(statement))
            return _Result()

    @contextmanager
    def _open(ctx=None):
        yield _Conn()

    monkeypatch.setattr(data_sql, "entity_read_connection", _open)
    missing = _get_error(table, user, {"business_key": "absent"})
    invisible = _get_error(table, user, {"business_key": "held-by-hidden-row"})
    assert type(missing) is type(invisible) is EntityRowNotFound
    assert missing.code == invisible.code == "ENTITY_ROW_NOT_FOUND"
    assert missing.message == invisible.message == "Entity row not found"
    assert "held-by-hidden-row" not in missing.message
    assert seen
    assert all("entity_access" in sql for sql in seen)
    assert all("entity_data" not in sql for sql in seen)


def test_unique_conflict_names_no_other_row(monkeypatch: pytest.MonkeyPatch) -> None:
    user, table = _seeded_reader()
    secret = {"row_id": 99, "sku": "taken"}

    @contextmanager
    def _open():
        yield object()

    monkeypatch.setattr(data_sql, "entity_connection", _open)
    monkeypatch.setattr(data_sql, "select_by_column", lambda *args, **kwargs: dict(secret))
    monkeypatch.setattr(
        "backend.entity.data.service.row_visible", lambda access, row: False
    )
    with pytest.raises(EntityRowConflict) as caught:
        upsert_one(table, {"key": "sku", "values": {"sku": "taken"}}, user)
    message = caught.value.message
    assert caught.value.http_status == 409
    assert "99" not in message
    assert "taken" not in message
    assert "row_id" not in message


def test_creator_grant_and_legacy_seed_actions() -> None:
    entity_id, _table = _published(published=False)
    user = _user("publisher", role_id=None)
    attrs = [
        AttributeRecord(name="sku", type="string", max_length=32, attribute_id="att_sku")
    ]
    grant_id = ensure_creator_grant(entity_id, user.id, attrs)
    assert grant_id is not None
    profile = get_access_store().profile_by_key(entity_id, ALL_CLEAR_KEY)
    assert profile is not None
    grant = get_access_store().grant(grant_id)
    assert grant is not None and grant.profile_id == profile.id
    assert set(grant.actions) == {"read", "export", "write"}

    seeded_id, _seed_table = _published()
    roles = get_role_store()
    seed_roles(roles)
    suffix = uuid.uuid4().hex[:8]
    read_role = create_role(
        roles,
        key=f"rt_read_{suffix}",
        name="Read",
        permissions=["entity:data_read"],
    )
    write_role = create_role(
        roles,
        key=f"rt_write_{suffix}",
        name="Write",
        permissions=["entity:data_read", "entity:data_write"],
    )
    seed_entity_entitlements(seeded_id)
    grants = get_access_store().grants(seeded_id)
    read_grant = next(item for item in grants if item.subject_id == read_role.id)
    write_grant = next(item for item in grants if item.subject_id == write_role.id)
    assert read_grant.actions == ["read"]
    assert write_grant.actions == ["read", "write"]
    assert "export" not in write_grant.actions


def test_missing_combination_view_is_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.entity.access.jobs.dispatch_entity_job", lambda job: job.id
    )
    entity_id, _table = _published()
    user = _user("pending", role_id=None)
    created = create_profile(
        entity_id,
        key="sales",
        name="Sales",
        description=None,
        columns=[{"attribute_id": "att_sku", "level": "clear"}],
        actor_user_id=user.id,
        actor_token_id=None,
    )
    create_grant(
        entity_id,
        subject={"type": "user", "id": user.id},
        profile_id=created["profile"]["id"],
        row_rule=None,
        actions=["read"],
        status="active",
        valid_until=None,
        actor_user_id=user.id,
        actor_token_id=None,
    )
    with pytest.raises(EntityAccessPending) as caught:
        require_subject_view(entity_id, user.id)
    assert caught.value.http_status == 503
    assert caught.value.code == "ENTITY_ACCESS_PENDING"


def _unknown_filter(target: HeadTarget, field: str) -> EntityRowInvalid:
    with pytest.raises(EntityRowInvalid) as caught:
        compile_filters({"field": field, "op": "eq", "value": "x"}, target)
    return caught.value


def _unknown_field(target: HeadTarget, field: str) -> EntityRowInvalid:
    with pytest.raises(EntityRowInvalid) as caught:
        _resolve_fields([field], target)
    return caught.value


def _shape_target(shape) -> HeadTarget:
    now = NOW
    entity = BusinessEntityRecord(
        id="ent_customer",
        table_name="customer",
        name="Customer",
        description="",
        deprecated_at=None,
        created_at=now,
        updated_at=now,
    )
    version = EntityVersionRecord(
        id="ver_customer",
        entity_id=entity.id,
        version=3,
        attributes=[],
        materialized_attributes=[],
        publish_status=PUBLISHED,
        latest_reconcile_job_id=None,
        created_at=now,
        updated_at=now,
    )
    attributes = tuple(
        AttributeRecord(
            name=column.attr.name,
            type="string" if column.attr.type == "dictionary" else column.attr.type,
            attribute_id=column.attr.attribute_id,
            max_length=64,
        )
        for column in shape.columns
    )
    return HeadTarget(
        entity=entity,
        head=version,
        attributes=attributes,
        physical_table="customer__v3__9f1c2a7b4d6e8f00",
        qualified_table='entity_data."customer__v3__9f1c2a7b4d6e8f00"',
        writable=False,
        read_relation=f'"entity_access"."{shape.view_name}"',
    )


def _published(*, published: bool = True) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    table = f"rt_{uuid.uuid4().hex[:8]}"
    attr = AttributeRecord(
        name="sku",
        type="string",
        max_length=32,
        unique=True,
        attribute_id="att_sku",
    )
    entity = BusinessEntityRecord(
        id=new_entity_id(),
        table_name=table,
        name="Probe",
        description="",
        deprecated_at=None,
        created_at=now,
        updated_at=now,
    )
    stored = attribute_to_dict(attr)
    stored["attribute_id"] = "att_sku"
    version = EntityVersionRecord(
        id=new_version_id(),
        entity_id=entity.id,
        version=1,
        attributes=[attr],
        materialized_attributes=[stored] if published else [],
        publish_status=PUBLISHED if published else UNPUBLISHED,
        latest_reconcile_job_id=None,
        created_at=now,
        updated_at=now,
    )
    get_entity_store().create_entity(entity, version)
    return entity.id, table


def _user(prefix: str, role_id: str | None) -> UserRecord:
    return get_user_store().create_user(
        account=f"{prefix}_{uuid.uuid4().hex[:8]}",
        display_name=prefix,
        password_hash=hash_password("secret"),
        role_id=role_id,
        status="active",
    )


def _seeded_reader(*, business_key: bool = False) -> tuple[UserRecord, str]:
    roles = get_role_store()
    seed_roles(roles)
    admin_role = roles.get_by_key("super_admin")
    assert admin_role is not None
    entity_id, table = _published()
    if business_key:
        version = get_entity_store().list_all_versions(entity_id)[0]
        attr = replace(version.attributes[0], business_key=True)
        stored = attribute_to_dict(attr)
        stored["attribute_id"] = "att_sku"
        stored["business_key"] = True
        get_entity_store().save_version(
            EntityVersionRecord(
                id=version.id,
                entity_id=version.entity_id,
                version=version.version,
                attributes=[attr],
                materialized_attributes=[stored],
                publish_status=version.publish_status,
                latest_reconcile_job_id=version.latest_reconcile_job_id,
                created_at=version.created_at,
                updated_at=version.updated_at,
            )
        )
    prepare_legacy_entity(entity_id)
    return _user("admin", admin_role.id), table


def _designer_without_data_grant() -> tuple[UserRecord, str]:
    roles = get_role_store()
    seed_roles(roles)
    suffix = uuid.uuid4().hex[:8]
    role = create_role(
        roles,
        key=f"rt_design_{suffix}",
        name="Design",
        permissions=["entity:read", "entity:write"],
    )
    entity_id, table = _published()
    prepare_legacy_entity(entity_id)
    return _user("design", role.id), table


def _not_found(table: str, user: UserRecord) -> EntityNotFound:
    with pytest.raises(EntityNotFound) as caught:
        begin_data(table, user, {}, action="read", for_write=False)
    return caught.value


def _get_error(table: str, user: UserRecord, body: dict) -> EntityRowNotFound:
    with pytest.raises(EntityRowNotFound) as caught:
        get_row(table, body, user)
    return caught.value
