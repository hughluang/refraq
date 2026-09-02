"""Refresh catalog embeddings after structure or semantics writes."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from backend.core.time import utc_now
from backend.metadata.catalog.embedding import (
    CatalogEmbeddingRecord,
    column_embedding_text,
    content_hash,
    current_generation,
    embed_texts,
    embedding_write_enabled,
    object_embedding_text,
)
from backend.metadata.catalog.records import (
    CatalogColumnRecord,
    CatalogObjectRecord,
    new_embedding_id,
)
from backend.metadata.catalog.store import get_catalog_store

logger = logging.getLogger(__name__)

UpsertOutcome = Literal["written", "skipped", "failed"]
_EMBED_BATCH = 32
_LOAD_EVERY = 64
_REASON_MAX = 300
_LENGTH_MISMATCH = "embeddings response length mismatch"


@dataclass(frozen=True)
class EmbeddingRefreshCounts:
    objects_attempted: int = 0
    objects_written: int = 0
    objects_failed: int = 0
    objects_skipped: int = 0
    columns_attempted: int = 0
    columns_written: int = 0
    columns_failed: int = 0
    columns_skipped: int = 0

    def plus(self, other: EmbeddingRefreshCounts) -> EmbeddingRefreshCounts:
        return EmbeddingRefreshCounts(
            objects_attempted=self.objects_attempted + other.objects_attempted,
            objects_written=self.objects_written + other.objects_written,
            objects_failed=self.objects_failed + other.objects_failed,
            objects_skipped=self.objects_skipped + other.objects_skipped,
            columns_attempted=self.columns_attempted + other.columns_attempted,
            columns_written=self.columns_written + other.columns_written,
            columns_failed=self.columns_failed + other.columns_failed,
            columns_skipped=self.columns_skipped + other.columns_skipped,
        )

    @property
    def written(self) -> int:
        return self.objects_written + self.columns_written

    @property
    def attempted(self) -> int:
        return self.objects_attempted + self.columns_attempted


@runtime_checkable
class EmbedRefreshProgress(Protocol):
    """Observer for catalog embedding refresh. Implementations must not live here."""

    def loading(self, *, objects: int, loaded: int) -> None:
        """Catalog detail fetch; ``loaded`` of ``objects`` have been read."""

    def planned(self, *, objects: int, columns: int) -> None:
        """Pending object and column texts are ready to embed."""

    def progressed(
        self,
        counts: EmbeddingRefreshCounts,
        *,
        processed: int,
        total: int,
    ) -> None:
        """Finished one embed batch; ``counts`` are source-local so far."""

    def failed(self, *, reason: str, n: int) -> None:
        """``n`` pending items failed for ``reason`` (batch or whole source)."""


def _reason_text(exc: BaseException) -> str:
    text = str(exc).strip() or type(exc).__name__
    if len(text) > _REASON_MAX:
        return text[:_REASON_MAX] + "…"
    return text


def refresh_object_embedding(obj: CatalogObjectRecord, *, force: bool = False) -> bool:
    if not embedding_write_enabled(incremental=not force):
        return False
    return _upsert("object", obj.id, obj.locator_key, object_embedding_text(obj)) == "written"


def refresh_column_embedding(
    col: CatalogColumnRecord, *, object_name: str | None = None, force: bool = False
) -> bool:
    if not embedding_write_enabled(incremental=not force):
        return False
    return (
        _upsert(
            "column",
            col.id,
            col.locator_key,
            column_embedding_text(col, object_name=object_name),
        )
        == "written"
    )


def refresh_source_embeddings(
    source_id: str,
    *,
    force: bool = False,
    progress: EmbedRefreshProgress | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> EmbeddingRefreshCounts:
    try:
        if not embedding_write_enabled(incremental=not force):
            return EmbeddingRefreshCounts()
        return _refresh_source_embeddings(
            source_id, progress=progress, should_stop=should_stop
        )
    except Exception as exc:
        logger.warning(
            "embedding refresh for source %s failed", source_id, exc_info=True
        )
        counts = _failed_source_counts(source_id)
        if progress is not None:
            progress.planned(
                objects=counts.objects_attempted, columns=counts.columns_attempted
            )
            progress.failed(reason=_reason_text(exc), n=counts.attempted)
            progress.progressed(
                counts, processed=counts.attempted, total=counts.attempted
            )
        return counts


def _refresh_source_embeddings(
    source_id: str,
    *,
    progress: EmbedRefreshProgress | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> EmbeddingRefreshCounts:
    store = get_catalog_store()
    objects, _total = store.list_objects(
        source_id, include_absent=True, limit=None, offset=0
    )
    listed = len(objects)
    if progress is not None:
        progress.loading(objects=listed, loaded=0)
    objects_attempted = 0
    objects_written = 0
    objects_failed = 0
    objects_skipped = 0
    columns_attempted = 0
    columns_written = 0
    columns_failed = 0
    columns_skipped = 0
    pending: list[tuple[str, str, str, str]] = []
    for index, obj in enumerate(objects, start=1):
        detail = store.get_object(obj.id)
        if detail is None:
            if progress is not None and (index % _LOAD_EVERY == 0 or index == listed):
                progress.loading(objects=listed, loaded=index)
            continue
        objects_attempted += 1
        pending.append(
            ("object", detail.id, detail.locator_key, object_embedding_text(detail))
        )
        for col in detail.columns:
            columns_attempted += 1
            pending.append(
                (
                    "column",
                    col.id,
                    col.locator_key,
                    column_embedding_text(col, object_name=detail.name),
                )
            )
        if progress is not None and (index % _LOAD_EVERY == 0 or index == listed):
            progress.loading(objects=listed, loaded=index)
    total = len(pending)
    if progress is not None:
        progress.planned(objects=objects_attempted, columns=columns_attempted)

    def snapshot() -> EmbeddingRefreshCounts:
        return EmbeddingRefreshCounts(
            objects_attempted=objects_attempted,
            objects_written=objects_written,
            objects_failed=objects_failed,
            objects_skipped=objects_skipped,
            columns_attempted=columns_attempted,
            columns_written=columns_written,
            columns_failed=columns_failed,
            columns_skipped=columns_skipped,
        )

    for start in range(0, total, _EMBED_BATCH):
        if should_stop is not None and should_stop():
            break
        chunk = pending[start : start + _EMBED_BATCH]
        outcomes, fail_reason = _upsert_many(chunk)
        for (kind, _target_id, _locator, _text), outcome in zip(
            chunk, outcomes, strict=True
        ):
            if kind == "object":
                if outcome == "written":
                    objects_written += 1
                elif outcome == "failed":
                    objects_failed += 1
                else:
                    objects_skipped += 1
            elif outcome == "written":
                columns_written += 1
            elif outcome == "failed":
                columns_failed += 1
            else:
                columns_skipped += 1
        if fail_reason and progress is not None:
            failed_n = sum(1 for outcome in outcomes if outcome == "failed")
            progress.failed(reason=fail_reason, n=failed_n)
        if progress is not None:
            progress.progressed(
                snapshot(), processed=min(start + len(chunk), total), total=total
            )
    return snapshot()


def _failed_source_counts(source_id: str) -> EmbeddingRefreshCounts:
    try:
        store = get_catalog_store()
        objects, _total = store.list_objects(
            source_id, include_absent=True, limit=None, offset=0
        )
    except Exception:
        return EmbeddingRefreshCounts()
    objects_n = 0
    columns_n = 0
    for obj in objects:
        objects_n += 1
        detail = store.get_object(obj.id)
        if detail is not None:
            columns_n += len(detail.columns)
    return EmbeddingRefreshCounts(
        objects_attempted=objects_n,
        objects_failed=objects_n,
        columns_attempted=columns_n,
        columns_failed=columns_n,
    )


def _upsert_many(
    items: list[tuple[str, str, str, str]],
) -> tuple[list[UpsertOutcome], str | None]:
    store = get_catalog_store()
    generation = current_generation()
    outcomes: list[UpsertOutcome | None] = [None] * len(items)
    to_embed: list[int] = []
    texts: list[str] = []
    existing_rows: list[CatalogEmbeddingRecord | None] = []
    digests: list[str] = []
    fail_reason: str | None = None
    for item in items:
        _kind, target_id, _locator, text = item
        digest = content_hash(text)
        existing = store.get_embedding(kind=_kind, target_id=target_id)
        existing_rows.append(existing)
        digests.append(digest)
        if (
            existing is not None
            and existing.content_hash == digest
            and existing.generation == generation
        ):
            outcomes[len(existing_rows) - 1] = "skipped"
        else:
            to_embed.append(len(existing_rows) - 1)
            texts.append(text)
    if texts:
        try:
            vectors = embed_texts(texts)
        except Exception as exc:
            logger.warning(
                "embedding refresh batch failed n=%s", len(texts), exc_info=True
            )
            fail_reason = _reason_text(exc)
            for idx in to_embed:
                outcomes[idx] = "failed"
            vectors = []
        if vectors and len(vectors) == len(to_embed):
            now = utc_now()
            for idx, vector in zip(to_embed, vectors, strict=True):
                kind, target_id, locator_key, _text = items[idx]
                existing = existing_rows[idx]
                store.upsert_embedding(
                    CatalogEmbeddingRecord(
                        id=existing.id if existing is not None else new_embedding_id(),
                        kind=kind,
                        target_id=target_id,
                        locator_key=locator_key,
                        content_hash=digests[idx],
                        embedding=vector,
                        indexed_at=now,
                        generation=generation,
                    )
                )
                outcomes[idx] = "written"
        elif texts:
            if fail_reason is None:
                fail_reason = _LENGTH_MISMATCH
            for idx in to_embed:
                if outcomes[idx] is None:
                    outcomes[idx] = "failed"
    resolved = ["failed" if item is None else item for item in outcomes]
    return resolved, fail_reason


def _upsert(kind: str, target_id: str, locator_key: str, text: str) -> UpsertOutcome:
    store = get_catalog_store()
    digest = content_hash(text)
    generation = current_generation()
    existing = store.get_embedding(kind=kind, target_id=target_id)
    if (
        existing is not None
        and existing.content_hash == digest
        and existing.generation == generation
    ):
        return "skipped"
    try:
        vectors = embed_texts([text])
    except Exception:
        logger.warning("embedding refresh failed for %s %s", kind, target_id)
        return "failed"
    if not vectors:
        return "failed"
    store.upsert_embedding(
        CatalogEmbeddingRecord(
            id=existing.id if existing is not None else new_embedding_id(),
            kind=kind,
            target_id=target_id,
            locator_key=locator_key,
            content_hash=digest,
            embedding=vectors[0],
            indexed_at=utc_now(),
            generation=generation,
        )
    )
    return "written"
