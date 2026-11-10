"""Entity definition text projected for the shared embedding call."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.admin.model_services import embed_texts, get_embedding_runtime
from backend.admin.model_services.records import CURRENT_PROCESSING_CONTRACT
from backend.core.config import get_settings
from backend.core.db import Base, session_scope
from backend.core.time import UtcDateTime, utc_now
from backend.entity.errors import EntityNotFound, EntityNotServing
from backend.entity.lifecycle import latest_published_of
from backend.entity.store import get_entity_store
from backend.tags.api import (
    KIND_ENTITY,
    bind_entity_assignment_listener,
    bind_tag_rename_listener,
    list_subject_ids,
    read_assignment,
)


def definition_text(
    *,
    table_name: str,
    name: str,
    description: str,
    tag_names: Sequence[str],
) -> str:
    """Stable definition text. ``tag_names`` are already in assignment order.

    Blank parts are omitted. Tag descriptions and anything outside these
    fields are not accepted here.
    """

    parts: list[str] = []
    for raw in (table_name, name, description, *tag_names):
        text = raw.strip()
        if text:
            parts.append(text)
    return "\n".join(parts)


def canonical_text(entity_id: str) -> str:
    """Definition text for one entity, tags in ``(name_key, id)`` assignment order."""

    entity = get_entity_store().get_entity(entity_id)
    if entity is None:
        raise EntityNotFound()
    assignment = read_assignment(KIND_ENTITY, entity_id)
    return definition_text(
        table_name=entity.table_name,
        name=entity.name,
        description=entity.description,
        tag_names=tuple(tag.name for tag in assignment.tags),
    )


@dataclass(frozen=True, slots=True)
class EntityProjection:
    entity_id: str
    head_version_id: str
    content_hash: str
    generation: int
    processing_contract: str
    embedding: tuple[float, ...]


class EntityEmbeddingRow(Base):
    """One current vector for an Entity, on the platform metadata database."""

    __tablename__ = "entity_embeddings"

    entity_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("business_entities.id", ondelete="CASCADE"),
        primary_key=True,
    )
    head_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    processing_contract: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list] = mapped_column(VECTOR(), nullable=False)
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False)
    indexed_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


_rows: dict[str, EntityProjection] = {}


def reset_entity_projection_store() -> None:
    """Drop the memory adapter. The metadata table is left for the caller to truncate."""

    _rows.clear()


def _sql_backend() -> bool:
    return get_settings().store_backend == "persistent"


def _digest(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _serving_head_id(entity_id: str) -> str | None:
    entity = get_entity_store().get_entity(entity_id)
    if entity is None or entity.deprecated_at is not None:
        return None
    head = latest_published_of(get_entity_store().list_all_versions(entity_id))
    if head is None:
        return None
    return head.id


def current_projection(entity_id: str) -> EntityProjection | None:
    """The retained row. Definition changes delete it instead of masking it."""

    if not _sql_backend():
        return _rows.get(entity_id)
    with session_scope() as session:
        row = session.get(EntityEmbeddingRow, entity_id)
        if row is None:
            return None
        return EntityProjection(
            entity_id=row.entity_id,
            head_version_id=row.head_version_id,
            content_hash=row.content_hash,
            generation=int(row.generation),
            processing_contract=row.processing_contract,
            embedding=tuple(float(item) for item in row.embedding),
        )


def _save(record: EntityProjection) -> None:
    if not _sql_backend():
        _rows[record.entity_id] = record
        return
    with session_scope() as session:
        row = session.get(EntityEmbeddingRow, record.entity_id)
        embedding = list(record.embedding)
        if row is None:
            session.add(
                EntityEmbeddingRow(
                    entity_id=record.entity_id,
                    head_version_id=record.head_version_id,
                    content_hash=record.content_hash,
                    generation=record.generation,
                    processing_contract=record.processing_contract,
                    embedding=embedding,
                    embedding_dim=len(embedding),
                    indexed_at=utc_now(),
                )
            )
        else:
            row.head_version_id = record.head_version_id
            row.content_hash = record.content_hash
            row.generation = record.generation
            row.processing_contract = record.processing_contract
            row.embedding = embedding
            row.embedding_dim = len(embedding)
            row.indexed_at = utc_now()
        session.flush()


def drop_entity_projection(entity_id: str) -> None:
    """Forget the retained vector. Does not call the embedding endpoint."""

    if not _sql_backend():
        _rows.pop(entity_id, None)
        return
    with session_scope() as session:
        row = session.get(EntityEmbeddingRow, entity_id)
        if row is not None:
            session.delete(row)
            session.flush()


def _drop_entities_using_tag(tag_id: str) -> None:
    for entity_id in list_subject_ids(kind=KIND_ENTITY, tag_ids=[tag_id]):
        drop_entity_projection(entity_id)


bind_entity_assignment_listener(drop_entity_projection)
bind_tag_rename_listener(_drop_entities_using_tag)


def retain_projection(
    *,
    entity_id: str,
    head_version_id: str,
    content_hash: str,
    generation: int,
    processing_contract: str,
    embedding: Sequence[float],
) -> EntityProjection | None:
    """Store a vector row when its head is the latest published head.

    A write for an older head leaves the current row unchanged.
    """

    if head_version_id != _serving_head_id(entity_id):
        return None
    if content_hash != _digest(canonical_text(entity_id)):
        return None
    if processing_contract != CURRENT_PROCESSING_CONTRACT:
        return None
    runtime = get_embedding_runtime()
    if runtime is not None and generation != runtime.generation:
        return None
    existing = current_projection(entity_id)
    if existing is not None and generation < existing.generation:
        return None
    saved = EntityProjection(
        entity_id=entity_id,
        head_version_id=head_version_id,
        content_hash=content_hash,
        generation=generation,
        processing_contract=processing_contract,
        embedding=tuple(float(item) for item in embedding),
    )
    _save(saved)
    return saved


def embed_entity(entity_id: str) -> EntityProjection:
    """Submit one serving entity's canonical text and retain the returned vector."""

    head_id = _serving_head_id(entity_id)
    if head_id is None:
        raise EntityNotServing()
    text = canonical_text(entity_id)
    runtime = get_embedding_runtime()
    generation = runtime.generation if runtime is not None else 0
    result = embed_texts([text], expected_generation=generation)
    saved = retain_projection(
        entity_id=entity_id,
        head_version_id=head_id,
        content_hash=_digest(text),
        generation=result.space.generation,
        processing_contract=result.space.processing_contract,
        embedding=result.vectors[0],
    )
    if saved is None:
        raise EntityNotServing()
    return saved
