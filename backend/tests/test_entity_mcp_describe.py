"""describe_entity and list_dictionary_codes, observed as tool JSON."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

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
from backend.core.time import format_instant, utc_now  # noqa: E402
from backend.entity.access.records import GrantRecord, ProfileRecord  # noqa: E402
from backend.entity.access.store import get_access_store  # noqa: E402
from backend.entity.access.views import rebuild_entity_views  # noqa: E402
from backend.entity.attribute_type import resolve  # noqa: E402
from backend.entity.dictionaries.records import (  # noqa: E402
    DictionaryEntryRecord,
    DictionaryRecord,
)
from backend.entity.dictionaries.store import get_dictionary_store  # noqa: E402
from backend.entity.ids import (  # noqa: E402
    new_access_grant_id,
    new_access_profile_id,
    new_entity_id,
    new_version_id,
)
from backend.entity.lifecycle import latest_published_of  # noqa: E402
from backend.entity.mcp.actor import mcp_authorization  # noqa: E402
from backend.entity.errors import EntityNotServing  # noqa: E402
from backend.entity.mcp.server import (  # noqa: E402
    describe_entity,
    list_dictionary_codes,
    list_entities,
)
from backend.entity.records import (  # noqa: E402
    AttributeRecord,
    BusinessEntityRecord,
    EntityVersionRecord,
    attribute_to_dict,
)
from backend.entity.store import get_entity_store  # noqa: E402
from backend.entity.table_name import published_attributes  # noqa: E402
from backend.main import app  # noqa: E402
from backend.tests.entity_access_oracle import prepare_legacy_entity  # noqa: E402
from backend.worker.app import celery_app  # noqa: E402

celery_app.conf.task_always_eager = True
celery_app.conf.task_eager_propagates = True

PASSWORD = "secret"
READER_PERMISSIONS = [
    "console:access",
    "tokens:write",
    "entity:data_read",
    "entity:write",
]


@pytest.fixture()
def client() -> TestClient:
    roles = get_role_store()
    seed_roles(roles)
    admin = roles.get_by_key("super_admin")
    assert admin is not None
    get_user_store().create_user(
        account="admin",
        display_name="Admin",
        password_hash=hash_password(PASSWORD),
        role_id=admin.id,
        status="active",
    )
    with TestClient(app) as test_client:
        login = test_client.post(
            "/auth/login", json={"account": "admin", "password": PASSWORD}
        )
        assert login.status_code == 200, login.text
        yield test_client


def _secret(client: TestClient, name: str = "describe-pat") -> str:
    expires = format_instant(utc_now() + timedelta(days=7))
    created = client.post("/tokens", json={"name": name, "expires_at": expires})
    assert created.status_code == 201, created.text
    return created.json()["secret"]


def _account(
    client: TestClient, account: str, permissions: list[str]
) -> tuple[str, str]:
    role = create_role(
        get_role_store(),
        key=account,
        name=account,
        permissions=permissions,
    )
    user = get_user_store().create_user(
        account=account,
        display_name=account,
        password_hash=hash_password(PASSWORD),
        role_id=role.id,
        status="active",
    )
    login = client.post(
        "/auth/login", json={"account": account, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    return _secret(client, name=f"{account}-pat"), user.id


def _call(fn: Any, secret: str, **kwargs: Any) -> dict[str, Any]:
    with mcp_authorization(f"Bearer {secret}"):
        return json.loads(fn(**kwargs))


def _describe(secret: str, **kwargs: Any) -> dict[str, Any]:
    return _call(describe_entity, secret, **kwargs)


def _codes(secret: str, **kwargs: Any) -> dict[str, Any]:
    return _call(list_dictionary_codes, secret, **kwargs)


def _seed(
    *,
    table_name: str,
    name: str = "Material",
    description: str = "Stock material",
    attributes: list[AttributeRecord] | None = None,
    publish: bool = True,
    deprecated: bool = False,
) -> BusinessEntityRecord:
    now = datetime.now(timezone.utc)
    attrs = attributes or [
        AttributeRecord(
            name="sku",
            type="string",
            required=True,
            unique=True,
            business_key=True,
            description="SKU code",
            max_length=32,
        ),
        AttributeRecord(name="note", type="text", description="Free text"),
    ]
    entity = BusinessEntityRecord(
        id=new_entity_id(),
        table_name=table_name,
        name=name,
        description=description,
        deprecated_at=now if deprecated else None,
        created_at=now,
        updated_at=now,
    )
    version = EntityVersionRecord(
        id=new_version_id(),
        entity_id=entity.id,
        version=1,
        attributes=list(attrs),
        materialized_attributes=(
            [attribute_to_dict(item) for item in attrs] if publish else []
        ),
        publish_status="published" if publish else "unpublished",
        latest_reconcile_job_id=None,
        created_at=now,
        updated_at=now,
    )
    get_entity_store().create_entity(entity, version)
    if publish:
        prepare_legacy_entity(entity.id)
    return entity


def _attribute_ids(entity_id: str) -> dict[str, str]:
    head = latest_published_of(get_entity_store().list_all_versions(entity_id))
    assert head is not None
    return {
        attr.name: attr.attribute_id
        for attr in published_attributes(head)
        if isinstance(attr.attribute_id, str)
    }


def _grant(
    entity_id: str,
    user_id: str,
    names: list[str],
    *,
    key: str = "reader",
    rebuild: bool = True,
) -> None:
    ids = _attribute_ids(entity_id)
    now = utc_now()
    profile_id = new_access_profile_id()
    get_access_store().insert_profile(
        ProfileRecord(
            id=profile_id,
            entity_id=entity_id,
            key=key,
            name=key,
            description=None,
            columns=[
                {"attribute_id": ids[name], "level": "clear"} for name in names
            ],
            created_at=now,
            updated_at=now,
        )
    )
    get_access_store().insert_grant(
        GrantRecord(
            id=new_access_grant_id(),
            entity_id=entity_id,
            subject_type="user",
            subject_id=user_id,
            profile_id=profile_id,
            row_rule=None,
            actions=["read"],
            status="active",
            valid_until=None,
            created_at=now,
            updated_at=now,
        )
    )
    if rebuild:
        rebuild_entity_views(entity_id)


def _reference(name: str, target_id: str) -> AttributeRecord:
    return AttributeRecord(
        name=name,
        type="reference",
        required=False,
        target_entity_id=target_id,
    )


def _snapshot(entity_id: str, snapshots: dict[str, dict[str, Any]]) -> None:
    head = latest_published_of(get_entity_store().list_all_versions(entity_id))
    assert head is not None
    head.reference_snapshots = snapshots
    get_entity_store().save_version(head)


def _not_found(table_name: str) -> dict[str, Any]:
    return {
        "error": {
            "code": "ENTITY_NOT_FOUND",
            "message": (
                f"Business Entity with table_name '{table_name}' was not found"
            ),
        }
    }


def test_describe_entity_returns_the_read_shape_without_write_fields(
    client: TestClient,
) -> None:
    _seed(table_name="material")
    body = _describe(_secret(client), table_name="material")
    assert "error" not in body, body
    assert body["entity"]["table_name"] == "material"
    assert body["entity"]["name"] == "Material"
    assert body["entity"]["description"] == "Stock material"
    assert "writable" not in body["entity"]
    assert body["business_key"] == "sku"
    assert body["withheld_field"] is None
    assert body["access"]["narrowed"] is False
    assert body["references"] == []
    assert body["inbound_references"] == []
    assert "row_write_max" not in body["limits"]
    assert body["limits"]["page_limit_default"] == 50
    assert body["limits"]["page_limit_max"] == 200
    names = [item["name"] for item in body["attributes"]]
    assert names == ["sku", "note"]
    sku = body["attributes"][0]
    assert sku["description"] == "SKU code"
    assert sku["business_key"] is True
    assert sku["presentation"] == {
        "row_varying": False,
        "levels": [{"key": "clear", "mode": "clear"}],
        "may_be_withheld": False,
    }
    assert "writable" not in sku
    assert "upsert_key" not in sku
    assert "codes_truncated" not in sku
    assert body["attributes"][1]["description"] == "Free text"


def test_describe_entity_does_not_open_an_entity_connection(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(table_name="material")

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("entity connection")

    monkeypatch.setattr("backend.entity.data.sql.entity_connection", boom)
    monkeypatch.setattr("backend.entity.data.sql.entity_read_connection", boom)
    body = _describe(_secret(client), table_name="material")
    assert body["entity"]["table_name"] == "material"


def test_describe_entity_rejects_narrow(client: TestClient) -> None:
    _seed(table_name="material")
    secret = _secret(client)
    refused = _describe(
        secret, table_name="material", narrow={"type": "user"}
    )
    assert refused == {
        "error": {"code": "REQUEST_INVALID", "message": "narrow is not accepted"}
    }
    plain = _describe(secret, table_name="material")
    assert plain["access"]["narrowed"] is False
    assert [item["name"] for item in plain["attributes"]] == ["sku", "note"]


def test_unknown_and_invisible_entities_match(
    client: TestClient,
) -> None:
    _seed(table_name="secret_goods", name="Secret", description="Hidden ledger")
    secret, _user_id = _account(client, "reader", READER_PERMISSIONS)
    missing = _describe(secret, table_name="missing_table")
    hidden = _describe(secret, table_name="secret_goods")
    assert missing == _not_found("missing_table")
    assert hidden == _not_found("secret_goods")
    assert set(missing) == set(hidden) == {"error"}
    assert set(missing["error"]) == set(hidden["error"]) == {"code", "message"}


def test_write_permission_does_not_reveal_an_entity(client: TestClient) -> None:
    _seed(table_name="secret_goods")
    secret, _user_id = _account(
        client,
        "author",
        ["console:access", "tokens:write", "entity:data_read", "entity:write"],
    )
    assert _describe(secret, table_name="secret_goods") == _not_found(
        "secret_goods"
    )


def test_describe_entity_hides_attributes_outside_the_read_shape(
    client: TestClient,
) -> None:
    entity = _seed(table_name="material")
    secret, user_id = _account(client, "reader", READER_PERMISSIONS)
    _grant(entity.id, user_id, ["sku"])
    body = _describe(secret, table_name="material")
    assert [item["name"] for item in body["attributes"]] == ["sku"]
    assert "note" not in json.dumps(body)


def test_describe_entity_marks_withheld_columns(client: TestClient) -> None:
    entity = _seed(table_name="material")
    secret, user_id = _account(client, "reader", READER_PERMISSIONS)
    _grant(entity.id, user_id, ["sku", "note"], key="full")
    _grant(entity.id, user_id, ["sku"], key="sku_only")
    body = _describe(secret, table_name="material")
    assert body["withheld_field"] == "__withheld"
    by_name = {item["name"]: item for item in body["attributes"]}
    assert set(by_name) == {"sku", "note"}
    assert by_name["note"]["presentation"]["may_be_withheld"] is True
    assert by_name["note"]["presentation"]["row_varying"] is True
    assert by_name["sku"]["presentation"]["may_be_withheld"] is False
    assert by_name["sku"]["presentation"]["levels"] == [
        {"key": "clear", "mode": "clear"}
    ]


_PREDATES = "Serving head predates reference snapshots; publish a new version"


def test_profile_reference_without_a_snapshot_stays_listed(
    client: TestClient,
) -> None:
    supplier = _seed(
        table_name="supplier",
        name="Supplier",
        description="Party",
        attributes=[
            AttributeRecord(
                name="code",
                type="string",
                required=True,
                unique=True,
                business_key=True,
                max_length=16,
            )
        ],
    )
    _seed(
        table_name="material",
        name="Material",
        description="Stock",
        attributes=[
            AttributeRecord(
                name="sku",
                type="string",
                required=True,
                unique=True,
                business_key=True,
                max_length=32,
            ),
            _reference("supplier_id", supplier.id),
        ],
    )
    secret = _secret(client, name="listed-pat")
    listed = _call(list_entities, secret)
    assert "error" not in listed, listed
    assert {item["table_name"] for item in listed["items"]} >= {
        "material",
        "supplier",
    }

    described = _describe(secret, table_name="material")
    assert described["error"]["code"] == "ENTITY_NOT_SERVING"
    assert described["error"]["message"] == _PREDATES

    target = _describe(secret, table_name="supplier")
    assert "error" not in target, target
    assert {"table_name": "material", "attribute": "supplier_id"} in target[
        "inbound_references"
    ]

    material_id = _entity_id("material")
    with pytest.raises(EntityNotServing) as raised:
        rebuild_entity_views(material_id)
    assert raised.value.message == _PREDATES


def test_lifecycle_errors_match_the_data_api(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "backend.entity.access.jobs.dispatch_entity_job", lambda job: job.id
    )
    deprecated = _seed(table_name="gone", deprecated=True)
    admin = _secret(client, name="admin-life")
    assert _describe(admin, table_name="gone")["error"]["code"] == "ENTITY_DEPRECATED"
    assert _describe(admin, table_name="gone")["error"]["message"] == (
        "A deprecated Business Entity is closed"
    )

    ref = AttributeRecord(
        name="supplier_id",
        type="reference",
        required=False,
        target_entity_id="ent_supplier",
    )
    _seed(table_name="legacy_ref", attributes=[ref])
    unserving = _describe(admin, table_name="legacy_ref")
    assert unserving["error"]["code"] == "ENTITY_NOT_SERVING"
    assert unserving["error"]["message"] == (
        "Serving head predates reference snapshots; publish a new version"
    )

    pending_user, pending_id = _account(client, "pending", READER_PERMISSIONS)
    _grant(deprecated.id, pending_id, ["sku"], rebuild=False)
    pending = _describe(pending_user, table_name="gone")
    assert pending == {
        "error": {
            "code": "ENTITY_ACCESS_PENDING",
            "message": "access configuration generating",
        }
    }

    combo = _seed(table_name="combo")
    combo_user, combo_id = _account(client, "combo", READER_PERMISSIONS)
    _grant(combo.id, combo_id, ["sku"], key="left", rebuild=False)
    _grant(combo.id, combo_id, ["note"], key="right", rebuild=False)
    monkeypatch.setattr(
        "backend.entity.access.plan.max_profile_combinations", lambda: 0
    )
    limited = _describe(combo_user, table_name="combo")
    assert limited == {
        "error": {
            "code": "ENTITY_ACCESS_COMBINATION_LIMIT",
            "message": "access configuration over limit for this subject",
        }
    }


def test_references_name_the_visible_target_business_key(
    client: TestClient,
) -> None:
    hidden = _seed(
        table_name="hidden_supplier",
        name="Hidden Supplier",
        description="Not granted",
        attributes=[
            AttributeRecord(
                name="code",
                type="string",
                required=True,
                unique=True,
                business_key=True,
                max_length=16,
            )
        ],
    )
    supplier = _seed(
        table_name="supplier",
        name="Supplier",
        description="Party",
        attributes=[
            AttributeRecord(
                name="code",
                type="string",
                required=True,
                unique=True,
                business_key=True,
                max_length=16,
            )
        ],
    )
    sku = AttributeRecord(
        name="sku",
        type="string",
        required=True,
        unique=True,
        business_key=True,
        description="SKU code",
        max_length=32,
    )
    linked = _seed(
        table_name="linked",
        attributes=[
            sku,
            _reference("supplier_code", supplier.id),
            _reference("hidden_code", hidden.id),
        ],
    )
    _snapshot(
        linked.id,
        {
            "supplier_code": {
                "attribute": "legacy_code",
                "type": "string",
                "max_length": 16,
            },
            "hidden_code": {
                "attribute": "code",
                "type": "string",
                "max_length": 16,
            },
        },
    )
    secret, user_id = _account(client, "reader", READER_PERMISSIONS)
    _grant(supplier.id, user_id, ["code"])
    _grant(linked.id, user_id, ["sku", "supplier_code", "hidden_code"])
    body = _describe(secret, table_name="linked")
    assert "hidden_supplier" not in json.dumps(body)
    assert "Hidden Supplier" not in json.dumps(body)
    by_name = {item["name"]: item for item in body["attributes"]}
    assert by_name["supplier_code"]["target"]["table_name"] == "supplier"
    assert by_name["supplier_code"]["target"]["business_key"] == "legacy_code"
    assert by_name["supplier_code"]["operators"] == list(resolve("string").operators)
    assert by_name["hidden_code"]["target"] is None
    assert body["references"] == [
        {
            "attribute": "supplier_code",
            "target": {"table_name": "supplier", "business_key": "legacy_code"},
        },
        {"attribute": "hidden_code", "target": None},
    ]


def test_inbound_references_use_visible_serving_heads(client: TestClient) -> None:
    customer = _seed(
        table_name="customer",
        name="Customer",
        description="Buyer",
        attributes=[
            AttributeRecord(
                name="sku",
                type="string",
                required=True,
                unique=True,
                business_key=True,
                max_length=32,
            ),
            _reference("parent", "pending"),
        ],
    )
    # The self-reference target is this entity; restamp after the id exists.
    stored = latest_published_of(get_entity_store().list_all_versions(customer.id))
    assert stored is not None
    stored.attributes = [
        AttributeRecord(
            name="sku",
            type="string",
            required=True,
            unique=True,
            business_key=True,
            max_length=32,
            attribute_id=_attribute_ids(customer.id)["sku"],
        ),
        AttributeRecord(
            name="parent",
            type="reference",
            required=False,
            target_entity_id=customer.id,
            attribute_id=_attribute_ids(customer.id).get("parent"),
        ),
    ]
    stored.materialized_attributes = [
        attribute_to_dict(item) for item in stored.attributes
    ]
    stored.reference_snapshots = {
        "parent": {"attribute": "sku", "type": "string", "max_length": 32}
    }
    get_entity_store().save_version(stored)
    prepare_legacy_entity(customer.id)

    def referrer(
        table_name: str,
        attribute: str,
        *,
        publish: bool = True,
        deprecated: bool = False,
    ) -> BusinessEntityRecord:
        return _seed(
            table_name=table_name,
            name=table_name,
            description=table_name,
            attributes=[_reference(attribute, customer.id)],
            publish=publish,
            deprecated=deprecated,
        )

    referrer("z_ord", "buyer")
    referrer("a_ord", "buyer")
    referrer("secret_ord", "buyer")
    referrer("draft_ord", "buyer", publish=False)
    moved = referrer("moved_ord", "old_ref")
    now = datetime.now(timezone.utc)
    get_entity_store().create_version(
        EntityVersionRecord(
            id=new_version_id(),
            entity_id=moved.id,
            version=2,
            attributes=[_reference("new_ref", customer.id)],
            materialized_attributes=[],
            publish_status="unpublished",
            latest_reconcile_job_id=None,
            created_at=now,
            updated_at=now,
        )
    )
    part = referrer("part_ord", "seen_ref")
    part_head = latest_published_of(get_entity_store().list_all_versions(part.id))
    assert part_head is not None
    part_ids = _attribute_ids(part.id)
    part_head.attributes = [
        AttributeRecord(
            name="seen_ref",
            type="reference",
            target_entity_id=customer.id,
            attribute_id=part_ids["seen_ref"],
        ),
        AttributeRecord(
            name="hid_ref",
            type="reference",
            target_entity_id=customer.id,
            attribute_id=None,
        ),
    ]
    part_head.materialized_attributes = [
        attribute_to_dict(item) for item in part_head.attributes
    ]
    get_entity_store().save_version(part_head)
    prepare_legacy_entity(part.id)
    old = referrer("old_ord", "buyer", deprecated=True)

    secret, user_id = _account(client, "reader", READER_PERMISSIONS)
    _grant(customer.id, user_id, ["sku", "parent"])
    for entity_id, names in (
        (_entity_id("a_ord"), ["buyer"]),
        (_entity_id("z_ord"), ["buyer"]),
        (moved.id, ["old_ref"]),
        (part.id, ["seen_ref"]),
        (old.id, ["buyer"]),
    ):
        _grant(entity_id, user_id, names, rebuild=False)

    body = _describe(secret, table_name="customer")
    assert body["inbound_references"] == [
        {"table_name": "a_ord", "attribute": "buyer"},
        {"table_name": "customer", "attribute": "parent"},
        {"table_name": "moved_ord", "attribute": "old_ref"},
        {"table_name": "old_ord", "attribute": "buyer"},
        {"table_name": "part_ord", "attribute": "seen_ref"},
        {"table_name": "z_ord", "attribute": "buyer"},
    ]
    text = json.dumps(body)
    for hidden in ("secret_ord", "draft_ord", "new_ref", "hid_ref"):
        assert hidden not in text


def _entity_id(table_name: str) -> str:
    entity = get_entity_store().get_entity_by_table_name(table_name)
    assert entity is not None
    return entity.id


def test_describe_entity_truncates_dictionary_codes(client: TestClient) -> None:
    now = datetime.now(timezone.utc)
    entries = tuple(
        DictionaryEntryRecord(
            code=f"c{index:02d}",
            label=f"L{index:02d}",
            active=index != 3,
            position=index,
        )
        for index in range(51)
    )
    dictionary = DictionaryRecord(
        id="dict_long",
        name="long_codes",
        display_name="Long",
        description=None,
        revision=1,
        deprecated_at=None,
        entries=entries + (
            DictionaryEntryRecord(
                code="extra", label="Extra", active=True, position=51
            ),
        ),
        created_at=now,
        updated_at=now,
    )
    get_dictionary_store().create(dictionary)
    entity = _seed(
        table_name="coded",
        attributes=[
            AttributeRecord(
                name="status",
                type="dictionary",
                required=True,
                dictionary_id=dictionary.id,
                description="Status code",
            )
        ],
    )
    head = latest_published_of(get_entity_store().list_all_versions(entity.id))
    assert head is not None
    head.dictionary_snapshots = {
        "status": {
            "dictionary_id": dictionary.id,
            "revision": 1,
            "codes": [f"c{index:02d}" for index in range(51)] + ["ghost"],
        }
    }
    get_entity_store().save_version(head)
    body = _describe(_secret(client), table_name="coded")
    status = body["attributes"][0]
    assert status["description"] == "Status code"
    assert status["codes_truncated"] is True
    assert len(status["codes"]) == 50
    assert status["codes"][0] == {"code": "c00", "label": "L00", "active": True}
    assert status["codes"][3] == {"code": "c03", "label": "L03", "active": False}
    assert status["codes"][-1] == {"code": "c49", "label": "L49", "active": True}
    assert "writable" not in status["codes"][0]
    rendered = json.dumps(status["codes"])
    assert "c50" not in rendered
    assert "ghost" not in rendered
    assert "extra" not in rendered


def test_list_dictionary_codes_pages_the_head_snapshot(client: TestClient) -> None:
    now = datetime.now(timezone.utc)
    entries = [
        DictionaryEntryRecord(code="open", label="Open", active=True, position=0),
        DictionaryEntryRecord(
            code="closed", label="Closed", active=False, position=1
        ),
        DictionaryEntryRecord(code="extra", label="Extra", active=True, position=2),
    ]
    dictionary = DictionaryRecord(
        id="dict_status",
        name="status_codes",
        display_name="Status",
        description=None,
        revision=1,
        deprecated_at=None,
        entries=tuple(entries),
        created_at=now,
        updated_at=now,
    )
    get_dictionary_store().create(dictionary)
    sku = AttributeRecord(
        name="sku",
        type="string",
        required=True,
        unique=True,
        business_key=True,
        max_length=32,
    )
    secret_code = AttributeRecord(
        name="secret_code",
        type="dictionary",
        dictionary_id=dictionary.id,
    )
    status = AttributeRecord(
        name="status",
        type="dictionary",
        required=True,
        dictionary_id=dictionary.id,
        description="Status code",
    )
    entity = _seed(table_name="ticket", attributes=[sku, status, secret_code])
    head = latest_published_of(get_entity_store().list_all_versions(entity.id))
    assert head is not None
    head.dictionary_snapshots = {
        "status": {
            "dictionary_id": dictionary.id,
            "revision": 1,
            "codes": ["open", "closed", "ghost"],
        },
        "secret_code": {
            "dictionary_id": dictionary.id,
            "revision": 1,
            "codes": ["open"],
        },
    }
    get_entity_store().save_version(head)
    secret, user_id = _account(client, "reader", READER_PERMISSIONS)
    _grant(entity.id, user_id, ["sku", "status"])

    described = _describe(secret, table_name="ticket")
    described_status = next(
        item for item in described["attributes"] if item["name"] == "status"
    )
    assert described_status["codes_truncated"] is False
    assert described_status["codes"] == [
        {"code": "open", "label": "Open", "active": True},
        {"code": "closed", "label": "Closed", "active": False},
        {"code": "ghost", "label": None, "active": False},
    ]

    page = _codes(secret, table_name="ticket", attribute="status")
    assert page["total"] == 3
    assert page["limit"] == 50
    assert page["offset"] == 0
    assert page["items"] == described_status["codes"]

    opened = _codes(
        secret, table_name="ticket", attribute="status", query_text="OPEN"
    )
    assert opened["items"] == [
        {"code": "open", "label": "Open", "active": True}
    ]
    closed = _codes(
        secret, table_name="ticket", attribute="status", query_text="clos"
    )
    assert closed["items"] == [
        {"code": "closed", "label": "Closed", "active": False}
    ]
    assert "extra" not in json.dumps(page)

    clamped = _codes(
        secret,
        table_name="ticket",
        attribute="status",
        limit=999,
        offset=-4,
    )
    assert clamped["limit"] == 200
    assert clamped["offset"] == 0
    assert clamped["total"] == 3

    missing = _codes(secret, table_name="ticket", attribute="nope")
    hidden = _codes(secret, table_name="ticket", attribute="secret_code")
    assert missing == {
        "error": {
            "code": "REQUEST_INVALID",
            "message": "Attribute 'nope' was not found",
        }
    }
    assert hidden == {
        "error": {
            "code": "REQUEST_INVALID",
            "message": "Attribute 'secret_code' was not found",
        }
    }
    not_dict = _codes(secret, table_name="ticket", attribute="sku")
    assert not_dict == {
        "error": {
            "code": "REQUEST_INVALID",
            "message": "Attribute 'sku' is not a dictionary",
        }
    }
    assert _codes(
        secret,
        table_name="ticket",
        attribute="status",
        narrow={"type": "role", "id": "role_x"},
    ) == {
        "error": {"code": "REQUEST_INVALID", "message": "narrow is not accepted"}
    }
    assert _codes(secret, table_name="no_such", attribute="status") == _not_found(
        "no_such"
    )


def test_list_dictionary_codes_returns_codes_omitted_from_describe(
    client: TestClient,
) -> None:
    now = datetime.now(timezone.utc)
    entries = tuple(
        DictionaryEntryRecord(
            code=f"c{index:02d}",
            label=f"L{index:02d}",
            active=True,
            position=index,
        )
        for index in range(51)
    )
    get_dictionary_store().create(
        DictionaryRecord(
            id="dict_page",
            name="paged_codes",
            display_name="Paged",
            description=None,
            revision=1,
            deprecated_at=None,
            entries=entries,
            created_at=now,
            updated_at=now,
        )
    )
    entity = _seed(
        table_name="paged",
        attributes=[
            AttributeRecord(
                name="status",
                type="dictionary",
                required=True,
                dictionary_id="dict_page",
            )
        ],
    )
    head = latest_published_of(get_entity_store().list_all_versions(entity.id))
    assert head is not None
    head.dictionary_snapshots = {
        "status": {
            "dictionary_id": "dict_page",
            "revision": 1,
            "codes": [f"c{index:02d}" for index in range(51)],
        }
    }
    get_entity_store().save_version(head)
    secret = _secret(client)
    tail = _codes(
        secret, table_name="paged", attribute="status", limit=10, offset=50
    )
    assert tail == {
        "items": [{"code": "c50", "label": "L50", "active": True}],
        "total": 51,
        "limit": 10,
        "offset": 50,
    }
    found = _codes(
        secret, table_name="paged", attribute="status", query_text="l50"
    )
    assert found["items"] == [{"code": "c50", "label": "L50", "active": True}]
    assert found["total"] == 1


def test_dictionary_tools_require_entity_data_read(client: TestClient) -> None:
    roles = get_role_store()
    create_role(
        roles,
        key="no_read",
        name="No read",
        permissions=["console:access", "tokens:write", "entity:write"],
    )
    get_user_store().create_user(
        account="noread",
        display_name="No read",
        password_hash=hash_password(PASSWORD),
        role_id=roles.get_by_key("no_read").id,  # type: ignore[union-attr]
        status="active",
    )
    login = client.post(
        "/auth/login", json={"account": "noread", "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    secret = _secret(client, name="noread-pat")
    forbidden = {
        "error": {
            "code": "AUTH_FORBIDDEN",
            "message": "Missing permission entity:data_read",
        }
    }
    assert _describe(secret, table_name="material") == forbidden
    assert _codes(secret, table_name="material", attribute="status") == forbidden
