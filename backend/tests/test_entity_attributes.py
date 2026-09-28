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
from backend.entity.present import attribute_payload  # noqa: E402
from backend.entity.records import (  # noqa: E402
    AttributeRecord,
    EnumerationEntry,
    attribute_from_dict,
    attribute_to_dict,
)
from backend.entity.store import MemoryEntityStore  # noqa: E402
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
    with pytest.raises(TypeError):
        attribute_from_dict(
            {
                "name": "status",
                "type": "enumeration",
                "config": {"entries": "ACTIVE"},
            }
        )
    with pytest.raises(KeyError):
        attribute_from_dict(
            {
                "name": "status",
                "type": "enumeration",
                "config": {"entries": [{"label": "Active"}]},
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
                type="enumeration",
                required=True,
                entries=(
                    EnumerationEntry(code="ACTIVE", label="Active"),
                    EnumerationEntry(code="DONE"),
                ),
            )
        ]
    )
    assert [entry.code for entry in cleaned[0].entries or ()] == ["ACTIVE", "DONE"]
    with pytest.raises(EntityAttributeInvalid, match="non-empty"):
        validate_shape(
            attributes=[
                AttributeRecord(name="status", type="enumeration", required=False, entries=())
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
                    entries=(EnumerationEntry(code="x"),),
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
        type="enumeration",
        required=True,
        entries=(EnumerationEntry(code="ACTIVE", label="Active"),),
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
                type="enumeration",
                required=False,
                entries=(EnumerationEntry(code="a", label="A"),),
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
                type="enumeration",
                required=False,
                entries=(EnumerationEntry(code="a", label="A"),),
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
                type="enumeration",
                required=False,
                entries=(
                    EnumerationEntry(code="a", label="A"),
                    EnumerationEntry(code="b", label="B"),
                ),
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
                type="enumeration",
                required=False,
                entries=(EnumerationEntry(code="a", label="A"),),
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
