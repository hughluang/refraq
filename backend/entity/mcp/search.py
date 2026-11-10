"""search_entities. Importing this module registers the tool."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from mcp.types import ToolAnnotations
from sqlalchemy import bindparam, text

from backend.admin.model_services import embed_texts, get_embedding_runtime
from backend.admin.model_services.errors import (
    ModelServiceClosed,
    ModelServiceControlRevisionMismatch,
    ModelServiceEndpointMissing,
    ModelServiceGenerationMismatch,
    ModelServiceNotInUse,
)
from backend.admin.model_services.records import (
    CURRENT_PROCESSING_CONTRACT,
    EmbeddingRuntime,
)
from backend.core.db import session_scope
from backend.entity.access.membership import person_of, readable_entity_ids
from backend.entity.embed_jobs.index_state import get_entity_index_store
from backend.entity.errors import (
    EntityIndexNotReady,
    EntityRequestInvalid,
    EntitySearchEmbedFailed,
)
from backend.entity.mcp.actor import current_actor
from backend.entity.mcp.guidance import TOOL_DESCRIPTIONS
from backend.entity.mcp.server import _entity_item, _err, _require, mcp
from backend.entity.projection import (
    EntityProjection,
    _digest,
    _serving_head_id,
    _sql_backend,
    canonical_text,
    current_projection,
)
from backend.entity.records import BusinessEntityRecord
from backend.entity.store import get_entity_store

_QUERY_TEXT_MAX = 2000
_LIMIT_DEFAULT = 10
_LIMIT_MAX = 50
_PASS_THROUGH = (
    ModelServiceNotInUse,
    ModelServiceClosed,
    ModelServiceEndpointMissing,
    ModelServiceGenerationMismatch,
    ModelServiceControlRevisionMismatch,
)


@dataclass(frozen=True, slots=True)
class _Hit:
    entity: BusinessEntityRecord
    projection: EntityProjection


def _clean_query(raw: str) -> str:
    text_value = raw.strip() if isinstance(raw, str) else ""
    if not text_value:
        raise EntityRequestInvalid("query_text is required")
    if len(text_value) > _QUERY_TEXT_MAX:
        raise EntityRequestInvalid("query_text must be at most 2000 characters")
    return text_value


def _clean_limit(raw: int | None) -> int:
    if raw is None:
        return _LIMIT_DEFAULT
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1 or raw > _LIMIT_MAX:
        raise EntityRequestInvalid("limit must be an integer from 1 through 50")
    return raw


def _projection_current(entity_id: str, projection: EntityProjection, generation: int) -> bool:
    if projection.generation != generation:
        return False
    if projection.processing_contract != CURRENT_PROCESSING_CONTRACT:
        return False
    if projection.head_version_id != _serving_head_id(entity_id):
        return False
    return projection.content_hash == _digest(canonical_text(entity_id))


def _require_open_runtime() -> EmbeddingRuntime:
    """Not configured, then closed, then a missing URL. Both fences use this order."""

    runtime = get_embedding_runtime()
    if runtime is None:
        raise ModelServiceNotInUse()
    if runtime.closed:
        raise ModelServiceClosed()
    if not runtime.url:
        raise ModelServiceEndpointMissing()
    return runtime


def _require_searchable() -> tuple[int, int]:
    """Model configured, controls open, and the Entity index is on that generation."""

    runtime = _require_open_runtime()
    index = get_entity_index_store().get()
    if not index.ready or index.generation != runtime.generation:
        raise EntityIndexNotReady()
    return runtime.generation, runtime.control_revision


def _recheck_fence(generation: int, control_revision: int) -> None:
    runtime = _require_open_runtime()
    if runtime.generation != generation:
        raise ModelServiceGenerationMismatch()
    if runtime.control_revision != control_revision:
        raise ModelServiceControlRevisionMismatch()
    index = get_entity_index_store().get()
    if not index.ready or index.generation != generation:
        raise EntityIndexNotReady()


def _authorized_serving(user: Any) -> list[BusinessEntityRecord]:
    candidates = get_entity_store().list_entity_candidates(
        q=None,
        statuses=frozenset({"serving"}),
        subject_ids=None,
        match_description=True,
    )
    if not candidates:
        return []
    visible = readable_entity_ids(
        [entity.id for entity in candidates], person_of(user)
    )
    return [entity for entity in candidates if entity.id in visible]


def _eligible(entities: list[BusinessEntityRecord], generation: int) -> list[_Hit]:
    hits: list[_Hit] = []
    for entity in entities:
        projection = current_projection(entity.id)
        if projection is None or not _projection_current(entity.id, projection, generation):
            continue
        hits.append(_Hit(entity, projection))
    return hits


def _cosine(left: list[float] | tuple[float, ...], right: list[float] | tuple[float, ...]) -> float | None:
    if not left or not right or len(left) != len(right):
        return None
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for one, other in zip(left, right, strict=True):
        dot += one * other
        left_norm += one * one
        right_norm += other * other
    if left_norm <= 0.0 or right_norm <= 0.0:
        return None
    score = dot / (math.sqrt(left_norm) * math.sqrt(right_norm))
    if not math.isfinite(score):
        return None
    return score


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(repr(float(item)) for item in values) + "]"


def _rank_sql(
    hits: list[_Hit], query: list[float], limit: int
) -> list[tuple[_Hit, float]]:
    by_id = {hit.entity.id: hit for hit in hits}
    stmt = text(
        """
        SELECT e.entity_id,
               (1 - (e.embedding <=> CAST(:q AS vector))) AS score
        FROM entity_embeddings AS e
        JOIN business_entities AS b ON b.id = e.entity_id
        WHERE e.entity_id IN :entity_ids
          AND e.generation = :generation
          AND e.processing_contract = :contract
          AND e.embedding_dim = :dim
        ORDER BY e.embedding <=> CAST(:q AS vector), b.table_name COLLATE "C"
        LIMIT :k
        """
    ).bindparams(bindparam("entity_ids", expanding=True))
    params = {
        "entity_ids": list(by_id),
        "q": _vector_literal(query),
        "generation": hits[0].projection.generation,
        "contract": CURRENT_PROCESSING_CONTRACT,
        "dim": len(query),
        "k": limit,
    }
    with session_scope() as session:
        rows = session.execute(stmt, params).all()
    ordered: list[tuple[_Hit, float]] = []
    for entity_id, score in rows:
        ordered.append((by_id[str(entity_id)], float(score)))
    return ordered


def _rank(hits: list[_Hit], query: list[float], limit: int) -> list[tuple[_Hit, float]]:
    scored: list[tuple[_Hit, float]] = []
    for hit in hits:
        score = _cosine(query, hit.projection.embedding)
        if score is None:
            continue
        scored.append((hit, score))
    if not scored:
        return []
    if _sql_backend():
        return _rank_sql([hit for hit, _score in scored], query, limit)
    scored.sort(key=lambda item: (-item[1], item[0].entity.table_name))
    return scored[:limit]


def _embed_query(text_value: str, generation: int, control_revision: int) -> list[float]:
    try:
        result = embed_texts(
            [text_value],
            expected_generation=generation,
            expected_control_revision=control_revision,
        )
    except _PASS_THROUGH:
        raise
    except Exception:
        raise EntitySearchEmbedFailed() from None
    vectors = result.vectors
    if len(vectors) != 1 or _cosine(vectors[0], vectors[0]) is None:
        raise EntitySearchEmbedFailed()
    return [float(item) for item in vectors[0]]


def _still_current(hit: _Hit, generation: int) -> bool:
    current = current_projection(hit.entity.id)
    if current is None:
        return False
    if (
        current.head_version_id != hit.projection.head_version_id
        or current.content_hash != hit.projection.content_hash
        or current.generation != hit.projection.generation
        or current.processing_contract != hit.projection.processing_contract
    ):
        return False
    return _projection_current(hit.entity.id, current, generation)


def _search(user: Any, query_text: str, limit: int) -> dict[str, Any]:
    generation, control_revision = _require_searchable()
    authorized = _authorized_serving(user)
    hits = _eligible(authorized, generation)
    if not hits:
        return {"items": []}
    query = _embed_query(query_text, generation, control_revision)
    ranked = _rank(hits, query, limit)
    _recheck_fence(generation, control_revision)
    if not ranked:
        return {"items": []}
    visible = readable_entity_ids(
        [hit.entity.id for hit, _score in ranked], person_of(user)
    )
    items: list[dict[str, Any]] = []
    for hit, score in ranked:
        if hit.entity.id not in visible or not _still_current(hit, generation):
            continue
        item = _entity_item(hit.entity)
        item["score"] = score
        items.append(item)
    return {"items": items}


@mcp.tool(
    description=TOOL_DESCRIPTIONS["search_entities"],
    annotations=ToolAnnotations(read_only_hint=True),
)
def search_entities(query_text: str, limit: int | None = None) -> str:
    """Rank serving Entities the caller can read. Scores are cosine similarity."""
    try:
        user, _token_id = current_actor()
        _require(user, "entity:data_read")
        return json.dumps(
            _search(user, _clean_query(query_text), _clean_limit(limit))
        )
    except Exception as exc:  # noqa: BLE001 — tool failures stay in the envelope
        return _err(exc)
