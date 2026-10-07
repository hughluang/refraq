"""PR 7 data-plane: default deny, shape errors, write attribution, seed, creator grant."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

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
from backend.admin.user_store import get_user_store  # noqa: E402
from backend.entity.access.seed import ensure_creator_grant  # noqa: E402
from backend.tests.entity_access_oracle import (  # noqa: E402
    prepare_legacy_entity,
    seed_entity_entitlements,
)
from backend.entity.access.store import get_access_store  # noqa: E402
from backend.entity.data.service import schema_for  # noqa: E402
from backend.entity.data.values import encode_inbound_map  # noqa: E402
from backend.entity.errors import EntityRowInvalid  # noqa: E402
from backend.entity.ids import new_entity_id, new_version_id  # noqa: E402
from backend.entity.lifecycle import PUBLISHED, UNPUBLISHED  # noqa: E402
from backend.entity.records import (  # noqa: E402
    AttributeRecord,
    BusinessEntityRecord,
    EntityVersionRecord,
    attribute_to_dict,
)
from backend.entity.store import get_entity_store  # noqa: E402
from backend.main import app  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    roles = get_role_store()
    seed_roles(roles)
    admin = roles.get_by_key("super_admin")
    assert admin is not None
    get_user_store().create_user(
        account="admin",
        display_name="Admin",
        password_hash=hash_password("secret"),
        role_id=admin.id,
        status="active",
    )
    reader = create_role(
        roles,
        key="data_reader",
        name="Data reader",
        permissions=["console:access", "entity:data_read", "entity:read"],
    )
    get_user_store().create_user(
        account="reader",
        display_name="Reader",
        password_hash=hash_password("secret"),
        role_id=reader.id,
        status="active",
    )
    with TestClient(app) as test_client:
        yield test_client


def _entity(*, published: bool = True) -> str:
    now = datetime.now(timezone.utc)
    attrs = [
        AttributeRecord(name="sku", type="string", max_length=32, unique=True),
        AttributeRecord(name="note", type="text"),
    ]
    entity = BusinessEntityRecord(
        id=new_entity_id(),
        table_name="material",
        name="Material",
        description="",
        deprecated_at=None,
        created_at=now,
        updated_at=now,
    )
    version = EntityVersionRecord(
        id=new_version_id(),
        entity_id=entity.id,
        version=1,
        attributes=list(attrs),
        materialized_attributes=[attribute_to_dict(item) for item in attrs]
        if published
        else [],
        publish_status=PUBLISHED if published else UNPUBLISHED,
        latest_reconcile_job_id=None,
        created_at=now,
        updated_at=now,
    )
    get_entity_store().create_entity(entity, version)
    return entity.id


def _login(client: TestClient, account: str) -> None:
    response = client.post(
        "/auth/login", json={"account": account, "password": "secret"}
    )
    assert response.status_code == 200, response.text


def test_missing_and_ungranted_table_share_404(client: TestClient) -> None:
    _entity()
    _login(client, "reader")
    missing = client.post("/entities/missing_table/schema", json={})
    hidden = client.post("/entities/material/schema", json={})
    assert missing.status_code == 404
    assert hidden.status_code == 404
    assert missing.json()["code"] == hidden.json()["code"] == "ENTITY_NOT_FOUND"
    assert hidden.json()["detail"] == (
        "Business Entity with table_name 'material' was not found"
    )


def test_malformed_body_is_401_before_parse(client: TestClient) -> None:
    response = client.post(
        "/entities/material/schema",
        content=b"not-json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_seed_keeps_entitled_role_schema(client: TestClient) -> None:
    entity_id = _entity()
    assert seed_entity_entitlements(entity_id) is True
    prepare_legacy_entity(entity_id)
    _login(client, "admin")
    response = client.post("/entities/material/schema", json={})
    assert response.status_code == 200, response.text
    names = [item["name"] for item in response.json()["attributes"]]
    assert names == ["sku", "note"]
    grants = get_access_store().grants(entity_id)
    assert any(item.subject_type == "role" and "read" in item.actions for item in grants)
    assert any("write" in item.actions for item in grants)


def test_hidden_column_matches_unknown_field(client: TestClient) -> None:
    entity_id = _entity()
    prepare_legacy_entity(entity_id)
    user = get_user_store().get_by_account("reader")
    assert user is not None
    # Reader role was entitled by the seed (data_read) but only to clear columns
    # that exist. A name that is not on the head and a withheld name share the
    # unknown-attribute error once the shape is the allow-list.
    from backend.entity.data.head import HeadTarget, resolve_head

    target = resolve_head("material", for_write=False)
    shaped = type(target)(
        entity=target.entity,
        head=target.head,
        attributes=tuple(attr for attr in target.attributes if attr.name == "sku"),
        physical_table=target.physical_table,
        qualified_table=target.qualified_table,
        writable=target.writable,
    )
    with pytest.raises(EntityRowInvalid) as hidden:
        encode_inbound_map({"note": "x"}, shaped, partial=True)
    with pytest.raises(EntityRowInvalid) as unknown:
        encode_inbound_map({"nope": "x"}, shaped, partial=True)
    assert type(hidden.value) is type(unknown.value)
    assert hidden.value.code == unknown.value.code == "ENTITY_ROW_INVALID"
    assert "Unknown attribute" in hidden.value.message
    assert "Unknown attribute" in unknown.value.message
    schema = schema_for("material", {}, user)
    assert [item["name"] for item in schema["attributes"]] == ["sku", "note"]


def test_creator_grant_on_first_publish_only() -> None:
    entity_id = _entity(published=False)
    user = get_user_store().create_user(
        account="publisher",
        display_name="Publisher",
        password_hash=hash_password("secret"),
        role_id=None,
        status="active",
    )
    attrs = [
        AttributeRecord(
            name="sku",
            type="string",
            max_length=32,
            attribute_id="att_sku",
        )
    ]
    grant_id = ensure_creator_grant(entity_id, user.id, attrs)
    assert grant_id is not None
    again = ensure_creator_grant(entity_id, user.id, attrs)
    assert again is None
    grant = get_access_store().grant(grant_id)
    assert grant is not None
    assert grant.subject_type == "user"
    assert grant.subject_id == user.id
    assert grant.row_rule is None
    assert set(grant.actions) == {"read", "export", "write"}


def test_first_publish_retry_realigns_the_creator_profile() -> None:
    entity_id = _entity(published=False)
    user = get_user_store().create_user(
        account="retry_publisher",
        display_name="Publisher",
        password_hash=hash_password("secret"),
        role_id=None,
        status="active",
    )
    first = [AttributeRecord(name="sku", type="string", max_length=32, attribute_id="att_a")]
    retry = [AttributeRecord(name="sku", type="string", max_length=32, attribute_id="att_b")]
    grant_id = ensure_creator_grant(entity_id, user.id, first)
    assert grant_id is not None
    revision = get_access_store().revision(entity_id)
    assert ensure_creator_grant(entity_id, user.id, retry) is None
    grant = get_access_store().grant(grant_id)
    assert grant is not None
    profile = get_access_store().profile(grant.profile_id)
    assert profile is not None
    assert profile.columns == [{"attribute_id": "att_b", "level": "clear"}]
    assert get_access_store().revision(entity_id) == revision + 1


def test_definition_hides_physical_name_without_entity_write(client: TestClient) -> None:
    entity_id = _entity()
    prepare_legacy_entity(entity_id)
    _login(client, "reader")
    listed = client.get("/entities")
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] == 1
    assert body["items"][0]["current_version"]["table_name"] is None
    _login(client, "admin")
    listed = client.get("/entities")
    assert listed.json()["items"][0]["current_version"]["table_name"]


def test_write_spanning_two_grants_is_denied() -> None:
    from backend.entity.access.compiler import Policy, compile_policy, subject_outcome
    from backend.entity.access.enforce import DataAccess, require_write_grant
    from backend.entity.access.errors import EntityAccessWriteDenied
    from backend.entity.access.facts import AttrFact, GrantSpec, Person, ProfileSpec
    from backend.entity.data.head import HeadTarget

    now = datetime.now(timezone.utc)
    sku = AttrFact("att_sku", "sku", "string")
    note = AttrFact("att_note", "note", "text")
    person = Person("user_1", "role_1", ())
    grants = (
        GrantSpec("g1", "user", "user_1", "p_sku", None, frozenset({"read", "write"}), "active", None),
        GrantSpec("g2", "user", "user_1", "p_note", None, frozenset({"read", "write"}), "active", None),
    )
    policy = Policy(
        entity_id="ent_1",
        table_name="material",
        revision=1,
        source_sql='entity_data."material"',
        head_version_id="ver",
        attributes=(sku, note),
        ladders={},
        profiles=(
            ProfileSpec("p_sku", "sku", (("att_sku", "clear"),)),
            ProfileSpec("p_note", "note", (("att_note", "clear"),)),
        ),
        grants=grants,
        restrictions=(),
        people=(person,),
        subject_attrs={},
        subject_values={},
        cap=64,
        existing_combos=frozenset(),
        now=now,
    )
    compiled = compile_policy(policy)
    outcome = subject_outcome(compiled, policy, person, action="write", narrow=None)
    user = get_user_store().get_by_account("admin")
    access = DataAccess(
        user=user,  # type: ignore[arg-type]
        head=None,  # type: ignore[arg-type]
        target=HeadTarget(
            entity=BusinessEntityRecord(
                id="ent_1",
                table_name="material",
                name="Material",
                description="",
                deprecated_at=None,
                created_at=now,
                updated_at=now,
            ),
            head=EntityVersionRecord(
                id="ver",
                entity_id="ent_1",
                version=1,
                attributes=[],
                materialized_attributes=[],
                publish_status=PUBLISHED,
                latest_reconcile_job_id=None,
                created_at=now,
                updated_at=now,
            ),
            attributes=(),
            physical_table="material__v1",
            qualified_table='entity_data."material__v1"',
            writable=True,
        ),
        full=HeadTarget(
            entity=BusinessEntityRecord(
                id="ent_1",
                table_name="material",
                name="Material",
                description="",
                deprecated_at=None,
                created_at=now,
                updated_at=now,
            ),
            head=EntityVersionRecord(
                id="ver",
                entity_id="ent_1",
                version=1,
                attributes=[],
                materialized_attributes=[],
                publish_status=PUBLISHED,
                latest_reconcile_job_id=None,
                created_at=now,
                updated_at=now,
            ),
            attributes=(),
            physical_table="material__v1",
            qualified_table='entity_data."material__v1"',
            writable=True,
        ),
        outcome=outcome,
        policy=policy,
        compiled=compiled,
        person=person,
        narrow=None,
        revision=1,
        action="write",
        started=0.0,
    )
    with pytest.raises(EntityAccessWriteDenied):
        require_write_grant(
            access,
            written={"sku", "note"},
            before=[{"row_id": 1, "sku": "A", "note": "n"}],
            after=[{"row_id": 1, "sku": "B", "note": "n"}],
        )


def test_conflict_detail_has_no_other_row() -> None:
    from backend.entity.errors import EntityRowConflict

    error = EntityRowConflict()
    assert error.http_status == 409
    assert "row_id" not in error.message


def test_access_log_retention_deletes_old_rows() -> None:
    from backend.entity.access.records import AccessLogRecord
    from backend.entity.ids import new_access_log_id
    from backend.entity.tasks import purge_expired_access_logs

    old = datetime.now(timezone.utc) - timedelta(days=400)
    get_access_store().append_log(
        AccessLogRecord(
            id=new_access_log_id(),
            created_at=old,
            user_id="user_1",
            pat_id=None,
            request_id=None,
            entity_id="ent_1",
            verb="get",
            effective_grant_ids=[],
            narrowing=None,
            view_name=None,
            policy_revision=1,
            row_count=0,
            outcome_code="ok",
            preview_subject_user_id=None,
            duration_ms=3,
        )
    )
    assert purge_expired_access_logs() == 1
    assert get_access_store().logs_for_entity("ent_1") == []
