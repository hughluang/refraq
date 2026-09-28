"""Project Business Entity records into contract shapes."""

from __future__ import annotations

from typing import Any

from backend.entity.lifecycle import PUBLISHED, ever_published
from backend.entity.records import (
    AttributeRecord,
    BusinessEntityRecord,
    EntityVersionRecord,
    attribute_to_dict,
    snapshot_signature,
)
from backend.entity.store import EntityStore, get_entity_store
from backend.jobs.store import JobRecord, get_job_store

__all__ = [
    "alignment_state",
    "archived_table_name",
    "current_version_of",
    "definition_ahead",
    "entity_out",
    "inbound_references_for",
    "latest_published_of",
    "occupies_live_table",
    "physical_table_name",
    "table_present",
    "version_out",
]


def archived_table_name(stem: str, version: int) -> str:
    return f"{stem}__rfq_v{version}"


def table_present(version: EntityVersionRecord) -> bool:
    return bool(version.materialized_attributes)


def latest_published_of(
    versions: list[EntityVersionRecord],
) -> EntityVersionRecord | None:
    published = [item for item in versions if item.publish_status == PUBLISHED]
    if not published:
        return None
    return max(published, key=lambda item: (item.version, item.id))


def physical_table_name(
    *,
    stem: str,
    version: EntityVersionRecord,
    latest_published: EntityVersionRecord | None,
) -> str | None:
    if not table_present(version):
        return None
    if latest_published is not None and version.id == latest_published.id:
        return stem
    return archived_table_name(stem, version.version)


def occupies_live_table(
    version: EntityVersionRecord,
    latest_published: EntityVersionRecord | None,
) -> bool:
    return (
        table_present(version)
        and latest_published is not None
        and version.id == latest_published.id
    )


def definition_ahead(version: EntityVersionRecord) -> bool:
    if not version.materialized_attributes:
        return True
    return snapshot_signature(version.materialized_attributes) != snapshot_signature(
        [attribute_to_dict(attr) for attr in version.attributes]
    )


def alignment_state(version: EntityVersionRecord) -> dict[str, Any]:
    job = _latest_reconcile_job(version)
    return {
        "table_present": table_present(version),
        "definition_ahead": definition_ahead(version),
        "latest_job_id": version.latest_reconcile_job_id,
        "latest_job_status": job.status if job is not None else None,
    }


def current_version_of(
    versions: list[EntityVersionRecord],
) -> EntityVersionRecord | None:
    if not versions:
        return None
    return max(versions, key=lambda item: (item.version, item.id))


def inbound_references_for(
    store: EntityStore, target_entity_id: str
) -> list[dict[str, str]]:
    """Current-version Entity References aimed at ``target_entity_id``."""
    found: list[dict[str, str]] = []
    for entity in store.list_all_entities():
        current = store.current_version(entity.id)
        if current is None:
            continue
        for attr in current.attributes:
            if attr.type != "reference":
                continue
            if attr.target_entity_id != target_entity_id:
                continue
            found.append(
                {
                    "entity_id": entity.id,
                    "table_name": entity.table_name,
                    "attribute_name": attr.name,
                }
            )
    found.sort(key=lambda item: (item["table_name"], item["attribute_name"]))
    return found


def attribute_payload(store: EntityStore, attr: AttributeRecord) -> dict[str, Any]:
    """Stored attribute shape, plus a read-only ``target`` on references."""
    payload = attribute_to_dict(attr)
    if attr.type != "reference":
        return payload
    payload["target"] = _reference_target(store, attr.target_entity_id)
    return payload


def _reference_target(
    store: EntityStore, entity_id: str | None
) -> dict[str, str] | None:
    if not entity_id:
        return None
    entity = store.get_entity(entity_id)
    if entity is None:
        return None
    return {
        "entity_id": entity.id,
        "name": entity.name,
        "table_name": entity.table_name,
    }


def entity_out(
    entity: BusinessEntityRecord,
    *,
    current: EntityVersionRecord | None,
    include_inbound_references: bool = False,
) -> dict[str, Any]:
    store = get_entity_store()
    versions = store.list_all_versions(entity.id)
    latest = latest_published_of(versions)
    current_payload: dict[str, Any] | None = None
    if current is not None:
        current_payload = {
            "id": current.id,
            "version": current.version,
            "publish_status": current.publish_status,
            "table_name": physical_table_name(
                stem=entity.table_name,
                version=current,
                latest_published=latest,
            ),
            "alignment": alignment_state(current),
        }
    payload: dict[str, Any] = {
        "id": entity.id,
        "table_name": entity.table_name,
        "name": entity.name,
        "description": entity.description,
        "deprecated_at": entity.deprecated_at,
        "ever_published": ever_published(versions),
        "current_version": current_payload,
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
    }
    if include_inbound_references:
        payload["inbound_references"] = inbound_references_for(store, entity.id)
    return payload


def version_out(
    version: EntityVersionRecord,
    *,
    entity: BusinessEntityRecord,
    include_attributes: bool,
    latest_published: EntityVersionRecord | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": version.id,
        "entity_id": entity.id,
        "version": version.version,
        "publish_status": version.publish_status,
        "table_name": physical_table_name(
            stem=entity.table_name,
            version=version,
            latest_published=latest_published,
        ),
        "alignment": alignment_state(version),
        "created_at": version.created_at,
        "updated_at": version.updated_at,
    }
    if include_attributes:
        store = get_entity_store()
        payload["attributes"] = [
            attribute_payload(store, attr) for attr in version.attributes
        ]
    else:
        payload["attribute_count"] = len(version.attributes)
    return payload


def _latest_reconcile_job(version: EntityVersionRecord) -> JobRecord | None:
    job_id = version.latest_reconcile_job_id
    if not job_id:
        return None
    return get_job_store().get(job_id)
