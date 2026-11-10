"""Published embedding call for in-use Model Service consumers."""

from __future__ import annotations

import math
from dataclasses import dataclass

from backend.admin.model_services.errors import (
    ModelServiceClosed,
    ModelServiceEndpointMissing,
    ModelServiceGenerationMismatch,
    ModelServiceNotInUse,
    ModelServiceTestFailed,
)
from backend.admin.model_services.openai_compat import (
    EMBEDDING_OUTPUT_DIM,
    post_openai_embeddings,
)
from backend.admin.model_services.service import get_embedding_runtime

PROCESSING_CONTRACT_VERSION = "prefix-1024-l2-v1"
_BATCH_LIMIT = 32


@dataclass(frozen=True)
class EmbeddingSpace:
    service_id: str
    generation: int
    processing_contract: str


@dataclass(frozen=True)
class EmbeddingVectors:
    vectors: list[list[float]]
    space: EmbeddingSpace


def project_embedding(
    vec: list[float], *, dim: int = EMBEDDING_OUTPUT_DIM
) -> list[float]:
    """Truncate a longer vector to `dim` and L2-normalize. Shorter vectors pass through."""
    if len(vec) <= dim:
        return vec
    truncated = vec[:dim]
    norm = math.sqrt(sum(n * n for n in truncated))
    if norm <= 0.0:
        return truncated
    return [n / norm for n in truncated]


def embed_texts(
    texts: list[str],
    *,
    expected_generation: int,
) -> EmbeddingVectors:
    """Embed texts for the live generation. Does not return credentials."""
    if not texts:
        runtime = get_embedding_runtime()
        service_id = runtime.service_id if runtime is not None else ""
        return EmbeddingVectors(
            vectors=[],
            space=EmbeddingSpace(
                service_id=service_id,
                generation=expected_generation,
                processing_contract=PROCESSING_CONTRACT_VERSION,
            ),
        )
    runtime = get_embedding_runtime()
    if runtime is None:
        raise ModelServiceNotInUse()
    if runtime.closed:
        raise ModelServiceClosed()
    if not runtime.url:
        raise ModelServiceEndpointMissing()
    if runtime.generation != expected_generation:
        raise ModelServiceGenerationMismatch()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), _BATCH_LIMIT):
        chunk = texts[start : start + _BATCH_LIMIT]
        vectors.extend(
            post_openai_embeddings(
                url=runtime.url,
                model=runtime.model,
                api_key=runtime.secret,
                texts=chunk,
                timeout=runtime.timeout_sec,
            )
        )
        live = get_embedding_runtime()
        if live is None or live.generation != expected_generation:
            raise ModelServiceGenerationMismatch()
    projected = [project_embedding(vector) for vector in vectors]
    if any(len(vector) != len(projected[0]) for vector in projected):
        raise ModelServiceTestFailed(
            f"Unusable embeddings response from {runtime.url}"
        )
    return EmbeddingVectors(
        vectors=projected,
        space=EmbeddingSpace(
            service_id=runtime.service_id,
            generation=expected_generation,
            processing_contract=PROCESSING_CONTRACT_VERSION,
        ),
    )
