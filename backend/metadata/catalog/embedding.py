"""Optional embedding client and Catalog Search hybrid rank (ADR 0037 / 0039)."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any

from backend.admin.model_services import get_embedding_runtime
from backend.admin.model_services.openai_compat import TIMEOUT_SEC, post_openai_embeddings

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
RRF_K = 60


def set_embed_fn_for_tests(fn: EmbedFn | None) -> None:
    global _override_embed
    _override_embed = fn


def current_generation() -> int:
    runtime = get_embedding_runtime()
    return runtime.generation if runtime is not None else 0


def embedding_configured() -> bool:
    """True when Catalog Search hybrid should run."""
    if _override_embed is not None:
        return True
    runtime = get_embedding_runtime()
    return (
        runtime is not None
        and not runtime.closed
        and runtime.ready
        and bool(runtime.url)
    )


def embedding_write_enabled(*, incremental: bool) -> bool:
    """True when vectors may be written (Job force ignores closed)."""
    if _override_embed is not None:
        return True
    runtime = get_embedding_runtime()
    if runtime is None or not runtime.url:
        return False
    if incremental and runtime.closed:
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


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    if _override_embed is not None:
        return _override_embed(texts)
    runtime = get_embedding_runtime()
    if runtime is None or not runtime.url:
        raise RuntimeError("embedding URL is not configured")
    return post_openai_embeddings(
        url=runtime.url,
        model=runtime.model,
        api_key=runtime.secret,
        texts=texts,
        timeout=TIMEOUT_SEC,
    )


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


def rrf_merge(
    lexical_ids: list[str],
    semantic_ids: list[str],
    *,
    k: int = RRF_K,
) -> list[str]:
    scores: dict[str, float] = {}
    for rank, item_id in enumerate(lexical_ids, start=1):
        scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    for rank, item_id in enumerate(semantic_ids, start=1):
        scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda item_id: (-scores[item_id], item_id))
