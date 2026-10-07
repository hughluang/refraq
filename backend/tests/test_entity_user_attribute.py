"""The user Attribute Type: physical column, write check, display, filters."""

from __future__ import annotations

import pytest

from backend.admin.security import hash_password
from backend.admin.user_store import get_user_store
from backend.core.time import utc_now
from backend.entity.attribute_type import resolve
from backend.entity.classify import classify_shapes
from backend.entity.data.filters import compile_filters
from backend.entity.data.head import HeadTarget
from backend.entity.data.values import (
    decode_row,
    encode_inbound_map,
)
from backend.entity.ddl import column_sql
from backend.entity.errors import EntityAttributeInvalid, EntityRowInvalid
from backend.entity.records import (
    AttributeRecord,
    BusinessEntityRecord,
    EntityVersionRecord,
)
from backend.entity.validate import validate_shape


def _user_attr(**overrides: object) -> AttributeRecord:
    body = {"name": "owner", "type": "user", "required": False}
    body.update(overrides)
    return AttributeRecord(**body)  # type: ignore[arg-type]


def _target(attr: AttributeRecord) -> HeadTarget:
    now = utc_now()
    entity = BusinessEntityRecord(
        id="ent_people",
        table_name="people",
        name="People",
        description="",
        deprecated_at=None,
        created_at=now,
        updated_at=now,
    )
    head = EntityVersionRecord(
        id="ver_1",
        entity_id=entity.id,
        version=1,
        attributes=[attr],
        materialized_attributes=[],
        publish_status="published",
        latest_reconcile_job_id=None,
        created_at=now,
        updated_at=now,
    )
    return HeadTarget(
        entity=entity,
        head=head,
        attributes=(attr,),
        physical_table="people__v1__0123456789abcdef",
        qualified_table='"entity_data"."people__v1__0123456789abcdef"',
        writable=True,
    )


def test_user_column_is_varchar_64_and_not_a_business_key() -> None:
    attr = _user_attr(required=True, unique=True, indexed=True)
    sql = column_sql(attr, table="people")
    assert "VARCHAR(64)" in sql
    assert "NOT NULL" in sql
    assert resolve("user").operators == ("eq", "ne", "in", "is_null")
    with pytest.raises(EntityAttributeInvalid, match="business_key"):
        validate_shape(attributes=[_user_attr(business_key=True, unique=True, required=True)])
    classified = classify_shapes(
        [AttributeRecord(name="owner", type="string", required=False, max_length=32)],
        [_user_attr()],
        versions=[],
    )
    assert classified.change_class == "breaking"
    assert classified.changes[0].field == "attributes.owner.type"


def test_user_write_requires_an_existing_user() -> None:
    ada = get_user_store().create_user(
        account="ada",
        display_name="Ada Lovelace",
        password_hash=hash_password("ada-pass"),
        role_id=None,
        status="disabled",
    )
    target = _target(_user_attr())
    encoded = encode_inbound_map({"owner": ada.id}, target, partial=True)
    assert encoded == {"owner": ada.id}
    row = decode_row(["owner"], (ada.id,), target)
    assert row == {"owner": ada.id}
    with pytest.raises(EntityRowInvalid, match="do not name a User"):
        encode_inbound_map({"owner": "user_gone"}, target, partial=True)


def test_user_filters_allow_eq_ne_in_is_null_including_a_historical_id() -> None:
    target = _target(_user_attr())
    compiled = compile_filters(
        {"field": "owner", "op": "eq", "value": "user_gone"},
        target,
    )
    assert compiled is not None
    assert compiled.sql == '"owner" = :f1'
    assert compiled.params == {"f1": "user_gone"}
    listed = compile_filters(
        {"field": "owner", "op": "in", "value": ["user_a", "user_b"]},
        target,
    )
    assert listed is not None
    assert "IN" in listed.sql
    nulls = compile_filters({"field": "owner", "op": "is_null"}, target)
    assert nulls is not None
    assert nulls.sql == '"owner" IS NULL'
    with pytest.raises(EntityRowInvalid, match="not allowed"):
        compile_filters(
            {"field": "owner", "op": "gt", "value": "user_a"},
            target,
        )
    with pytest.raises(EntityRowInvalid, match="contains"):
        compile_filters(
            {"field": "owner", "op": "contains", "value": "ada"},
            target,
        )
