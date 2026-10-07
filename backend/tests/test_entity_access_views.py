"""Profile-view DDL, the revision fence, and signed-context issuance."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from backend.admin.security import hash_password
from backend.admin.system_parameters import is_registry_frozen, register_parameters
from backend.admin.subjects.service import add_member, create_group
from backend.admin.user_store import get_user_store
from backend.entity.access.compiler import Policy, compile_policy
from backend.entity.access.context import (
    KeyRing,
    SigningKey,
    install_signing_keys,
    issue_context,
    rotate_key,
    verify_token,
)
from backend.entity.access.errors import (
    EntityAccessCombinationLimit,
    EntityAccessPending,
)
from backend.entity.access.facts import (
    AttrFact,
    GrantSpec,
    Narrow,
    Person,
    ProfileSpec,
)
from backend.entity.access.records import ProfileRecord
from backend.entity.access.service import create_grant, create_profile, require_subject_view
from backend.entity.access.store import get_access_store
from backend.entity.access.views import profile_view_statements, rebuild_entity_views
from backend.entity.parameters import ENTITY_PARAMETER_SPECS
from backend.entity.ids import new_entity_id, new_version_id
from backend.entity.kinds import KIND_RECONCILE
from backend.entity.lifecycle import PUBLISHED, UNPUBLISHED
from backend.entity.records import (
    AttributeRecord,
    BusinessEntityRecord,
    EntityVersionRecord,
    attribute_to_dict,
)
from backend.entity.store import get_entity_store
from backend.entity.table_name import compose_physical_table_name
from backend.entity.table_port import (
    RecordingEntityTablePort,
    bind_entity_table_port,
    get_entity_table_port,
)
from backend.entity.tasks import run_job
from backend.jobs.store import create_queued_job, get_job_store
from backend.core.time import utc_now

NOW = datetime(2026, 10, 7, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _entity_parameters() -> None:
    if not is_registry_frozen():
        register_parameters(ENTITY_PARAMETER_SPECS, group_order=("entity_access",))


def _policy(*grants: GrantSpec, people: tuple[Person, ...] = ()) -> Policy:
    name = AttrFact("att_name", "name", "string", max_length=32)
    return Policy(
        entity_id="ent_customer",
        table_name="customer",
        revision=4,
        source_sql='entity_data."customer__v1__ver"',
        head_version_id="ver",
        attributes=(name,),
        ladders={},
        profiles=(
            ProfileSpec("eap_a", "a", (("att_name", "clear"),)),
            ProfileSpec("eap_b", "b", (("att_name", "clear"),)),
        ),
        grants=grants,
        restrictions=(),
        people=people,
        subject_attrs={},
        subject_values={},
        cap=64,
        existing_combos=frozenset(),
        now=NOW,
    )


def _grant(grant_id: str, profile_id: str, kind: str, subject_id: str) -> GrantSpec:
    return GrantSpec(
        grant_id,
        kind,  # type: ignore[arg-type]
        subject_id,
        profile_id,
        None,
        frozenset({"read"}),
        "active",
        None,
    )


def test_rule_literal_with_a_semicolon_stays_in_one_statement() -> None:
    person = Person("user_1", "role_1", ("grp_1",))
    literal = "a;\nGRANT SELECT ON x TO y;"
    grant = replace(
        _grant("eag_user", "eap_a", "user", "user_1"),
        row_rule={"eq": {"attr": "att_name", "value": literal}},
    )
    compiled = compile_policy(_policy(grant, people=(person,)))
    statements = profile_view_statements(compiled, [])
    views = len(compiled.bindings)
    assert len(statements) == views + 3 * views
    carrying = [item for item in statements if "GRANT SELECT ON x TO y" in item]
    assert carrying
    assert all(item.startswith("CREATE VIEW") for item in carrying)
    assert all("'a;\nGRANT SELECT ON x TO y;'" in item for item in carrying)


def test_profile_view_sql_drops_and_creates_and_fences_revision() -> None:
    person = Person("user_1", "role_1", ("grp_1",))
    compiled = compile_policy(
        _policy(_grant("eag_user", "eap_a", "user", "user_1"), people=(person,))
    )
    sql = compiled.bindings[0].sql
    assert "CREATE OR REPLACE" not in sql
    assert "security_barrier = true" in sql
    assert "acl.rev_ok('ent_customer', 4)" in sql
    assert hashlib.sha256(sql.encode()).hexdigest() == compiled.bindings[0].ddl_sha256
    statements = profile_view_statements(compiled, ["customer__p_old"])
    assert statements[0].startswith('DROP VIEW IF EXISTS "entity_access".')
    assert any("CREATE VIEW" in item and "CREATE OR REPLACE" not in item for item in statements)
    assert any('OWNER TO "refraq_exposure_owner"' in item for item in statements)
    assert any("GRANT SELECT" in item and '"refraq_reader"' in item for item in statements)
    revised = compile_policy(replace(
        _policy(_grant("eag_user", "eap_a", "user", "user_1"), people=(person,)),
        revision=5,
    ))
    assert "acl.rev_ok('ent_customer', 5)" in revised.bindings[0].sql
    assert "acl.rev_ok('ent_customer', 4)" not in revised.bindings[0].sql


def test_signed_context_roundtrip_and_key_rotation() -> None:
    person = Person("user_1", "role_1", ("grp_1",))
    user_grant = _grant("eag_user", "eap_a", "user", "user_1")
    role_grant = _grant("eag_role", "eap_b", "role", "role_1")
    policy = _policy(user_grant, role_grant, people=(person,))
    compiled = compile_policy(policy)
    first = SigningKey("k1", b"a" * 32)
    second = SigningKey("k2", b"b" * 32)
    third = SigningKey("k3", b"c" * 32)
    ring = KeyRing((first,))
    old = issue_context(
        policy, compiled, person, ring, action="read", request_id="req_old", now=NOW
    )
    ring = rotate_key(ring, second)
    token = issue_context(
        policy,
        compiled,
        person,
        ring,
        action="read",
        request_id="req_1",
        now=NOW,
    )
    payload = verify_token(token, ring.by_kid(), now=NOW)
    assert payload is not None
    assert payload["kid"] == "k2"
    assert payload["sub"] == "user_1"
    assert payload["grants"] == ["eag_user", "eag_role"]
    assert payload["rev"] == {"ent_customer": 4}
    assert payload["req"] == "req_1"
    assert verify_token(old, ring.by_kid(), now=NOW) is not None
    narrowed = issue_context(
        policy,
        compiled,
        person,
        ring,
        action="read",
        narrow=Narrow("user"),
        now=NOW,
    )
    narrow_payload = verify_token(narrowed, ring.by_kid(), now=NOW)
    assert narrow_payload is not None
    assert narrow_payload["grants"] == ["eag_user"]
    assert verify_token(token, ring.by_kid(), now=NOW + timedelta(seconds=120)) is None
    forged = token[:-4] + "0000"
    assert verify_token(forged, ring.by_kid(), now=NOW) is None
    rotated = rotate_key(ring, third)
    assert verify_token(old, rotated.by_kid(), now=NOW) is None
    assert verify_token(token, rotated.by_kid(), now=NOW) is not None
    assert rotated.current().kid == "k3"
    assert {item.kid for item in rotated.keys} == {"k2", "k3"}
    calls: list[tuple[str, dict[str, object]]] = []

    class _Conn:
        def execute(self, statement: object, params: dict[str, object]) -> None:
            calls.append((str(statement), params))

    install_signing_keys(_Conn(), rotated)
    assert [params["kid"] for _sql, params in calls] == ["k2", "k3"]


def _published_entity() -> tuple[str, str]:
    now = utc_now()
    attr = AttributeRecord(name="name", type="string", max_length=32, attribute_id="att_name")
    entity = BusinessEntityRecord(
        id=new_entity_id(),
        table_name="customer",
        name="Customer",
        description="",
        deprecated_at=None,
        created_at=now,
        updated_at=now,
    )
    version = EntityVersionRecord(
        id=new_version_id(),
        entity_id=entity.id,
        version=1,
        attributes=[attr],
        materialized_attributes=[{**attribute_to_dict(attr), "attribute_id": "att_name"}],
        publish_status=PUBLISHED,
        latest_reconcile_job_id=None,
        created_at=now,
        updated_at=now,
    )
    get_entity_store().create_entity(entity, version)
    user = get_user_store().create_user(
        account="ada",
        display_name="Ada",
        password_hash=hash_password("secret"),
        role_id="role_1",
        status="active",
    )
    return entity.id, user.id


def test_policy_job_is_user_triggered_and_rows_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.entity.access.jobs.dispatch_entity_job", lambda job: job.id
    )
    entity_id, user_id = _published_entity()
    created = create_profile(
        entity_id,
        key="sales",
        name="Sales",
        description=None,
        columns=[{"attribute_id": "att_name", "level": "clear"}],
        actor_user_id=user_id,
        actor_token_id=None,
    )
    create_grant(
        entity_id,
        subject={"type": "user", "id": user_id},
        profile_id=created["profile"]["id"],
        row_rule=None,
        actions=["read"],
        status="active",
        valid_until=None,
        actor_user_id=user_id,
        actor_token_id=None,
    )
    queued, _total = get_job_store().list(kind="entity_access_views")
    assert len(queued) == 1
    assert queued[0].trigger_kind == "user"
    assert queued[0].input["entity_id"] == entity_id
    with pytest.raises(EntityAccessPending):
        require_subject_view(entity_id, user_id)
    assert run_job(queued[0].id)["status"] == "succeeded"
    outcome = require_subject_view(entity_id, user_id)
    assert outcome.shape is not None
    stored = get_access_store().bindings(entity_id)
    assert stored
    assert {item.status for item in stored} == {"ready"}
    assert all(len(item.ddl_sha256) == 64 for item in stored)
    port = get_entity_table_port()
    assert isinstance(port, RecordingEntityTablePort)
    script = "\n".join(port.statements)
    assert "CREATE OR REPLACE" not in script
    assert 'DROP VIEW IF EXISTS "entity_access".' in script
    assert 'OWNER TO "refraq_exposure_owner"' in script


def test_new_membership_enqueues_a_system_job(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.entity.access.jobs.dispatch_entity_job", lambda job: job.id
    )
    entity_id, user_id = _published_entity()
    sales = create_profile(
        entity_id,
        key="sales",
        name="Sales",
        description=None,
        columns=[{"attribute_id": "att_name", "level": "clear"}],
        actor_user_id=user_id,
        actor_token_id=None,
    )
    finance = create_profile(
        entity_id,
        key="finance",
        name="Finance",
        description=None,
        columns=[{"attribute_id": "att_name", "level": "clear"}],
        actor_user_id=user_id,
        actor_token_id=None,
    )
    create_grant(
        entity_id,
        subject={"type": "user", "id": user_id},
        profile_id=sales["profile"]["id"],
        row_rule=None,
        actions=["read"],
        status="active",
        valid_until=None,
        actor_user_id=user_id,
        actor_token_id=None,
    )
    group = create_group(
        key="east",
        name="East",
        description=None,
        actor_user_id=user_id,
        actor_token_id=None,
    )
    create_grant(
        entity_id,
        subject={"type": "group", "id": group.id},
        profile_id=finance["profile"]["id"],
        row_rule=None,
        actions=["read"],
        status="active",
        valid_until=None,
        actor_user_id=user_id,
        actor_token_id=None,
    )
    queued, _total = get_job_store().list(kind="entity_access_views")
    assert run_job(queued[0].id)["status"] == "succeeded"
    require_subject_view(entity_id, user_id)
    add_member(group.id, user_id, actor_user_id=user_id, actor_token_id=None)
    with pytest.raises(EntityAccessPending):
        require_subject_view(entity_id, user_id)
    jobs, _total = get_job_store().list(kind="entity_access_views")
    system = [item for item in jobs if item.trigger_kind == "system"]
    assert len(system) == 1
    assert system[0].status == "queued"


def test_failed_view_job_is_not_requeued_on_every_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.entity.access.jobs.dispatch_entity_job", lambda job: job.id
    )
    entity_id, user_id = _published_entity()
    created = create_profile(
        entity_id,
        key="sales",
        name="Sales",
        description=None,
        columns=[{"attribute_id": "att_name", "level": "clear"}],
        actor_user_id=user_id,
        actor_token_id=None,
    )
    create_grant(
        entity_id,
        subject={"type": "user", "id": user_id},
        profile_id=created["profile"]["id"],
        row_rule=None,
        actions=["read"],
        status="active",
        valid_until=None,
        actor_user_id=user_id,
        actor_token_id=None,
    )

    class _ViewDdlFails(RecordingEntityTablePort):
        def execute_ddl(self, statements: list[str]) -> None:
            raise RuntimeError("view ddl failed")

    bind_entity_table_port(_ViewDdlFails())
    queued, _total = get_job_store().list(kind="entity_access_views")
    assert run_job(queued[0].id)["status"] == "failed"
    for _ in range(3):
        with pytest.raises(EntityAccessPending):
            require_subject_view(entity_id, user_id)
    jobs, _total = get_job_store().list(kind="entity_access_views")
    assert [item.trigger_kind for item in jobs] == ["user"]
    later = utc_now() + timedelta(minutes=2)
    monkeypatch.setattr("backend.entity.access.service.utc_now", lambda: later)
    with pytest.raises(EntityAccessPending):
        require_subject_view(entity_id, user_id)
    jobs, _total = get_job_store().list(kind="entity_access_views")
    assert sorted(item.trigger_kind for item in jobs) == ["system", "user"]


def test_over_cap_stays_a_limit_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.entity.access.jobs.dispatch_entity_job", lambda job: job.id
    )
    monkeypatch.setattr(
        "backend.entity.access.plan.max_profile_combinations", lambda: 0
    )
    entity_id, user_id = _published_entity()
    first = create_profile(
        entity_id,
        key="sales",
        name="Sales",
        description=None,
        columns=[{"attribute_id": "att_name", "level": "clear"}],
        actor_user_id=user_id,
        actor_token_id=None,
    )
    second = create_profile(
        entity_id,
        key="finance",
        name="Finance",
        description=None,
        columns=[{"attribute_id": "att_name", "level": "clear"}],
        actor_user_id=user_id,
        actor_token_id=None,
    )
    for profile_id in (first["profile"]["id"], second["profile"]["id"]):
        create_grant(
            entity_id,
            subject={"type": "user", "id": user_id},
            profile_id=profile_id,
            row_rule=None,
            actions=["read"],
            status="active",
            valid_until=None,
            actor_user_id=user_id,
            actor_token_id=None,
        )
    with pytest.raises(EntityAccessCombinationLimit):
        require_subject_view(entity_id, user_id)
    jobs, _total = get_job_store().list(kind="entity_access_views")
    assert all(item.trigger_kind != "system" for item in jobs)


def test_publish_builds_profile_views_in_the_same_transaction() -> None:
    now = utc_now()
    attr = AttributeRecord(name="name", type="string", max_length=32, attribute_id="att_name")
    entity = BusinessEntityRecord(
        id=new_entity_id(),
        table_name="customer",
        name="Customer",
        description="",
        deprecated_at=None,
        created_at=now,
        updated_at=now,
    )
    version = EntityVersionRecord(
        id=new_version_id(),
        entity_id=entity.id,
        version=1,
        attributes=[attr],
        materialized_attributes=[],
        publish_status=UNPUBLISHED,
        latest_reconcile_job_id=None,
        created_at=now,
        updated_at=now,
    )
    get_entity_store().create_entity(entity, version)
    get_access_store().insert_profile(
        ProfileRecord(
            id="eap_sales",
            entity_id=entity.id,
            key="sales",
            name="Sales",
            description=None,
            columns=[{"attribute_id": "att_unused", "level": "clear"}],
            created_at=now,
            updated_at=now,
        )
    )
    port = RecordingEntityTablePort()
    bind_entity_table_port(port)
    job = create_queued_job(
        kind=KIND_RECONCILE,
        input={
            "entity_version_id": version.id,
            "dictionary_bindings": {},
            "reference_bindings": {},
        },
        summary="entity_reconcile · customer",
        trigger_kind="user",
    )
    assert run_job(job.id)["status"] == "succeeded"
    script = "\n".join(port.statements)
    assert "CREATE OR REPLACE" not in script
    assert 'DROP VIEW IF EXISTS "entity_access".' in script
    assert 'CREATE VIEW "entity_access".' in script
    assert 'OWNER TO "refraq_exposure_owner"' in script
    ready = get_access_store().bindings(entity.id)
    assert ready and ready[0].status == "ready"
    assert ready[0].ddl_sha256


def test_publish_view_failure_rolls_the_table_back() -> None:
    now = utc_now()
    attr = AttributeRecord(name="name", type="string", max_length=32)
    entity = BusinessEntityRecord(
        id=new_entity_id(),
        table_name="customer",
        name="Customer",
        description="",
        deprecated_at=None,
        created_at=now,
        updated_at=now,
    )
    version = EntityVersionRecord(
        id=new_version_id(),
        entity_id=entity.id,
        version=1,
        attributes=[attr],
        materialized_attributes=[],
        publish_status=UNPUBLISHED,
        latest_reconcile_job_id=None,
        created_at=now,
        updated_at=now,
    )
    get_entity_store().create_entity(entity, version)

    class _ViewDdlFails(RecordingEntityTablePort):
        def execute_ddl(self, statements: list[str]) -> None:
            raise RuntimeError("view ddl failed")

    port = _ViewDdlFails()
    bind_entity_table_port(port)
    job = create_queued_job(
        kind=KIND_RECONCILE,
        input={
            "entity_version_id": version.id,
            "dictionary_bindings": {},
            "reference_bindings": {},
        },
        summary="entity_reconcile · customer",
        trigger_kind="user",
    )
    assert run_job(job.id)["status"] == "failed"
    stored = get_entity_store().get_version(version.id)
    assert stored is not None
    assert stored.publish_status == UNPUBLISHED
    physical, _comment = compose_physical_table_name("customer", 1, version.id)
    assert port.table_exists("entity_data", physical) is False
    assert ("entity_data", "customer") not in port._views


def test_rebuild_without_a_head_marks_the_revision_applied() -> None:
    now = utc_now()
    entity = BusinessEntityRecord(
        id=new_entity_id(),
        table_name="customer",
        name="Customer",
        description="",
        deprecated_at=None,
        created_at=now,
        updated_at=now,
    )
    version = EntityVersionRecord(
        id=new_version_id(),
        entity_id=entity.id,
        version=1,
        attributes=[],
        materialized_attributes=[],
        publish_status=UNPUBLISHED,
        latest_reconcile_job_id=None,
        created_at=now,
        updated_at=now,
    )
    get_entity_store().create_entity(entity, version)
    get_access_store().set_revision(entity.id, 3)
    result = rebuild_entity_views(entity.id)
    assert result["views_created"] == 0
    assert result["policy_revision"] == 3
    assert get_access_store().views_revision(entity.id) == 3
    assert get_access_store().bindings(entity.id) == []
