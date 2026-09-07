"""Catalog Search: vector nearest-neighbor, or raise on embed/neighbor failure."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

from backend.admin.model_services.errors import ModelServiceError
from backend.core.errors import AppError
from backend.core.metrics import (
    observe_catalog_neighbor,
    record_catalog_hybrid,
    record_catalog_search_vector_error,
)
from backend.metadata.catalog.embedding import current_generation, embed_texts
from backend.metadata.catalog.store import get_catalog_store
from backend.metadata.errors import CatalogSearchEmbedFailed, CatalogSearchNeighborFailed

T = TypeVar("T")

logger = logging.getLogger(__name__)

_SEMANTIC_CANDIDATE_LIMIT = 50


def vector_page(
    *,
    query: str,
    kind: str,
    id_of: Callable[[T], str],
    limit: int,
    offset: int,
    source_id: str | None = None,
    object_type: str | None = None,
    object_ids: list[str] | None = None,
) -> tuple[list[T], bool]:
    """Return nearest neighbors sliced to `limit`/`offset`, plus truncated.

    Raises when the query vector cannot be produced or neighbor scoring
    fails (other than AppError). An empty neighbor list is a successful
    empty page, not a lexical fallback.
    """
    semantic_ids = _nearest_ids(
        kind,
        query,
        source_id=source_id,
        object_type=object_type,
        object_ids=object_ids,
    )
    record_catalog_hybrid("vector")
    if not semantic_ids:
        return [], False

    store = get_catalog_store()
    extras: list[T]
    if kind == "object":
        extras = store.get_objects_by_ids(semantic_ids)  # type: ignore[assignment]
    else:
        extras = store.get_columns_by_ids(semantic_ids)  # type: ignore[assignment]
    by_id: dict[str, T] = {id_of(item): item for item in extras}
    ordered = [by_id[item_id] for item_id in semantic_ids if item_id in by_id]
    sliced = ordered[offset : offset + limit]
    truncated = offset + limit < len(ordered)
    return sliced, truncated


def _nearest_ids(
    kind: str,
    query: str,
    *,
    source_id: str | None = None,
    object_type: str | None = None,
    object_ids: list[str] | None = None,
) -> list[str]:
    started = time.perf_counter()
    try:
        vectors = embed_texts([query])
    except ModelServiceError:
        observe_catalog_neighbor(kind, "embed", time.perf_counter() - started)
        logger.warning("catalog search query embed failed for kind %s", kind)
        record_catalog_search_vector_error("embed_failed")
        raise CatalogSearchEmbedFailed() from None
    except AppError:
        observe_catalog_neighbor(kind, "embed", time.perf_counter() - started)
        raise
    except Exception:
        observe_catalog_neighbor(kind, "embed", time.perf_counter() - started)
        logger.warning("catalog search query embed failed for kind %s", kind)
        record_catalog_search_vector_error("embed_failed")
        raise CatalogSearchEmbedFailed() from None
    observe_catalog_neighbor(kind, "embed", time.perf_counter() - started)
    if not vectors:
        logger.warning("catalog search query embed returned no vectors for kind %s", kind)
        record_catalog_search_vector_error("no_vectors")
        raise CatalogSearchEmbedFailed()
    started_score = time.perf_counter()
    try:
        return get_catalog_store().nearest_embeddings(
            kind=kind,
            query=vectors[0],
            limit=_SEMANTIC_CANDIDATE_LIMIT,
            generation=current_generation(),
            source_id=source_id,
            object_type=object_type,
            object_ids=object_ids,
        )
    except AppError:
        raise
    except Exception:
        logger.warning("catalog search neighbor failed for kind %s", kind)
        record_catalog_search_vector_error("neighbor_failed")
        raise CatalogSearchNeighborFailed() from None
    finally:
        observe_catalog_neighbor(kind, "score", time.perf_counter() - started_score)
