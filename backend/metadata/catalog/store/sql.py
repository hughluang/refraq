"""SQL CatalogStore persistence adapter."""

from __future__ import annotations

from backend.core.time import utc_now
import json
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, defer, noload, selectinload

from backend.core.db import get_session_factory, session_scope
from backend.core.pagination import apply_offset_page, apply_sql_page
from backend.metadata.catalog.identity import (
    _recompute_column_locator,
    _recompute_object_locator,
)
from backend.metadata.catalog.records import (
    CatalogColumnRecord,
    CatalogForeignKeyRecord,
    CatalogIndexRecord,
    CatalogJoinRecord,
    CatalogObjectRecord,
    UNSET,
)
from backend.metadata.catalog.list_query import list_object_sql_filters
from backend.metadata.catalog.search_rank import _search_rank, rank_and_page
from backend.metadata.catalog.structure_merge import StructureRefreshPlan
from backend.metadata.catalog.join_pair import Inserted, Occupied, apply_insert_join
from backend.metadata.catalog.structure_persist import (
    apply_join_detection_plan,
    apply_structure_plan,
)
from backend.metadata.catalog.join_changes import (
    CatalogJoinChangeRecord,
    join_change_for_amend,
    join_change_for_rejection_toggle,
)
from backend.metadata.join_detection_jobs.reconcile import JoinDetectionPlan
from backend.metadata.catalog.embedding import CatalogEmbeddingRecord
from backend.metadata.catalog.records import new_embedding_id
from backend.metadata.catalog.semantics_changes import CatalogSemanticsChangeRecord
from backend.metadata.models import (
    CatalogColumnRow,
    CatalogEmbeddingRow,
    CatalogForeignKeyRow,
    CatalogIndexRow,
    CatalogJoinChangeRow,
    CatalogJoinRow,
    CatalogObjectRow,
    CatalogSemanticsChangeRow,
)


def _dumps_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value)


def _loads_json(raw: str | None) -> Any:
    if raw is None:
        return None
    return json.loads(raw)


def _select_joins_for_source(source_id: str):
    """Joins whose endpoints sit on this Source. Subquery — never bind every column id.

    An expanded ``IN (:id1, :id2, …)`` hits PostgreSQL's 65535 bind-parameter cap
    on large catalogs (one Source can have hundreds of thousands of columns).
    """

    source_col_ids = (
        select(CatalogColumnRow.id)
        .join(CatalogObjectRow, CatalogColumnRow.object_id == CatalogObjectRow.id)
        .where(CatalogObjectRow.source_id == source_id)
    )
    return select(CatalogJoinRow).where(
        or_(
            CatalogJoinRow.from_column_id.in_(source_col_ids),
            CatalogJoinRow.to_column_id.in_(source_col_ids),
        )
    )


class _SqlStructureWrite:
    def __init__(self, session: Session, source_id: str) -> None:
        self._session = session
        self._source_id = source_id

    @property
    def session(self) -> Session:
        return self._session

    def load_baseline(
        self,
    ) -> tuple[list[CatalogObjectRecord], list[CatalogJoinRecord]]:
        rows = list(
            self._session.scalars(
                select(CatalogObjectRow)
                .where(CatalogObjectRow.source_id == self._source_id)
                .options(
                    selectinload(CatalogObjectRow.columns),
                    selectinload(CatalogObjectRow.foreign_keys),
                    selectinload(CatalogObjectRow.indexes),
                )
            ).all()
        )
        existing_objects = [_row_to_object(r) for r in rows]
        join_rows = list(
            self._session.scalars(_select_joins_for_source(self._source_id)).all()
        )
        existing_joins = [_row_to_join(j) for j in join_rows]
        self._session.commit()
        return existing_objects, existing_joins

    def persist_plan(self, plan: StructureRefreshPlan) -> None:
        now = utc_now()
        apply_structure_plan(_SqlPersistPort(self._session, now=now), plan, now=now)
        self._session.flush()

    def persist_join_detection_plan(self, plan: JoinDetectionPlan) -> int:
        now = utc_now()
        inserted = apply_join_detection_plan(
            _SqlPersistPort(self._session, now=now), plan, now=now
        )
        self._session.flush()
        return inserted


class SqlCatalogStore:
    def list_objects(
        self,
        source_id: str,
        *,
        name_search: str | None = None,
        include_absent: bool = True,
        object_type: str | None = None,
        business_semantics_ready: bool | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[CatalogObjectRecord], int]:

        filters = list_object_sql_filters(
            CatalogObjectRow,
            source_id=source_id,
            name_search=name_search,
            include_absent=include_absent,
            object_type=object_type,
            business_semantics_ready=business_semantics_ready,
        )
        with session_scope() as session:
            count_stmt = (
                select(func.count()).select_from(CatalogObjectRow).where(*filters)
            )
            total = int(session.execute(count_stmt).scalar_one())
            stmt = (
                select(CatalogObjectRow)
                .where(*filters)
                .options(
                    noload(CatalogObjectRow.columns),
                    noload(CatalogObjectRow.foreign_keys),
                    noload(CatalogObjectRow.indexes),
                    defer(CatalogObjectRow.ddl),
                )
                .order_by(
                    CatalogObjectRow.schema_name,
                    CatalogObjectRow.name,
                    CatalogObjectRow.object_type,
                )
                .offset(offset)
            )
            if limit is not None:
                stmt = stmt.limit(limit)
            rows = session.scalars(stmt).all()
            return (
                [_row_to_object(r, include_structure=False) for r in rows],
                total,
            )

    def search_objects(
        self,
        query: str,
        *,
        source_id: str | None = None,
        object_type: str | None = None,
        include_absent: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[CatalogObjectRecord], int]:

        with session_scope() as session:
            stmt = select(CatalogObjectRow).options(
                selectinload(CatalogObjectRow.columns)
            )
            if source_id is not None:
                stmt = stmt.where(CatalogObjectRow.source_id == source_id)
            if object_type is not None:
                stmt = stmt.where(CatalogObjectRow.object_type == object_type)
            if not include_absent:
                stmt = stmt.where(CatalogObjectRow.is_present.is_(True))
            rows = session.scalars(stmt).all()
            return rank_and_page(
                (_row_to_object(row) for row in rows),
                rank_of=lambda o: _search_rank(
                    query,
                    locator_key=o.locator_key,
                    name=o.name,
                    schema_name=o.schema_name,
                    business_name=o.business_name,
                    business_description=o.business_description,
                ),
                tiebreak=lambda o: (o.schema_name, o.name, o.id),
                limit=limit,
                offset=offset,
            )

    def search_columns(
        self,
        query: str,
        *,
        source_id: str | None = None,
        object_type: str | None = None,
        include_absent: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[CatalogColumnRecord], int]:

        with session_scope() as session:
            stmt = select(CatalogObjectRow).options(
                selectinload(CatalogObjectRow.columns)
            )
            if source_id is not None:
                stmt = stmt.where(CatalogObjectRow.source_id == source_id)
            if object_type is not None:
                stmt = stmt.where(CatalogObjectRow.object_type == object_type)
            rows = session.scalars(stmt).all()
            candidates: list[CatalogColumnRecord] = []
            for row in rows:
                obj = _row_to_object(row)
                for col in obj.columns:
                    if include_absent or col.is_present:
                        candidates.append(col)
            return rank_and_page(
                candidates,
                rank_of=lambda c: _search_rank(
                    query,
                    locator_key=c.locator_key,
                    name=c.name,
                    business_name=c.business_name,
                    business_description=c.business_description,
                ),
                tiebreak=lambda c: (c.name, c.id),
                limit=limit,
                offset=offset,
            )

    def get_object(self, object_id: str) -> CatalogObjectRecord | None:
        with session_scope() as session:
            row = session.get(
                CatalogObjectRow,
                object_id,
                options=(selectinload(CatalogObjectRow.columns),),
            )
            return _row_to_object(row) if row else None

    def get_object_by_locator(self, locator_key: str) -> CatalogObjectRecord | None:
        with session_scope() as session:
            row = session.scalars(
                select(CatalogObjectRow)
                .where(CatalogObjectRow.locator_key == locator_key)
                .options(selectinload(CatalogObjectRow.columns))
            ).first()
            return _row_to_object(row) if row else None

    def get_column(self, column_id: str) -> CatalogColumnRecord | None:
        with session_scope() as session:
            row = session.get(CatalogColumnRow, column_id)
            return _row_to_column(row) if row else None

    def get_column_by_locator(self, locator_key: str) -> CatalogColumnRecord | None:
        with session_scope() as session:
            row = session.scalars(
                select(CatalogColumnRow).where(
                    CatalogColumnRow.locator_key == locator_key
                )
            ).first()
            return _row_to_column(row) if row else None

    def list_present_for_source(self, source_id: str) -> list[CatalogObjectRecord]:
        with session_scope() as session:
            rows = list(
                session.scalars(
                    select(CatalogObjectRow)
                    .where(
                        CatalogObjectRow.source_id == source_id,
                        CatalogObjectRow.is_present.is_(True),
                    )
                    .options(
                        selectinload(CatalogObjectRow.columns),
                        selectinload(CatalogObjectRow.foreign_keys),
                        selectinload(CatalogObjectRow.indexes),
                    )
                    .order_by(
                        CatalogObjectRow.schema_name,
                        CatalogObjectRow.name,
                        CatalogObjectRow.object_type,
                    )
                ).all()
            )
            return [_row_to_object(r) for r in rows]

    def count_objects_for_domain(self, domain_id: str) -> int:
        with session_scope() as session:
            return int(
                session.execute(
                    select(func.count())
                    .select_from(CatalogObjectRow)
                    .where(CatalogObjectRow.business_domain_id == domain_id)
                ).scalar_one()
            )

    @contextmanager
    def catalog_write(self, source_id: str) -> Iterator[_SqlStructureWrite]:
        """Catalog write unit: load baseline, persist plan (no merge).

        Same-kind runner serialization is the **Kind execution lock** (ADR 0032),
        not this write unit. Automatic join inserts use ON CONFLICT DO NOTHING.
        Successful exit commits once (catalog plan + Diff rows on the same session).
        """
        session = get_session_factory()()
        write = _SqlStructureWrite(session, source_id)
        try:
            yield write
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def recompute_locators_for_source(
        self,
        source_id: str,
        *,
        engine: str | None,
        kind: str,
        source_key: str,
    ) -> int:

        changed = 0
        with session_scope() as session:
            rows = list(
                session.scalars(
                    select(CatalogObjectRow)
                    .where(CatalogObjectRow.source_id == source_id)
                    .options(selectinload(CatalogObjectRow.columns))
                ).all()
            )
            for row in rows:
                obj_locator = _recompute_object_locator(
                    engine=engine,
                    kind=kind,
                    source_key=source_key,
                    schema_name=row.schema_name,
                    object_type=row.object_type,
                    name=row.name,
                )
                if row.locator_key != obj_locator:
                    row.locator_key = obj_locator
                    changed += 1
                for col in row.columns:
                    col_locator = _recompute_column_locator(
                        engine=engine,
                        kind=kind,
                        source_key=source_key,
                        schema_name=row.schema_name,
                        object_type=row.object_type,
                        name=row.name,
                        column_name=col.name,
                        field_kind=col.field_kind or "column",
                    )
                    if col.locator_key != col_locator:
                        col.locator_key = col_locator
                        changed += 1
            session.flush()
        return changed

    def delete_objects_for_source(self, source_id: str) -> None:
        with session_scope() as session:
            rows = list(
                session.scalars(
                    select(CatalogObjectRow)
                    .where(CatalogObjectRow.source_id == source_id)
                    .options(selectinload(CatalogObjectRow.columns))
                ).all()
            )
            for row in rows:
                session.delete(row)
            session.flush()

    def patch_object_semantics(
        self,
        object_id: str,
        *,
        business_name: Any = UNSET,
        business_description: Any = UNSET,
        object_category: Any = UNSET,
        grain_description: Any = UNSET,
        business_primary_key: Any = UNSET,
        business_domain_id: Any = UNSET,
        evidence_summary: Any = UNSET,
        open_questions: Any = UNSET,
        semantic_source: Any = UNSET,
        business_semantics_ready: Any = UNSET,
    ) -> CatalogObjectRecord | None:

        with session_scope() as session:
            row = session.get(
                CatalogObjectRow,
                object_id,
                options=(selectinload(CatalogObjectRow.columns),),
            )
            if row is None:
                return None
            now = utc_now()
            changed = False
            if business_name is not UNSET:
                row.business_name = business_name
                changed = True
            if business_description is not UNSET:
                row.business_description = business_description
                changed = True
            if object_category is not UNSET:
                row.object_category = object_category
                changed = True
            if grain_description is not UNSET:
                row.grain_description = grain_description
                changed = True
            if business_primary_key is not UNSET:
                row.business_primary_key_json = _dumps_json(business_primary_key)
                changed = True
            if business_domain_id is not UNSET:
                row.business_domain_id = business_domain_id
                changed = True
            if evidence_summary is not UNSET:
                row.evidence_summary_json = _dumps_json(evidence_summary)
                changed = True
            if open_questions is not UNSET:
                row.open_questions_json = _dumps_json(open_questions)
                changed = True
            if semantic_source is not UNSET:
                row.semantic_source = semantic_source
                changed = True
            if business_semantics_ready is not UNSET:
                row.business_semantics_ready = business_semantics_ready
                changed = True
            row.updated_at = now
            if changed:
                row.semantics_updated_at = now
            session.flush()
            return _row_to_object(row)

    def patch_column_semantics(
        self,
        column_id: str,
        *,
        business_name: Any = UNSET,
        business_description: Any = UNSET,
        column_semantics: Any = UNSET,
        enum_catalog: Any = UNSET,
        semantic_source: Any = UNSET,
        field_kind: Any = UNSET,
    ) -> CatalogColumnRecord | None:

        with session_scope() as session:
            row = session.get(CatalogColumnRow, column_id)
            if row is None:
                return None
            if business_name is not UNSET:
                row.business_name = business_name
            if business_description is not UNSET:
                row.business_description = business_description
            if column_semantics is not UNSET:
                row.column_semantics_json = _dumps_json(column_semantics)
            if enum_catalog is not UNSET:
                row.enum_catalog_json = _dumps_json(enum_catalog)
            if semantic_source is not UNSET:
                row.semantic_source = semantic_source
            if field_kind is not UNSET:
                row.field_kind = field_kind
            row.updated_at = utc_now()
            session.flush()
            return _row_to_column(row)

    def get_join(self, join_id: str) -> CatalogJoinRecord | None:
        with session_scope() as session:
            row = session.get(CatalogJoinRow, join_id)
            return _row_to_join(row) if row else None

    def get_join_by_pair(
        self,
        from_column_id: str,
        to_column_id: str,
    ) -> CatalogJoinRecord | None:

        with session_scope() as session:
            row = session.scalars(
                select(CatalogJoinRow).where(
                    CatalogJoinRow.from_column_id == from_column_id,
                    CatalogJoinRow.to_column_id == to_column_id,
                )
            ).first()
            return _row_to_join(row) if row else None

    def list_joins_for_object(
        self, object_id: str, *, limit: int | None = None, offset: int = 0
    ) -> tuple[list[CatalogJoinRecord], int]:
        with session_scope() as session:
            col_ids = list(
                session.scalars(
                    select(CatalogColumnRow.id).where(
                        CatalogColumnRow.object_id == object_id
                    )
                ).all()
            )
            if not col_ids:
                return [], 0
            pred = or_(
                CatalogJoinRow.from_column_id.in_(col_ids),
                CatalogJoinRow.to_column_id.in_(col_ids),
            )
            total = int(
                session.scalar(
                    select(func.count()).select_from(CatalogJoinRow).where(pred)
                )
                or 0
            )
            stmt = apply_sql_page(
                select(CatalogJoinRow)
                .where(pred)
                .order_by(CatalogJoinRow.created_at, CatalogJoinRow.id),
                limit=limit,
                offset=offset,
            )
            return [_row_to_join(r) for r in session.scalars(stmt).all()], total

    def list_all_joins_for_source(self, source_id: str) -> list[CatalogJoinRecord]:
        with session_scope() as session:
            rows = list(
                session.scalars(
                    _select_joins_for_source(source_id).order_by(
                        CatalogJoinRow.created_at
                    )
                ).all()
            )
            return [_row_to_join(r) for r in rows]

    def write_insert_join(
        self,
        *,
        from_column_id: str,
        to_column_id: str,
        evidence: str,
        created_by_user_id: str | None,
        join_kind: str = "INNER",
        join_expression: str | None = None,
        attester: str,
    ) -> Inserted | Occupied:
        now = utc_now()
        with session_scope() as session:
            return apply_insert_join(
                _SqlPersistPort(session, now=now),
                from_column_id=from_column_id,
                to_column_id=to_column_id,
                evidence=evidence,
                created_by_user_id=created_by_user_id,
                join_kind=join_kind,
                join_expression=join_expression,
                attester=attester,
                now=now,
            )

    def update_join(
        self,
        join_id: str,
        *,
        evidence: str,
        join_kind: str,
        join_expression: str | None,
        actor_user_id: str | None,
    ) -> CatalogJoinRecord | None:
        now = utc_now()
        with session_scope() as session:
            row = session.get(CatalogJoinRow, join_id)
            if row is None:
                return None
            row.evidence = evidence
            row.join_kind = join_kind
            row.join_expression = join_expression
            _sql_append_join_change(
                session,
                join_change_for_amend(
                    from_column_id=row.from_column_id,
                    to_column_id=row.to_column_id,
                    created_at=now,
                    actor_user_id=actor_user_id,
                ),
            )
            session.flush()
            return _row_to_join(row)

    def set_join_rejection(
        self,
        join_id: str,
        *,
        rejected_at: datetime | None,
        rejected_by_user_id: str | None,
        actor_user_id: str | None = None,
    ) -> CatalogJoinRecord | None:
        now = utc_now()
        with session_scope() as session:
            row = session.get(CatalogJoinRow, join_id)
            if row is None:
                return None
            row.rejected_at = rejected_at
            row.rejected_by_user_id = rejected_by_user_id
            _sql_append_join_change(
                session,
                join_change_for_rejection_toggle(
                    from_column_id=row.from_column_id,
                    to_column_id=row.to_column_id,
                    created_at=now,
                    rejected_at=rejected_at,
                    actor_user_id=actor_user_id,
                    rejected_by_user_id=rejected_by_user_id,
                ),
            )
            session.flush()
            return _row_to_join(row)

    def list_join_changes(
        self,
        *,
        from_column_id: str,
        to_column_id: str,
    ) -> list[CatalogJoinChangeRecord]:
        with session_scope() as session:
            rows = list(
                session.scalars(
                    select(CatalogJoinChangeRow)
                    .where(
                        CatalogJoinChangeRow.from_column_id == from_column_id,
                        CatalogJoinChangeRow.to_column_id == to_column_id,
                    )
                    .order_by(CatalogJoinChangeRow.created_at, CatalogJoinChangeRow.id)
                ).all()
            )
            return [_row_to_join_change(r) for r in rows]

    def append_semantics_change(self, change: CatalogSemanticsChangeRecord) -> None:
        with session_scope() as session:
            session.add(
                CatalogSemanticsChangeRow(
                    id=change.id,
                    object_id=change.object_id,
                    column_id=change.column_id,
                    field_name=change.field_name,
                    old_value=change.old_value,
                    new_value=change.new_value,
                    semantic_source=change.semantic_source,
                    actor_user_id=change.actor_user_id,
                    created_at=change.created_at,
                )
            )
            session.flush()

    def list_semantics_changes(
        self,
        object_id: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[CatalogSemanticsChangeRecord], int]:
        with session_scope() as session:
            rows = list(
                session.scalars(
                    select(CatalogSemanticsChangeRow)
                    .where(CatalogSemanticsChangeRow.object_id == object_id)
                    .order_by(
                        CatalogSemanticsChangeRow.created_at.desc(),
                        CatalogSemanticsChangeRow.id.desc(),
                    )
                ).all()
            )
            items = [_row_to_semantics_change(r) for r in rows]
            return apply_offset_page(items, limit=limit, offset=offset)

    def upsert_embedding(self, record: CatalogEmbeddingRecord) -> None:
        with session_scope() as session:
            row = session.scalar(
                select(CatalogEmbeddingRow).where(
                    CatalogEmbeddingRow.kind == record.kind,
                    CatalogEmbeddingRow.target_id == record.target_id,
                )
            )
            if row is None:
                session.add(
                    CatalogEmbeddingRow(
                        id=record.id or new_embedding_id(),
                        kind=record.kind,
                        target_id=record.target_id,
                        locator_key=record.locator_key,
                        content_hash=record.content_hash,
                        embedding=record.embedding,
                        indexed_at=record.indexed_at,
                        generation=record.generation,
                    )
                )
            else:
                row.locator_key = record.locator_key
                row.content_hash = record.content_hash
                row.embedding = record.embedding
                row.indexed_at = record.indexed_at
                row.generation = record.generation
            session.flush()

    def get_embedding(
        self, *, kind: str, target_id: str
    ) -> CatalogEmbeddingRecord | None:
        with session_scope() as session:
            row = session.scalar(
                select(CatalogEmbeddingRow).where(
                    CatalogEmbeddingRow.kind == kind,
                    CatalogEmbeddingRow.target_id == target_id,
                )
            )
            return _row_to_embedding(row) if row is not None else None

    def list_embeddings(self, *, kind: str) -> list[CatalogEmbeddingRecord]:
        with session_scope() as session:
            rows = list(
                session.scalars(
                    select(CatalogEmbeddingRow).where(CatalogEmbeddingRow.kind == kind)
                ).all()
            )
            return [_row_to_embedding(r) for r in rows]

    def delete_embeddings(self) -> None:
        with session_scope() as session:
            session.execute(delete(CatalogEmbeddingRow))
            session.flush()

    def delete_join(self, join_id: str) -> bool:
        with session_scope() as session:
            row = session.get(CatalogJoinRow, join_id)
            if row is None:
                return False
            session.delete(row)
            session.flush()
            return True


_STAMP_CHUNK = 1000


class _SqlPersistPort:
    def __init__(self, session: Session, *, now: datetime) -> None:
        self._session = session
        self._now = now

    def get_join_by_pair(
        self, from_column_id: str, to_column_id: str
    ) -> CatalogJoinRecord | None:
        row = self._session.scalars(
            select(CatalogJoinRow).where(
                CatalogJoinRow.from_column_id == from_column_id,
                CatalogJoinRow.to_column_id == to_column_id,
            )
        ).first()
        return _row_to_join(row) if row is not None else None

    def insert_join(self, record: CatalogJoinRecord) -> CatalogJoinRecord | None:
        stmt = (
            pg_insert(CatalogJoinRow)
            .values(
                id=record.id,
                from_column_id=record.from_column_id,
                to_column_id=record.to_column_id,
                evidence=record.evidence,
                join_kind=record.join_kind,
                join_expression=record.join_expression,
                created_by_user_id=record.created_by_user_id,
                created_at=record.created_at,
            )
            .on_conflict_do_nothing(constraint="uq_catalog_joins_from_to")
            .returning(CatalogJoinRow.id)
        )
        got = self._session.execute(stmt).first()
        if got is None:
            return None
        return record

    def append_join_change(self, change: CatalogJoinChangeRecord) -> None:
        _sql_append_join_change(self._session, change)

    def put_object(self, obj: CatalogObjectRecord) -> None:
        _sql_persist_object(self._session, obj, now=self._now)

    def stamp_objects(self, plan: StructureRefreshPlan) -> None:
        self._session.flush()
        _sql_stamp_objects(self._session, plan)
        self._session.flush()


def _sql_append_join_change(session: Any, change: CatalogJoinChangeRecord) -> None:
    session.add(
        CatalogJoinChangeRow(
            id=change.id,
            from_column_id=change.from_column_id,
            to_column_id=change.to_column_id,
            kind=change.kind,
            attester=change.attester,
            actor_user_id=change.actor_user_id,
            created_at=change.created_at,
        )
        )


def _sql_stamp_objects(session: Any, plan: StructureRefreshPlan) -> None:
    ids = list(plan.stamp_object_ids)
    for offset in range(0, len(ids), _STAMP_CHUNK):
        chunk = ids[offset : offset + _STAMP_CHUNK]
        session.execute(
            update(CatalogObjectRow)
            .where(CatalogObjectRow.id.in_(chunk))
            .values(
                collected_at=plan.collected_at,
                last_structure_job_id=plan.last_structure_job_id,
            )
        )


def _sql_persist_object(
    session: Any, obj: CatalogObjectRecord, *, now: datetime
) -> None:
    """Write a fully-merged CatalogObjectRecord (no merge rules)."""

    row = session.get(
        CatalogObjectRow,
        obj.id,
        options=(
            selectinload(CatalogObjectRow.columns),
            selectinload(CatalogObjectRow.foreign_keys),
            selectinload(CatalogObjectRow.indexes),
        ),
    )
    if row is None:
        row = CatalogObjectRow(
            id=obj.id,
            source_id=obj.source_id,
            locator_key=obj.locator_key,
            object_type=obj.object_type,
            schema_name=obj.schema_name,
            name=obj.name,
            ddl=obj.ddl,
            comment=obj.comment,
            primary_key_json=_dumps_json(obj.primary_key),
            is_present=obj.is_present,
            business_name=obj.business_name,
            business_description=obj.business_description,
            object_category=obj.object_category,
            grain_description=obj.grain_description,
            business_primary_key_json=_dumps_json(obj.business_primary_key),
            business_domain_id=obj.business_domain_id,
            evidence_summary_json=_dumps_json(obj.evidence_summary),
            open_questions_json=_dumps_json(obj.open_questions),
            semantic_source=obj.semantic_source,
            business_semantics_ready=obj.business_semantics_ready,
            semantics_updated_at=obj.semantics_updated_at,
            last_structure_job_id=obj.last_structure_job_id,
            collected_at=obj.collected_at,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )
        session.add(row)
    else:
        row.locator_key = obj.locator_key
        row.object_type = obj.object_type
        row.schema_name = obj.schema_name
        row.name = obj.name
        row.ddl = obj.ddl
        row.comment = obj.comment
        row.primary_key_json = _dumps_json(obj.primary_key)
        row.is_present = obj.is_present
        row.last_structure_job_id = obj.last_structure_job_id
        row.collected_at = obj.collected_at
        row.updated_at = obj.updated_at

    col_by_id = {c.id: c for c in list(row.columns)}
    seen_col_ids: set[str] = set()
    for col in obj.columns:
        seen_col_ids.add(col.id)
        prev = col_by_id.get(col.id)
        if prev is None:
            session.add(
                CatalogColumnRow(
                    id=col.id,
                    object_id=obj.id,
                    locator_key=col.locator_key,
                    name=col.name,
                    ordinal=col.ordinal,
                    data_type=col.data_type,
                    normalized_type=col.normalized_type,
                    nullable=col.nullable,
                    default_value=col.default_value,
                    comment=col.comment,
                    is_present=col.is_present,
                    business_name=col.business_name,
                    business_description=col.business_description,
                    column_semantics_json=_dumps_json(col.column_semantics),
                    enum_catalog_json=_dumps_json(col.enum_catalog),
                    semantic_source=col.semantic_source,
                    field_kind=col.field_kind or "column",
                    created_at=col.created_at,
                    updated_at=col.updated_at,
                )
            )
        else:
            prev.locator_key = col.locator_key
            prev.name = col.name
            prev.ordinal = col.ordinal
            prev.data_type = col.data_type
            prev.normalized_type = col.normalized_type
            prev.nullable = col.nullable
            prev.default_value = col.default_value
            prev.comment = col.comment
            prev.field_kind = col.field_kind or prev.field_kind
            prev.is_present = col.is_present
            prev.updated_at = col.updated_at

    for cid, prev in col_by_id.items():
        if cid not in seen_col_ids:
            session.delete(prev)

    fk_by_id = {fk.id: fk for fk in list(row.foreign_keys) if fk.id}
    seen_fk_ids: set[str] = set()
    for fk in obj.foreign_keys:
        fk_id = fk.id
        if fk_id is None:
            raise ValueError(
                f"structure plan FK {fk.name!r} on object {obj.id} missing id"
            )
        seen_fk_ids.add(fk_id)
        prev = fk_by_id.get(fk_id)
        if prev is None:
            session.add(
                CatalogForeignKeyRow(
                    id=fk_id,
                    object_id=obj.id,
                    name=fk.name,
                    columns_json=_dumps_json(fk.columns) or "[]",
                    ref_schema=fk.ref_schema,
                    ref_table=fk.ref_table,
                    ref_columns_json=_dumps_json(fk.ref_columns) or "[]",
                    is_present=fk.is_present,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            prev.name = fk.name
            prev.columns_json = _dumps_json(fk.columns) or "[]"
            prev.ref_schema = fk.ref_schema
            prev.ref_table = fk.ref_table
            prev.ref_columns_json = _dumps_json(fk.ref_columns) or "[]"
            prev.is_present = fk.is_present
            prev.updated_at = now
    for fid, prev in fk_by_id.items():
        if fid not in seen_fk_ids:
            session.delete(prev)

    idx_by_id = {idx.id: idx for idx in list(row.indexes) if idx.id}
    seen_idx_ids: set[str] = set()
    for idx in obj.indexes:
        idx_id = idx.id
        if idx_id is None:
            raise ValueError(
                f"structure plan index {idx.name!r} on object {obj.id} missing id"
            )
        seen_idx_ids.add(idx_id)
        prev = idx_by_id.get(idx_id)
        if prev is None:
            session.add(
                CatalogIndexRow(
                    id=idx_id,
                    object_id=obj.id,
                    name=idx.name,
                    columns_json=_dumps_json(idx.columns) or "[]",
                    is_unique=idx.is_unique,
                    is_present=idx.is_present,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            prev.name = idx.name
            prev.columns_json = _dumps_json(idx.columns) or "[]"
            prev.is_unique = idx.is_unique
            prev.is_present = idx.is_present
            prev.updated_at = now
    for iid, prev in idx_by_id.items():
        if iid not in seen_idx_ids:
            session.delete(prev)


def _row_to_column(row: object) -> CatalogColumnRecord:
    assert isinstance(row, CatalogColumnRow)
    return CatalogColumnRecord(
        id=row.id,
        object_id=row.object_id,
        locator_key=row.locator_key,
        name=row.name,
        ordinal=row.ordinal,
        data_type=row.data_type,
        nullable=row.nullable,
        is_present=row.is_present,
        default_value=row.default_value,
        comment=row.comment,
        business_name=row.business_name,
        business_description=row.business_description,
        column_semantics=_loads_json(row.column_semantics_json),
        enum_catalog=_loads_json(row.enum_catalog_json),
        semantic_source=row.semantic_source,
        field_kind=row.field_kind,
        created_at=row.created_at,
        updated_at=row.updated_at,
        normalized_type=row.normalized_type,
    )


def _row_to_join(row: object) -> CatalogJoinRecord:
    assert isinstance(row, CatalogJoinRow)
    return CatalogJoinRecord(
        id=row.id,
        from_column_id=row.from_column_id,
        to_column_id=row.to_column_id,
        evidence=row.evidence,
        join_kind=row.join_kind,
        join_expression=row.join_expression,
        created_by_user_id=row.created_by_user_id,
        created_at=row.created_at,
        rejected_at=row.rejected_at,
        rejected_by_user_id=row.rejected_by_user_id,
    )


def _row_to_join_change(row: object) -> CatalogJoinChangeRecord:
    assert isinstance(row, CatalogJoinChangeRow)
    return CatalogJoinChangeRecord(
        id=row.id,
        from_column_id=row.from_column_id,
        to_column_id=row.to_column_id,
        kind=row.kind,
        attester=row.attester,
        actor_user_id=row.actor_user_id,
        created_at=row.created_at,
    )


def _row_to_semantics_change(row: CatalogSemanticsChangeRow) -> CatalogSemanticsChangeRecord:
    return CatalogSemanticsChangeRecord(
        id=row.id,
        object_id=row.object_id,
        column_id=row.column_id,
        field_name=row.field_name,
        old_value=row.old_value,
        new_value=row.new_value,
        semantic_source=row.semantic_source,
        actor_user_id=row.actor_user_id,
        created_at=row.created_at,
    )


def _row_to_embedding(row: CatalogEmbeddingRow) -> CatalogEmbeddingRecord:
    return CatalogEmbeddingRecord(
        id=row.id,
        kind=row.kind,
        target_id=row.target_id,
        locator_key=row.locator_key,
        content_hash=row.content_hash,
        embedding=list(row.embedding or []),
        indexed_at=row.indexed_at,
        generation=row.generation,
    )


def _row_to_object(
    row: object, *, include_structure: bool = True
) -> CatalogObjectRecord:
    assert isinstance(row, CatalogObjectRow)
    columns: list[CatalogColumnRecord] = []
    foreign_keys: list[CatalogForeignKeyRecord] = []
    indexes: list[CatalogIndexRecord] = []
    ddl: str | None = None
    if include_structure:
        columns = [
            _row_to_column(c) for c in sorted(row.columns, key=lambda x: x.ordinal)
        ]
        foreign_keys = [
            CatalogForeignKeyRecord(
                id=fk.id,
                name=fk.name,
                columns=_loads_json(fk.columns_json) or [],
                ref_schema=fk.ref_schema,
                ref_table=fk.ref_table,
                ref_columns=_loads_json(fk.ref_columns_json) or [],
                is_present=fk.is_present,
            )
            for fk in getattr(row, "foreign_keys", []) or []
        ]
        indexes = [
            CatalogIndexRecord(
                id=idx.id,
                name=idx.name,
                columns=_loads_json(idx.columns_json) or [],
                is_unique=idx.is_unique,
                is_present=idx.is_present,
            )
            for idx in getattr(row, "indexes", []) or []
        ]
        ddl = row.ddl
    return CatalogObjectRecord(
        id=row.id,
        source_id=row.source_id,
        locator_key=row.locator_key,
        object_type=row.object_type,
        schema_name=row.schema_name,
        name=row.name,
        ddl=ddl,
        comment=row.comment,
        primary_key=_loads_json(row.primary_key_json),
        is_present=row.is_present,
        business_name=row.business_name,
        business_description=row.business_description,
        object_category=row.object_category,
        grain_description=row.grain_description,
        business_primary_key=_loads_json(row.business_primary_key_json),
        business_domain_id=row.business_domain_id,
        evidence_summary=_loads_json(row.evidence_summary_json),
        open_questions=_loads_json(row.open_questions_json),
        semantic_source=row.semantic_source,
        business_semantics_ready=row.business_semantics_ready,
        semantics_updated_at=row.semantics_updated_at,
        last_structure_job_id=row.last_structure_job_id,
        collected_at=row.collected_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        columns=columns,
        foreign_keys=foreign_keys,
        indexes=indexes,
    )
