"""Optional embedding client and Catalog Search vector rank (ADR 0043 / 0039)."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any

from backend.admin.model_services import (
    embed_texts as request_embeddings,
    get_embedding_runtime,
)
from backend.admin.model_services.ports import catalog_embed_jobs

EmbedFn = Callable[[list[str]], list[list[float]]]


@dataclass
class CatalogEmbeddingRecord:
    id: str
    kind: str
    target_id: str
    locator_key: str
    content_hash: str
    embedding: list[float]
    indexed_at: datetime
    generation: int = 0

_override_embed: EmbedFn | None = None


def set_embed_fn_for_tests(fn: EmbedFn | None) -> None:
    global _override_embed
    _override_embed = fn


def current_generation() -> int:
    runtime = get_embedding_runtime()
    return runtime.generation if runtime is not None else 0


def embedding_configured() -> bool:
    """True when Catalog Search complete state (vector) should run."""
    if _override_embed is not None:
        return True
    runtime = get_embedding_runtime()
    return (
        runtime is not None
        and not runtime.closed
        and bool(runtime.url)
        and catalog_embed_jobs().index_view().ready
    )


def embedding_write_enabled() -> bool:
    """True when an embedding runtime with a url is present."""
    if _override_embed is not None:
        return True
    runtime = get_embedding_runtime()
    if runtime is None or not runtime.url:
        return False
    return True


def normalize_embedding_text(*parts: str | None) -> str:
    cleaned: list[str] = []
    for raw in parts:
        text = str(raw or "").strip()
        if text:
            cleaned.append(text)
    return "\n".join(cleaned)


def content_hash(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def object_embedding_text(obj: Any) -> str:
    return normalize_embedding_text(
        obj.locator_key,
        obj.schema_name,
        obj.name,
        obj.comment,
        obj.business_name,
        obj.business_description,
    )


def column_embedding_text(col: Any, *, object_name: str | None = None) -> str:
    return normalize_embedding_text(
        col.locator_key,
        object_name,
        col.name,
        col.comment,
        col.business_name,
        col.business_description,
    )


def embed_texts(
    texts: list[str], *, expected_generation: int | None = None
) -> list[list[float]]:
    if not texts:
        return []
    if _override_embed is not None:
        return _override_embed(texts)
    generation = (
        current_generation() if expected_generation is None else expected_generation
    )
    return request_embeddings(texts, expected_generation=generation).vectors


def cosine_similarity(left: list[float], right: list[float]) -> float | None:
    """Cosine similarity, or None when the pair is not a comparable vector."""
    if not left or not right or len(left) != len(right):
        return None
    dot = 0.0
    ln = 0.0
    rn = 0.0
    for a, b in zip(left, right, strict=True):
        dot += a * b
        ln += a * a
        rn += b * b
    if ln <= 0.0 or rn <= 0.0:
        return None
    return dot / (math.sqrt(ln) * math.sqrt(rn))
