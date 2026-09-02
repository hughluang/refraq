"""Catalog Search: lexical plus optional embedding RRF."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

from backend.metadata.catalog.embedding import (
    cosine_similarity,
    current_generation,
    embed_texts,
    rrf_merge,
)
from backend.metadata.catalog.store import get_catalog_store

T = TypeVar("T")

logger = logging.getLogger(__name__)

_SEMANTIC_CANDIDATE_LIMIT = 50
LEXICAL_POOL = 500


def hybrid_page(
    *,
    query: str,
    lexical_items: list[T],
    kind: str,
    id_of: Callable[[T], str],
    limit: int,
    offset: int,
) -> tuple[list[T], int] | None:
    """Merge lexical-ranked items with embedding neighbors.

    Returns None when the query vector cannot be produced so the caller
    pages the lexical store the same way as when embeddings are unset.
    """
    semantic_ids = _nearest_ids(kind, query)
    if semantic_ids is None:
        return None

    lexical_ids = [id_of(item) for item in lexical_items]
    by_id: dict[str, T] = {id_of(item): item for item in lexical_items}
    store = get_catalog_store()
    for target_id in semantic_ids:
        if target_id in by_id:
            continue
        extra = (
            store.get_object(target_id)
            if kind == "object"
            else store.get_column(target_id)
        )
        if extra is None:
            continue
        by_id[target_id] = extra  # type: ignore[assignment]
    merged_ids = rrf_merge(lexical_ids, semantic_ids)
    merged = [by_id[item_id] for item_id in merged_ids if item_id in by_id]
    return merged[offset : offset + limit], len(merged)


def _nearest_ids(kind: str, query: str) -> list[str] | None:
    try:
        vectors = embed_texts([query])
    except Exception:
        logger.warning("catalog search query embed failed for kind %s", kind)
        return None
    if not vectors:
        logger.warning("catalog search query embed returned no vectors for kind %s", kind)
        return None
    query_vec = vectors[0]
    scored: list[tuple[float, str]] = []
    skipped = 0
    generation = current_generation()
    for rec in get_catalog_store().list_embeddings(kind=kind):
        if rec.generation != generation:
            continue
        score = cosine_similarity(query_vec, rec.embedding)
        if score is None:
            skipped += 1
            continue
        scored.append((score, rec.target_id))
    if skipped:
        logger.warning(
            "skipped %s %s embeddings with incompatible vectors",
            skipped,
            kind,
        )
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [
        target_id
        for score, target_id in scored[:_SEMANTIC_CANDIDATE_LIMIT]
        if score > 0
    ]
