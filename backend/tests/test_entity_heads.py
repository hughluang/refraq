"""Entity head read port."""

from __future__ import annotations

from backend.core.time import utc_now
from backend.entity.heads import get_entity_head
from backend.entity.records import (
    AttributeRecord,
    BusinessEntityRecord,
    EntityVersionRecord,
    attribute_to_stored,
)
from backend.entity.store import get_entity_store


def _entity(entity_id: str) -> BusinessEntityRecord:
    now = utc_now()
    return BusinessEntityRecord(
        id=entity_id,
        table_name=entity_id,
        name="Material",
        description="A material",
        deprecated_at=None,
        created_at=now,
        updated_at=now,
    )


def _version(
    *,
    version_id: str,
    entity_id: str,
    version: int,
    status: str,
    attributes: list[AttributeRecord],
    materialized: list[AttributeRecord] | None = None,
) -> EntityVersionRecord:
    now = utc_now()
    return EntityVersionRecord(
        id=version_id,
        entity_id=entity_id,
        version=version,
        attributes=attributes,
        materialized_attributes=[
            attribute_to_stored(attr) for attr in (materialized or [])
        ],
        publish_status=status,
        latest_reconcile_job_id=None,
        created_at=now,
        updated_at=now,
    )


def test_missing_and_unpublished_have_no_head() -> None:
    assert get_entity_head("ent_missing") is None
    store = get_entity_store()
    draft = AttributeRecord(name="sku", type="string", unique=True, business_key=True)
    store.create_entity(
        _entity("ent_draft"),
        _version(
            version_id="ver_draft",
            entity_id="ent_draft",
            version=1,
            status="unpublished",
            attributes=[draft],
        ),
    )
    assert get_entity_head("ent_draft") is None


def test_head_is_latest_published_snapshot() -> None:
    sku = AttributeRecord(
        name="sku",
        type="string",
        required=True,
        unique=True,
        business_key=True,
        max_length=32,
    )
    title = AttributeRecord(name="title", type="string", max_length=32)
    store = get_entity_store()
    store.create_entity(
        _entity("ent_live"),
        _version(
            version_id="ver_1",
            entity_id="ent_live",
            version=1,
            status="published",
            attributes=[AttributeRecord(name="draft_only", type="string")],
            materialized=[sku, title],
        ),
    )
    store.create_version(
        _version(
            version_id="ver_2",
            entity_id="ent_live",
            version=2,
            status="unpublished",
            attributes=[AttributeRecord(name="next", type="string", business_key=True)],
        )
    )
    head = get_entity_head("ent_live")
    assert head is not None
    by_name = {attr.name: attr for attr in head.attributes}
    assert set(by_name) == {"sku", "title"}
    assert by_name["sku"].business_key is True
    assert by_name["sku"].unique is True
    assert by_name["title"].business_key is False
