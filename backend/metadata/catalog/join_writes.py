"""Join edge list and writes (HTTP + MCP)."""

from __future__ import annotations

from typing import Any

from backend.admin.audit import persist_audit_event
from backend.core.time import utc_now
from backend.metadata.catalog.join_origin import HUMAN_JOIN_ORIGIN
from backend.metadata.catalog.join_pair import (
    Inserted,
    PairWriteDecision,
    decide_pair_write,
    pair_state,
)
from backend.metadata.catalog.refs import require_column, require_join
from backend.metadata.catalog.store import (
    CatalogJoinRecord,
    get_catalog_store,
    require_object,
)
from backend.metadata.catalog.views import JoinView, join_view
from backend.metadata.errors import (
    CatalogJoinNotFound,
    JoinAlreadyDefined,
    JoinAlreadyRejected,
    JoinCrossSource,
    JoinDeleteAutomatic,
    JoinEvidenceRequired,
    JoinInvalid,
    JoinNotRejected,
    JoinRejected,
)

_EVIDENCE_AUDIT_MAX = 500


def list_joins(
    object_id: str, *, limit: int | None = None, offset: int = 0
) -> tuple[list[JoinView], int]:
    require_object(object_id)
    records, total = get_catalog_store().list_joins_for_object(
        object_id, limit=limit, offset=offset
    )
    return [join_view(j) for j in records], total


def _validated_pair(
    *,
    from_column_id: str,
    to_column_id: str,
    evidence: str,
    join_kind: str,
    join_expression: str | None,
) -> tuple[str, str, str]:
    cleaned = (evidence or "").strip()
    if not cleaned:
        raise JoinEvidenceRequired()
    if from_column_id == to_column_id:
        raise JoinInvalid()
    from_col = require_column(from_column_id)
    to_col = require_column(to_column_id)
    from_obj = require_object(from_col.object_id)
    to_obj = require_object(to_col.object_id)
    if from_obj.source_id != to_obj.source_id:
        raise JoinCrossSource()
    expression = join_expression
    if expression is None:
        expression = f"{from_col.name} = {to_col.name}"
    kind = (join_kind or "INNER").strip() or "INNER"
    return cleaned, kind, expression


def _audit_join_create(
    *,
    record: CatalogJoinRecord,
    evidence: str,
    attester: str,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> None:
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="catalog_join",
        resource_id=record.id,
        action="join.create",
        result="success",
        detail={
            "from_column_id": record.from_column_id,
            "to_column_id": record.to_column_id,
            "evidence": evidence[:_EVIDENCE_AUDIT_MAX],
            "join_kind": record.join_kind,
            "attester": attester,
        },
    )


def _raise_human_single_refuse(decision: PairWriteDecision) -> None:
    if decision.action == "refuse_defined":
        raise JoinAlreadyDefined(decision.existing_id or "")
    if decision.action == "refuse_rejected":
        raise JoinRejected(decision.existing_id or "")


def create_join(
    *,
    from_column_id: str,
    to_column_id: str,
    evidence: str,
    actor_user_id: str | None,
    actor_token_id: str | None,
    join_kind: str = "INNER",
    join_expression: str | None = None,
    attester: str = HUMAN_JOIN_ORIGIN,
) -> CatalogJoinRecord:
    cleaned, kind, expression = _validated_pair(
        from_column_id=from_column_id,
        to_column_id=to_column_id,
        evidence=evidence,
        join_kind=join_kind,
        join_expression=join_expression,
    )
    store = get_catalog_store()
    existing = store.get_join_by_pair(from_column_id, to_column_id)
    _raise_human_single_refuse(
        decide_pair_write(
            pair_state(existing),
            writer="human_single",
            existing_id=None if existing is None else existing.id,
        )
    )
    result = store.write_insert_join(
        from_column_id=from_column_id,
        to_column_id=to_column_id,
        evidence=cleaned,
        created_by_user_id=actor_user_id,
        join_kind=kind,
        join_expression=expression,
        attester=attester,
    )
    if isinstance(result, Inserted):
        _audit_join_create(
            record=result.record,
            evidence=cleaned,
            attester=attester,
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
        )
        return result.record
    if result.record.is_rejected:
        raise JoinRejected(result.record.id)
    raise JoinAlreadyDefined(result.record.id)


def amend_join(
    *,
    join_id: str,
    evidence: str,
    actor_user_id: str | None,
    actor_token_id: str | None,
    join_kind: str = "INNER",
    join_expression: str | None = None,
) -> CatalogJoinRecord:
    existing = require_join(join_id)
    if existing.is_rejected:
        raise JoinRejected(existing.id)
    cleaned, kind, expression = _validated_pair(
        from_column_id=existing.from_column_id,
        to_column_id=existing.to_column_id,
        evidence=evidence,
        join_kind=join_kind,
        join_expression=join_expression,
    )
    record = get_catalog_store().update_join(
        join_id,
        evidence=cleaned,
        join_kind=kind,
        join_expression=expression,
        actor_user_id=actor_user_id,
    )
    if record is None:
        raise CatalogJoinNotFound()
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="catalog_join",
        resource_id=record.id,
        action="join.patch",
        result="success",
        detail={
            "from_column_id": record.from_column_id,
            "to_column_id": record.to_column_id,
            "evidence": cleaned[:_EVIDENCE_AUDIT_MAX],
            "join_kind": kind,
        },
    )
    return record


def reject_join(
    *,
    join_id: str,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> CatalogJoinRecord:
    existing = require_join(join_id)
    if existing.is_rejected:
        raise JoinAlreadyRejected(existing.id)
    record = get_catalog_store().set_join_rejection(
        join_id,
        rejected_at=utc_now(),
        rejected_by_user_id=actor_user_id,
        actor_user_id=actor_user_id,
    )
    if record is None:
        raise CatalogJoinNotFound()
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="catalog_join",
        resource_id=join_id,
        action="join.reject",
        result="success",
        detail={
            "from_column_id": existing.from_column_id,
            "to_column_id": existing.to_column_id,
        },
    )
    return record


def restore_join(
    *,
    join_id: str,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> CatalogJoinRecord:
    existing = require_join(join_id)
    if not existing.is_rejected:
        raise JoinNotRejected(existing.id)
    record = get_catalog_store().set_join_rejection(
        join_id,
        rejected_at=None,
        rejected_by_user_id=None,
        actor_user_id=actor_user_id,
    )
    if record is None:
        raise CatalogJoinNotFound()
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="catalog_join",
        resource_id=join_id,
        action="join.restore",
        result="success",
        detail={
            "from_column_id": existing.from_column_id,
            "to_column_id": existing.to_column_id,
        },
    )
    return record


def upsert_joins_batch(
    *,
    joins: list[dict[str, Any]],
    actor_user_id: str | None,
    actor_token_id: str | None,
    attester: str = HUMAN_JOIN_ORIGIN,
) -> tuple[list[CatalogJoinRecord], int, int, int]:
    """Create many joins; skip asserted pairs; report rejected pairs; never restore.

    All edges share one Source.
    """
    if not joins:
        return [], 0, 0, 0
    store = get_catalog_store()
    source_id: str | None = None
    created = 0
    known = 0
    rejected = 0
    items: list[CatalogJoinRecord] = []
    for item in joins:
        from_id = str(item["from_column_id"])
        to_id = str(item["to_column_id"])
        from_col = require_column(from_id)
        to_col = require_column(to_id)
        from_obj = require_object(from_col.object_id)
        to_obj = require_object(to_col.object_id)
        if from_obj.source_id != to_obj.source_id:
            raise JoinCrossSource()
        if source_id is None:
            source_id = from_obj.source_id
        elif from_obj.source_id != source_id:
            raise JoinCrossSource()
        existing = store.get_join_by_pair(from_id, to_id)
        decision = decide_pair_write(
            pair_state(existing),
            writer="human_batch",
            existing_id=None if existing is None else existing.id,
        )
        if decision.action == "skip_protected":
            assert existing is not None
            known += 1
            items.append(existing)
            continue
        if decision.action == "skip_rejected":
            assert existing is not None
            rejected += 1
            items.append(existing)
            continue
        cleaned, kind, expression = _validated_pair(
            from_column_id=from_id,
            to_column_id=to_id,
            evidence=str(item.get("evidence") or ""),
            join_kind=str(item.get("join_kind") or "INNER"),
            join_expression=item.get("join_expression"),
        )
        result = store.write_insert_join(
            from_column_id=from_id,
            to_column_id=to_id,
            evidence=cleaned,
            created_by_user_id=actor_user_id,
            join_kind=kind,
            join_expression=expression,
            attester=attester,
        )
        if isinstance(result, Inserted):
            created += 1
            _audit_join_create(
                record=result.record,
                evidence=cleaned,
                attester=attester,
                actor_user_id=actor_user_id,
                actor_token_id=actor_token_id,
            )
        else:
            if result.record.is_rejected:
                rejected += 1
            else:
                known += 1
        items.append(result.record)
    return items, created, known, rejected


def delete_join(
    *,
    join_id: str,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> None:
    existing = require_join(join_id)
    if existing.created_by_user_id is None:
        raise JoinDeleteAutomatic(existing.id)
    if existing.is_rejected:
        raise JoinRejected(existing.id)
    deleted = get_catalog_store().delete_join(join_id)
    if not deleted:
        raise CatalogJoinNotFound()
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="catalog_join",
        resource_id=join_id,
        action="join.delete",
        result="success",
        detail={
            "from_column_id": existing.from_column_id,
            "to_column_id": existing.to_column_id,
        },
    )
