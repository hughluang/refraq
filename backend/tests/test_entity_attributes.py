"""Entity attribute types: config, DDL, classifier signals, inbound refs."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.role_store import get_role_store  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store  # noqa: E402
from backend.entity.classify import DefinitionShape, classify_shapes  # noqa: E402
from backend.entity.ddl import column_sql, create_table_statements  # noqa: E402
from backend.entity.errors import EntityAttributeInvalid  # noqa: E402
from backend.entity.present import attribute_payload, compose_physical_table_name  # noqa: E402
from backend.core.time import utc_now  # noqa: E402
from backend.entity.entity_db import entity_db_schema  # noqa: E402
from backend.entity.ids import new_entity_id, new_version_id  # noqa: E402
from backend.entity.lifecycle import PUBLISHED, UNPUBLISHED  # noqa: E402
from backend.entity.records import (  # noqa: E402
    AttributeRecord,
    BusinessEntityRecord,
    EntityVersionRecord,
    attribute_from_dict,
    attribute_to_dict,
)
from backend.entity.store import MemoryEntityStore, get_entity_store  # noqa: E402
from backend.entity.table_port import get_entity_table_port  # noqa: E402
from backend.entity.validate import validate_shape  # noqa: E402
from backend.main import app  # noqa: E402
from backend.metadata.catalog.normalized_type import (  # noqa: E402
    CLOSED_NORMALIZED_TYPES,
    PATCHABLE_NORMALIZED_TYPES,
)
from backend.metadata.type_mappings.seeds import PRODUCT_TYPE_MAPPING_SEEDS  # noqa: E402
from backend.metadata.type_mappings.store import reset_type_mapping_store  # noqa: E402
from backend.metadata.type_mappings.seeds import ensure_product_type_mappings  # noqa: E402
from backend.metadata.type_mappings.service import resolve_normalized_type  # noqa: E402


def _value(**overrides: object) -> dict:
    body: dict = {
        "name": "sku",
        "type": "string",
        "required": False,
        "config": {"max_length": 32},
    }
    body.update(overrides)
    return body


def _reference(**overrides: object) -> dict:
    body: dict = {
        "name": "supplier_id",
        "type": "reference",
        "required": False,
        "config": {"target_entity_id": "ent_missing"},
    }
    body.update(overrides)
    return body


def _create(**overrides: object) -> dict:
    body: dict = {
        "table_name": "material",
        "name": "Material",
        "description": "A stock-keeping material.",
        "attributes": [_value()],
    }
    body.update(overrides)
    return body


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
    with TestClient(app) as test_client:
        login = test_client.post(
            "/auth/login", json={"account": "admin", "password": "secret"}
        )
        assert login.status_code == 200, login.text
        yield test_client


def test_closed_set_has_thirteen_including_decimal() -> None:
    assert "decimal" in CLOSED_NORMALIZED_TYPES
    assert len(CLOSED_NORMALIZED_TYPES) == 13
    assert "unknown" not in PATCHABLE_NORMALIZED_TYPES
    assert "decimal" in PATCHABLE_NORMALIZED_TYPES
    assert len(PATCHABLE_NORMALIZED_TYPES) == 12


def test_exact_natives_seed_to_decimal() -> None:
    reset_type_mapping_store()
    ensure_product_type_mappings()
    assert resolve_normalized_type(engine="postgresql", data_type="numeric") == (
        "decimal"
    )
    assert resolve_normalized_type(engine="postgresql", data_type="money") == "decimal"
    assert resolve_normalized_type(engine="mssql", data_type="smallmoney") == "decimal"
    assert resolve_normalized_type(engine="oracle", data_type="number") == "decimal"
    assert resolve_normalized_type(engine="postgresql", data_type="float8") == "number"
    assert ("postgresql", "numeric", "decimal") in PRODUCT_TYPE_MAPPING_SEEDS


def test_attribute_from_dict_requires_type_and_config() -> None:
    attr = attribute_from_dict(
        {
            "name": "sku",
            "type": "string",
            "required": True,
            "unique": True,
            "config": {"max_length": 32},
        }
    )
    assert attr.type == "string"
    assert attr.max_length == 32
    assert attr.unique is True
    with pytest.raises(KeyError):
        attribute_from_dict({"name": "sku", "normalized_type": "string"})


def test_malformed_enumeration_and_precision_fail_hydration() -> None:
    ignored = attribute_from_dict(
        {
            "name": "status",
            "type": "dictionary",
            "config": {"entries": "ACTIVE"},
        }
    )
    assert ignored.dictionary_id is None
    bound = attribute_from_dict(
        {
            "name": "status",
            "type": "dictionary",
            "config": {"dictionary_id": "cl_status", "entries": [{"code": "ACTIVE"}]},
        }
    )
    assert bound.dictionary_id == "cl_status"
    with pytest.raises(TypeError):
        attribute_from_dict(
            {
                "name": "status",
                "type": "dictionary",
                "config": {"dictionary_id": 1},
            }
        )
    with pytest.raises(TypeError):
        attribute_from_dict(
            {
                "name": "amount",
                "type": "decimal",
                "config": {"precision": True, "scale": 2},
            }
        )


def test_string_max_length_and_text_and_decimal() -> None:
    with pytest.raises(EntityAttributeInvalid, match="max_length"):
        validate_shape(
            attributes=[
                AttributeRecord(name="sku", type="string", required=False),
            ]
        )
    cleaned = validate_shape(
        attributes=[
            AttributeRecord(name="sku", type="string", required=False, max_length=32),
        ]
    )
    assert cleaned[0].max_length == 32
    with pytest.raises(EntityAttributeInvalid, match="65535"):
        validate_shape(
            attributes=[
                AttributeRecord(
                    name="sku", type="string", required=False, max_length=65536
                ),
            ]
        )
    text = validate_shape(
        attributes=[AttributeRecord(name="notes", type="text", required=False)]
    )
    assert text[0].type == "text"
    with pytest.raises(EntityAttributeInvalid, match="rejects config"):
        validate_shape(
            attributes=[
                AttributeRecord(name="notes", type="text", required=False, max_length=10),
            ]
        )
    with pytest.raises(EntityAttributeInvalid, match="precision and scale"):
        validate_shape(
            attributes=[AttributeRecord(name="amount", type="decimal", required=False)]
        )
    decimal = validate_shape(
        attributes=[
            AttributeRecord(
                name="amount",
                type="decimal",
                required=False,
                precision=10,
                scale=2,
            )
        ]
    )
    assert decimal[0].precision == 10


def test_json_requires_empty_config_and_maps_to_jsonb() -> None:
    cleaned = validate_shape(
        attributes=[AttributeRecord(name="payload", type="json", required=False)]
    )
    assert cleaned[0].type == "json"
    assert attribute_to_dict(cleaned[0])["config"] == {}
    with pytest.raises(EntityAttributeInvalid, match="rejects config"):
        validate_shape(
            attributes=[
                AttributeRecord(
                    name="payload", type="json", required=False, max_length=10
                ),
            ]
        )
    column = column_sql(cleaned[0], table="material")
    assert column.split()[1] == "JSONB"
    statements = create_table_statements("public", "material", cleaned)
    assert "JSONB" in statements[0]


def test_enumeration_is_its_own_type() -> None:
    cleaned = validate_shape(
        attributes=[
            AttributeRecord(
                name="status",
                type="dictionary",
                required=True,
                dictionary_id="cl_status",
            )
        ]
    )
    assert cleaned[0].dictionary_id == "cl_status"
    assert attribute_to_dict(cleaned[0])["config"] == {"dictionary_id": "cl_status"}
    with pytest.raises(EntityAttributeInvalid, match="dictionary_id"):
        validate_shape(
            attributes=[
                AttributeRecord(name="status", type="dictionary", required=False)
            ]
        )
    with pytest.raises(EntityAttributeInvalid, match="rejects config"):
        validate_shape(
            attributes=[
                AttributeRecord(
                    name="sku",
                    type="string",
                    required=False,
                    max_length=32,
                    dictionary_id="cl_status",
                )
            ]
        )


def test_ddl_string_text_decimal_reference_and_enumeration() -> None:
    string_attr = AttributeRecord(
        name="sku", type="string", required=True, max_length=32
    )
    text_attr = AttributeRecord(name="notes", type="text", required=False)
    decimal_attr = AttributeRecord(
        name="amount", type="decimal", required=False, precision=12, scale=2
    )
    ref = AttributeRecord(
        name="supplier_id",
        type="reference",
        required=False,
        indexed=True,
        target_entity_id="ent_supplier",
    )
    enum_attr = AttributeRecord(
        name="status",
        type="dictionary",
        required=True,
        dictionary_id="cl_status",
        codes=("ACTIVE",),
    )
    assert "VARCHAR(32)" in column_sql(string_attr, table="material")
    assert column_sql(text_attr, table="material").split()[1] == "TEXT"
    assert "NUMERIC(12,2)" in column_sql(decimal_attr, table="material")
    assert "BIGINT" in column_sql(ref, table="material")
    enum_sql = column_sql(enum_attr, table="material")
    assert "VARCHAR(64)" in enum_sql
    assert "CHECK" in enum_sql
    assert "'ACTIVE'" in enum_sql
    statements = create_table_statements(
        "public", "material", [string_attr, text_attr, decimal_attr, ref, enum_attr]
    )
    assert len(statements) == 2
    assert "CREATE INDEX" in statements[1]


def test_classifier_type_precision_enumeration_target() -> None:
    before = DefinitionShape(
        attributes=(
            AttributeRecord(name="qty", type="integer", required=False),
            AttributeRecord(
                name="status",
                type="dictionary",
                required=False,
                dictionary_id="cl_status",
                codes=("a",),
            ),
            AttributeRecord(
                name="supplier_id",
                type="reference",
                required=False,
                target_entity_id="ent_supplier",
            ),
        )
    )
    decimal = DefinitionShape(
        attributes=(
            AttributeRecord(
                name="qty",
                type="decimal",
                required=False,
                precision=10,
                scale=2,
            ),
            AttributeRecord(
                name="status",
                type="dictionary",
                required=False,
                dictionary_id="cl_status",
                codes=("a",),
            ),
            AttributeRecord(
                name="supplier_id",
                type="reference",
                required=False,
                target_entity_id="ent_supplier",
            ),
        )
    )
    assert classify_shapes(before, decimal).change_class == "breaking"
    added = DefinitionShape(
        attributes=(
            AttributeRecord(name="qty", type="integer", required=False),
            AttributeRecord(
                name="status",
                type="dictionary",
                required=False,
                dictionary_id="cl_status",
                codes=("a", "b"),
            ),
            AttributeRecord(
                name="supplier_id",
                type="reference",
                required=False,
                target_entity_id="ent_supplier",
            ),
        )
    )
    assert classify_shapes(before, added).change_class == "non_breaking"
    retarget = DefinitionShape(
        attributes=(
            AttributeRecord(name="qty", type="integer", required=False),
            AttributeRecord(
                name="status",
                type="dictionary",
                required=False,
                dictionary_id="cl_status",
                codes=("a",),
            ),
            AttributeRecord(
                name="supplier_id",
                type="reference",
                required=False,
                target_entity_id="ent_party",
            ),
        )
    )
    assert classify_shapes(before, retarget).change_class == "breaking"


def test_reference_create_inbound_and_self_ref(client: TestClient) -> None:
    supplier = client.post(
        "/entities",
        json=_create(table_name="supplier", name="Supplier", attributes=[]),
    )
    assert supplier.status_code == 201, supplier.text
    supplier_id = supplier.json()["entity"]["id"]

    material = client.post(
        "/entities",
        json=_create(
            table_name="material",
            attributes=[
                _value(name="sku"),
                _reference(config={"target_entity_id": supplier_id}),
            ],
        ),
    )
    assert material.status_code == 201, material.text
    material_id = material.json()["entity"]["id"]

    listed = client.get("/entities")
    assert listed.status_code == 200
    for item in listed.json()["items"]:
        assert "inbound_references" not in item

    got = client.get(f"/entities/{supplier_id}")
    assert got.status_code == 200
    assert got.json()["entity"]["inbound_references"] == [
        {
            "entity_id": material_id,
            "table_name": "material",
            "attribute_name": "supplier_id",
        }
    ]

    self_ref = client.patch(
        f"/entities/{material_id}",
        json={
            "attributes": [
                _value(name="sku"),
                _reference(name="parent_id", config={"target_entity_id": "self"}),
            ]
        },
    )
    assert self_ref.status_code == 200, self_ref.text
    got_self = client.get(f"/entities/{material_id}")
    assert {
        "entity_id": material_id,
        "table_name": "material",
        "attribute_name": "parent_id",
    } in got_self.json()["entity"]["inbound_references"]


def test_reference_target_must_exist_and_not_be_deprecated(client: TestClient) -> None:
    missing = client.post(
        "/entities",
        json=_create(
            table_name="material",
            attributes=[
_reference()
            ],
        ),
    )
    assert missing.status_code == 422
    assert missing.json()["code"] == "ENTITY_ATTRIBUTE_INVALID"
    assert "does not name an existing entity" in missing.json()["detail"]

    supplier = client.post(
        "/entities",
        json=_create(table_name="supplier", name="Supplier", attributes=[_value()]),
    )
    assert supplier.status_code == 201, supplier.text
    supplier_body = supplier.json()["entity"]
    published = client.post(
        f"/entities/{supplier_body['id']}/versions/"
        f"{supplier_body['current_version']['id']}/publish"
    )
    assert published.status_code in (200, 201), published.text
    deprecated = client.post(f"/entities/{supplier_body['id']}/deprecate")
    assert deprecated.status_code == 200, deprecated.text

    blocked = client.post(
        "/entities",
        json=_create(
            table_name="material",
            attributes=[
                _reference(config={"target_entity_id": supplier_body["id"]}),
            ],
        ),
    )
    assert blocked.status_code == 422
    assert blocked.json()["code"] == "ENTITY_ATTRIBUTE_INVALID"
    assert "deprecated" in blocked.json()["detail"]


def test_missing_type_is_attribute_invalid(client: TestClient) -> None:
    missing = client.post(
        "/entities",
        json=_create(
            attributes=[
                {
                    "name": "sku",
                    "required": False,
                    "config": {"max_length": 32},
                }
            ]
        ),
    )
    assert missing.status_code == 422
    assert missing.json()["code"] == "ENTITY_ATTRIBUTE_INVALID"


def test_inbound_rejects_on_write_and_forbidden_kinds(client: TestClient) -> None:
    bad_inbound = client.post(
        "/entities",
        json=_create(inbound_references=[]),
    )
    assert bad_inbound.status_code == 422
    assert bad_inbound.json()["code"] == "REQUEST_INVALID"

    bad_kind = client.post(
        "/entities",
        json=_create(
            attributes=[{"type": "many2one", "name": "x", "required": False, "config": {}}]
        ),
    )
    assert bad_kind.status_code == 422
    assert bad_kind.json()["code"] == "ENTITY_ATTRIBUTE_INVALID"

    bad_inverse = client.post(
        "/entities",
        json=_create(
            attributes=[
                {
                    "name": "x",
                    "type": "string",
                    "config": {"max_length": 32},
                    "inverse_attribute": "y",
                }
            ]
        ),
    )
    assert bad_inverse.status_code == 422
    assert bad_inverse.json()["code"] == "ENTITY_ATTRIBUTE_INVALID"


def test_top_level_entries_is_attribute_invalid(client: TestClient) -> None:
    created = client.post("/entities", json=_create())
    assert created.status_code == 201, created.text
    entity = created.json()["entity"]
    version_id = entity["current_version"]["id"]
    attribute = {**_value(), "entries": [{"code": "open"}]}

    posted = client.post(
        "/entities",
        json=_create(table_name="sku_item", attributes=[attribute]),
    )
    assert posted.status_code == 422
    assert posted.json()["code"] == "ENTITY_ATTRIBUTE_INVALID"
    assert posted.json()["detail"] == "Attribute field 'entries' is not accepted"

    patched = client.patch(
        f"/entities/{entity['id']}/versions/{version_id}",
        json={"attributes": [attribute]},
    )
    assert patched.status_code == 422
    assert patched.json()["code"] == "ENTITY_ATTRIBUTE_INVALID"
    assert patched.json()["detail"] == "Attribute field 'entries' is not accepted"


def test_entity_referenced_blocks_deprecate_and_delete_not_publish(
    client: TestClient,
) -> None:
    target = client.post(
        "/entities",
        json=_create(table_name="supplier", name="Supplier", attributes=[_value()]),
    ).json()["entity"]
    client.post(
        "/entities",
        json=_create(
            table_name="material",
            attributes=[
                _reference(config={"target_entity_id": target["id"]}),
            ],
        ),
    )

    delete_blocked = client.delete(f"/entities/{target['id']}")
    assert delete_blocked.status_code == 409
    assert delete_blocked.json()["code"] == "ENTITY_REFERENCED"

    published = client.post(
        f"/entities/{target['id']}/versions/{target['current_version']['id']}/publish"
    )
    assert published.status_code in (200, 201), published.text

    deprecate_blocked = client.post(f"/entities/{target['id']}/deprecate")
    assert deprecate_blocked.status_code == 409
    assert deprecate_blocked.json()["code"] == "ENTITY_REFERENCED"


def test_historical_reference_does_not_block_or_count(client: TestClient) -> None:
    target = client.post(
        "/entities",
        json=_create(table_name="supplier", name="Supplier", attributes=[_value()]),
    ).json()["entity"]
    referring = client.post(
        "/entities",
        json=_create(
            table_name="material",
            attributes=[
                _reference(config={"target_entity_id": target["id"]}),
            ],
        ),
    ).json()["entity"]

    cleared = client.patch(
        f"/entities/{referring['id']}",
        json={"attributes": [_value(name="sku")]},
    )
    assert cleared.status_code == 200, cleared.text

    got = client.get(f"/entities/{target['id']}")
    assert got.json()["entity"]["inbound_references"] == []
    deleted = client.delete(f"/entities/{target['id']}")
    assert deleted.status_code == 204


def test_self_reference_blocks_delete(client: TestClient) -> None:
    created = client.post(
        "/entities",
        json=_create(
            table_name="node",
            attributes=[
                _reference(name="parent_id", config={"target_entity_id": "self"})
            ],
        ),
    )
    assert created.status_code == 201, created.text
    entity_id = created.json()["entity"]["id"]
    blocked = client.delete(f"/entities/{entity_id}")
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "ENTITY_REFERENCED"


def test_self_reference_is_stored_as_entity_id(client: TestClient) -> None:
    created = client.post(
        "/entities",
        json=_create(
            table_name="node",
            name="Node",
            attributes=[
                _value(name="sku"),
                _reference(name="parent_id", config={"target_entity_id": "self"}),
            ],
        ),
    )
    assert created.status_code == 201, created.text
    entity = created.json()["entity"]
    version = client.get(
        f"/entities/{entity['id']}/versions/{entity['current_version']['id']}"
    )
    assert version.status_code == 200, version.text
    attributes = version.json()["version"]["attributes"]
    assert "target" not in attributes[0]
    reference = attributes[1]
    assert reference["config"] == {"target_entity_id": entity["id"]}
    assert reference["target"] == {
        "entity_id": entity["id"],
        "name": "Node",
        "table_name": "node",
    }
    classified = client.post(
        f"/entities/{entity['id']}/classify",
        json={
            "attributes": [
                _value(name="sku"),
                _reference(name="parent_id", config={"target_entity_id": "self"}),
            ]
        },
    )
    assert classified.status_code == 200, classified.text
    assert classified.json()["class"] == "unchanged"


def test_target_table_name_config_is_rejected(client: TestClient) -> None:
    rejected = client.post(
        "/entities",
        json=_create(
            attributes=[
                _reference(config={"target_table_name": "supplier"}),
            ]
        ),
    )
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "ENTITY_ATTRIBUTE_INVALID"


def test_attribute_payload_omits_target_from_storage() -> None:
    stored = attribute_to_dict(
        AttributeRecord(
            name="parent_id",
            type="reference",
            required=False,
            target_entity_id="ent_supplier",
        )
    )
    assert stored["config"] == {"target_entity_id": "ent_supplier"}
    assert "target" not in stored
    store = MemoryEntityStore()
    missing = attribute_payload(
        store,
        AttributeRecord(
            name="parent_id",
            type="reference",
            required=False,
            target_entity_id="ent_missing",
        ),
    )
    assert missing["target"] is None
    plain = attribute_payload(
        store,
        AttributeRecord(name="sku", type="string", required=False, max_length=32),
    )
    assert "target" not in plain


def _accepted_snapshot() -> list[AttributeRecord]:
    return [
        AttributeRecord(name="code", type="string", required=False, max_length=32),
        AttributeRecord(
            name="parent", type="reference", required=False, target_entity_id=None
        ),
    ]


def _changed_snapshot() -> list[AttributeRecord]:
    return [
        *_accepted_snapshot(),
        AttributeRecord(name="notes", type="text", required=False),
    ]


def _plant_snapshot(
    *,
    table_name: str,
    attributes: list[AttributeRecord],
    published: bool,
    successor: list[AttributeRecord] | None = None,
) -> tuple[str, str]:
    now = utc_now()
    entity_id = new_entity_id()
    version_id = new_version_id()
    store = get_entity_store()
    store.create_entity(
        BusinessEntityRecord(
            id=entity_id,
            table_name=table_name,
            name="Probe",
            description="Accepted snapshot.",
            deprecated_at=None,
            created_at=now,
            updated_at=now,
        ),
        EntityVersionRecord(
            id=version_id,
            entity_id=entity_id,
            version=1,
            attributes=list(attributes),
            materialized_attributes=(
                [attribute_to_dict(attr) for attr in attributes] if published else []
            ),
            publish_status=PUBLISHED if published else UNPUBLISHED,
            latest_reconcile_job_id=None,
            created_at=now,
            updated_at=now,
        ),
    )
    current_id = version_id
    if published:
        physical, _comment = compose_physical_table_name(table_name, 1, version_id)
        port = get_entity_table_port()
        port.create_physical_table(
            entity_db_schema(),
            physical,
            list(attributes),
        )
        port.swap_stem_view(
            entity_db_schema(),
            table_name,
            physical=physical,
            expected_target=None,
        )
    if successor is not None:
        current_id = new_version_id()
        store.create_version(
            EntityVersionRecord(
                id=current_id,
                entity_id=entity_id,
                version=2,
                attributes=list(successor),
                materialized_attributes=[],
                publish_status=UNPUBLISHED,
                latest_reconcile_job_id=None,
                created_at=now,
                updated_at=now,
            )
        )
    return entity_id, current_id


def _parent_target(version: dict) -> object:
    parent = next(item for item in version["attributes"] if item["name"] == "parent")
    return parent["config"]["target_entity_id"]


def test_open_version_copies_accepted_reference_without_target(
    client: TestClient,
) -> None:
    omitted_id, _version_id = _plant_snapshot(
        table_name="copy_omitted",
        attributes=_accepted_snapshot(),
        published=True,
    )
    omitted = client.post(f"/entities/{omitted_id}/versions", json={})
    assert omitted.status_code == 201, omitted.text
    assert omitted.json()["version"]["version"] == 2
    assert _parent_target(omitted.json()["version"]) is None

    echoed_id, _echo_version = _plant_snapshot(
        table_name="copy_echo",
        attributes=_accepted_snapshot(),
        published=True,
    )
    echoed = client.post(
        f"/entities/{echoed_id}/versions",
        json={"attributes": [attribute_to_dict(attr) for attr in _accepted_snapshot()]},
    )
    assert echoed.status_code == 201, echoed.text
    assert _parent_target(echoed.json()["version"]) is None


def test_publish_unchanged_successor_keeps_accepted_reference(
    client: TestClient,
) -> None:
    entity_id, _version_id = _plant_snapshot(
        table_name="republish_copy",
        attributes=_accepted_snapshot(),
        published=True,
    )
    opened = client.post(f"/entities/{entity_id}/versions", json={})
    assert opened.status_code == 201, opened.text
    version_id = opened.json()["version"]["id"]
    published = client.post(f"/entities/{entity_id}/versions/{version_id}/publish")
    assert published.status_code == 201, published.text
    assert published.json()["job"]["status"] == "succeeded"
    saved = client.get(f"/entities/{entity_id}/versions/{version_id}")
    assert saved.status_code == 200, saved.text
    assert _parent_target(saved.json()["version"]) is None


def test_changed_shape_still_requires_reference_target(client: TestClient) -> None:
    open_id, _open_version = _plant_snapshot(
        table_name="changed_open",
        attributes=_accepted_snapshot(),
        published=True,
    )
    opened = client.post(
        f"/entities/{open_id}/versions",
        json={"attributes": [attribute_to_dict(attr) for attr in _changed_snapshot()]},
    )
    assert opened.status_code == 422
    assert opened.json()["code"] == "ENTITY_ATTRIBUTE_INVALID"
    assert "target_entity_id" in opened.json()["detail"]

    publish_id, version_id = _plant_snapshot(
        table_name="changed_publish",
        attributes=_accepted_snapshot(),
        published=True,
        successor=_changed_snapshot(),
    )
    published = client.post(f"/entities/{publish_id}/versions/{version_id}/publish")
    assert published.status_code == 422
    assert published.json()["code"] == "ENTITY_ATTRIBUTE_INVALID"
    assert "target_entity_id" in published.json()["detail"]


def test_first_publish_requires_reference_target(client: TestClient) -> None:
    entity_id, version_id = _plant_snapshot(
        table_name="first_publish_ref",
        attributes=_accepted_snapshot(),
        published=False,
    )
    published = client.post(f"/entities/{entity_id}/versions/{version_id}/publish")
    assert published.status_code == 422
    assert published.json()["code"] == "ENTITY_ATTRIBUTE_INVALID"
    assert "target_entity_id" in published.json()["detail"]
