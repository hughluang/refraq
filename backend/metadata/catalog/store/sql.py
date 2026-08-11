"""SQL CatalogStore persistence adapter."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from backend.core.db import session_scope
from backend.metadata.catalog.fk_join_sync import PROTECTED_JOIN_ORIGINS
from backend.metadata.catalog.identity import (
    _recompute_column_locator,
    _recompute_object_locator,
)
from backend.metadata.catalog.records import (
    UNSET,
    CatalogColumnRecord,
    CatalogForeignKeyRecord,
    CatalogIndexRecord,
    CatalogJoinRecord,
    CatalogObjectRecord,
    new_join_id,
)
from backend.metadata.catalog.search_rank import _paginate, _search_rank
from backend.metadata.catalog.structure_merge import build_structure_refresh_plan


def _dumps_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value)


def _loads_json(raw: str | None) -> Any:
    if raw is None:
        return None
    return json.loads(raw)




class SqlCatalogStore:
    def list_objects(
        self,
        source_id: str,
        *,
        name_search: str | None = None,
        include_absent: bool = True,
        object_type: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[CatalogObjectRecord], int]:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from backend.core.db import session_scope
        from backend.metadata.models import CatalogObjectRow

        with session_scope() as session:
            stmt = (
                select(CatalogObjectRow)
                .where(CatalogObjectRow.source_id == source_id)
                .options(selectinload(CatalogObjectRow.columns))
                .order_by(
                    CatalogObjectRow.schema_name,
                    CatalogObjectRow.name,
                    CatalogObjectRow.object_type,
                )
            )
            if not include_absent:
                stmt = stmt.where(CatalogObjectRow.is_present.is_(True))
            if object_type is not None:
                stmt = stmt.where(CatalogObjectRow.object_type == object_type)
            rows = session.scalars(stmt).all()
            records = [_row_to_object(r) for r in rows]
            if name_search:
                q = name_search.lower()
                records = [
                    o
                    for o in records
                    if q in o.name.lower() or q in o.schema_name.lower()
                ]
            total = len(records)
            return _paginate(records, limit=limit, offset=offset), total

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
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from backend.core.db import session_scope
        from backend.metadata.models import CatalogObjectRow

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
            ranked: list[tuple[int, CatalogObjectRecord]] = []
            for row in rows:
                obj = _row_to_object(row)
                rank = _search_rank(
                    query,
                    locator_key=obj.locator_key,
                    name=obj.name,
                    schema_name=obj.schema_name,
                    business_name=obj.business_name,
                    business_description=obj.business_description,
                )
                if rank is None:
                    continue
                ranked.append((rank, obj))
            ranked.sort(key=lambda t: (t[0], t[1].schema_name, t[1].name, t[1].id))
            total = len(ranked)
            page = [o for _, o in _paginate(ranked, limit=limit, offset=offset)]
            return page, total

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
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from backend.core.db import session_scope
        from backend.metadata.models import CatalogObjectRow

        with session_scope() as session:
            stmt = select(CatalogObjectRow).options(
                selectinload(CatalogObjectRow.columns)
            )
            if source_id is not None:
                stmt = stmt.where(CatalogObjectRow.source_id == source_id)
            if object_type is not None:
                stmt = stmt.where(CatalogObjectRow.object_type == object_type)
            rows = session.scalars(stmt).all()
            ranked: list[tuple[int, CatalogColumnRecord]] = []
            for row in rows:
                obj = _row_to_object(row)
                for col in obj.columns:
                    if not include_absent and not col.is_present:
                        continue
                    rank = _search_rank(
                        query,
                        locator_key=col.locator_key,
                        name=col.name,
                        business_name=col.business_name,
                        business_description=col.business_description,
                    )
                    if rank is None:
                        continue
                    ranked.append((rank, col))
            ranked.sort(key=lambda t: (t[0], t[1].name, t[1].id))
            total = len(ranked)
            page = [c for _, c in _paginate(ranked, limit=limit, offset=offset)]
            return page, total

    def get_object(self, object_id: str) -> CatalogObjectRecord | None:
        from sqlalchemy.orm import selectinload

        from backend.core.db import session_scope
        from backend.metadata.models import CatalogObjectRow

        with session_scope() as session:
            row = session.get(
                CatalogObjectRow,
                object_id,
                options=(selectinload(CatalogObjectRow.columns),),
            )
            return _row_to_object(row) if row else None

    def get_object_by_locator(self, locator_key: str) -> CatalogObjectRecord | None:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from backend.core.db import session_scope
        from backend.metadata.models import CatalogObjectRow

        with session_scope() as session:
            row = session.scalars(
                select(CatalogObjectRow)
                .where(CatalogObjectRow.locator_key == locator_key)
                .options(selectinload(CatalogObjectRow.columns))
            ).first()
            return _row_to_object(row) if row else None

    def get_column(self, column_id: str) -> CatalogColumnRecord | None:
        from backend.core.db import session_scope
        from backend.metadata.models import CatalogColumnRow

        with session_scope() as session:
            row = session.get(CatalogColumnRow, column_id)
            return _row_to_column(row) if row else None

    def get_column_by_locator(self, locator_key: str) -> CatalogColumnRecord | None:
        from sqlalchemy import select

        from backend.core.db import session_scope
        from backend.metadata.models import CatalogColumnRow

        with session_scope() as session:
            row = session.scalars(
                select(CatalogColumnRow).where(
                    CatalogColumnRow.locator_key == locator_key
                )
            ).first()
            return _row_to_column(row) if row else None

    def list_present_for_source(self, source_id: str) -> list[CatalogObjectRecord]:
        items, _ = self.list_objects(source_id, include_absent=False)
        return items

    def apply_structure_plan(
        self,
        *,
        source_id: str,
        job_id: str,
        objects: list[CatalogObjectRecord],
        schema_scope: str | None,
        fail_safe_threshold: float,
        engine: str | None,
        kind: str,
        source_key: str,
    ) -> None:
        """Atomic load → build plan → persist (zero merge rules in adapter)."""
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from backend.core.db import session_scope
        from backend.metadata.models import (
            CatalogJoinRow,
            CatalogObjectRow,
        )

        now = datetime.utcnow()
        with session_scope() as session:
            rows = list(
                session.scalars(
                    select(CatalogObjectRow)
                    .where(CatalogObjectRow.source_id == source_id)
                    .options(
                        selectinload(CatalogObjectRow.columns),
                        selectinload(CatalogObjectRow.foreign_keys),
                        selectinload(CatalogObjectRow.indexes),
                    )
                ).all()
            )
            existing_objects = [_row_to_object(r) for r in rows]
            col_ids = [c.id for o in existing_objects for c in o.columns]
            existing_joins: list[CatalogJoinRecord] = []
            if col_ids:
                from sqlalchemy import or_

                join_rows = list(
                    session.scalars(
                        select(CatalogJoinRow).where(
                            or_(
                                CatalogJoinRow.from_column_id.in_(col_ids),
                                CatalogJoinRow.to_column_id.in_(col_ids),
                            )
                        )
                    ).all()
                )
                existing_joins = [_row_to_join(j) for j in join_rows]

            plan = build_structure_refresh_plan(
                source_id=source_id,
                job_id=job_id,
                existing_objects=existing_objects,
                existing_joins=existing_joins,
                incoming=objects,
                schema_scope=schema_scope,
                fail_safe_threshold=fail_safe_threshold,
                engine=engine,
                kind=kind,
                source_key=source_key,
                now=now,
            )

            for obj in plan.objects:
                _sql_persist_object(session, obj, now=now)

            for jid in plan.delete_join_ids:
                row = session.get(CatalogJoinRow, jid)
                if row is not None:
                    session.delete(row)

            for upsert in plan.upsert_joins:
                existing = session.scalars(
                    select(CatalogJoinRow).where(
                        CatalogJoinRow.from_column_id == upsert.from_column_id,
                        CatalogJoinRow.to_column_id == upsert.to_column_id,
                    )
                ).first()
                if existing is not None:
                    existing.evidence = upsert.evidence
                    existing.join_kind = upsert.join_kind
                    existing.join_expression = upsert.join_expression
                    existing.origin = upsert.origin
                else:
                    session.add(
                        CatalogJoinRow(
                            id=new_join_id(),
                            from_column_id=upsert.from_column_id,
                            to_column_id=upsert.to_column_id,
                            evidence=upsert.evidence,
                            join_kind=upsert.join_kind,
                            join_expression=upsert.join_expression,
                            origin=upsert.origin,
                            created_by_user_id=None,
                            created_at=now,
                        )
                    )
            session.flush()

    def replace_structure_snapshot(
        self,
        *,
        source_id: str,
        job_id: str,
        objects: list[CatalogObjectRecord],
        schema_scope: str | None,
        engine: str | None,
        kind: str,
        source_key: str,
    ) -> None:
        """Deprecated seed helper — prefer apply_structure_snapshot / apply_structure_plan."""
        self.apply_structure_plan(
            source_id=source_id,
            job_id=job_id,
            objects=objects,
            schema_scope=schema_scope,
            fail_safe_threshold=1.0,
            engine=engine,
            kind=kind,
            source_key=source_key,
        )

    def recompute_locators_for_source(
        self,
        source_id: str,
        *,
        engine: str | None,
        kind: str,
        source_key: str,
    ) -> int:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from backend.core.db import session_scope
        from backend.metadata.models import CatalogObjectRow

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
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from backend.core.db import session_scope
        from backend.metadata.models import CatalogObjectRow

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
        from sqlalchemy.orm import selectinload

        from backend.core.db import session_scope
        from backend.metadata.models import CatalogObjectRow

        with session_scope() as session:
            row = session.get(
                CatalogObjectRow,
                object_id,
                options=(selectinload(CatalogObjectRow.columns),),
            )
            if row is None:
                return None
            now = datetime.utcnow()
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
        from backend.core.db import session_scope
        from backend.metadata.models import CatalogColumnRow

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
            row.updated_at = datetime.utcnow()
            session.flush()
            return _row_to_column(row)

    def get_join(self, join_id: str) -> CatalogJoinRecord | None:
        from backend.core.db import session_scope
        from backend.metadata.models import CatalogJoinRow

        with session_scope() as session:
            row = session.get(CatalogJoinRow, join_id)
            return _row_to_join(row) if row else None

    def list_joins_for_object(self, object_id: str) -> list[CatalogJoinRecord]:
        from sqlalchemy import or_, select

        from backend.core.db import session_scope
        from backend.metadata.models import CatalogColumnRow, CatalogJoinRow

        with session_scope() as session:
            col_ids = list(
                session.scalars(
                    select(CatalogColumnRow.id).where(
                        CatalogColumnRow.object_id == object_id
                    )
                ).all()
            )
            if not col_ids:
                return []
            rows = list(
                session.scalars(
                    select(CatalogJoinRow)
                    .where(
                        or_(
                            CatalogJoinRow.from_column_id.in_(col_ids),
                            CatalogJoinRow.to_column_id.in_(col_ids),
                        )
                    )
                    .order_by(CatalogJoinRow.created_at)
                ).all()
            )
            return [_row_to_join(r) for r in rows]

    def list_all_joins_for_source(self, source_id: str) -> list[CatalogJoinRecord]:
        from sqlalchemy import or_, select

        from backend.core.db import session_scope
        from backend.metadata.models import (
            CatalogColumnRow,
            CatalogJoinRow,
            CatalogObjectRow,
        )

        with session_scope() as session:
            col_ids = list(
                session.scalars(
                    select(CatalogColumnRow.id)
                    .join(
                        CatalogObjectRow,
                        CatalogColumnRow.object_id == CatalogObjectRow.id,
                    )
                    .where(CatalogObjectRow.source_id == source_id)
                ).all()
            )
            if not col_ids:
                return []
            rows = list(
                session.scalars(
                    select(CatalogJoinRow)
                    .where(
                        or_(
                            CatalogJoinRow.from_column_id.in_(col_ids),
                            CatalogJoinRow.to_column_id.in_(col_ids),
                        )
                    )
                    .order_by(CatalogJoinRow.created_at)
                ).all()
            )
            return [_row_to_join(r) for r in rows]

    def upsert_join(
        self,
        *,
        from_column_id: str,
        to_column_id: str,
        evidence: str,
        created_by_user_id: str | None,
        join_kind: str = "INNER",
        join_expression: str | None = None,
        origin: str = "human",
    ) -> CatalogJoinRecord:
        from sqlalchemy import select

        from backend.core.db import session_scope
        from backend.metadata.models import CatalogJoinRow

        now = datetime.utcnow()
        with session_scope() as session:
            existing = session.scalars(
                select(CatalogJoinRow).where(
                    CatalogJoinRow.from_column_id == from_column_id,
                    CatalogJoinRow.to_column_id == to_column_id,
                )
            ).first()
            if existing is not None:
                if origin == "foreign_key" and existing.origin in PROTECTED_JOIN_ORIGINS:
                    return _row_to_join(existing)
                existing.evidence = evidence
                existing.join_kind = join_kind
                existing.join_expression = join_expression
                existing.origin = origin
                session.flush()
                return _row_to_join(existing)
            row = CatalogJoinRow(
                id=new_join_id(),
                from_column_id=from_column_id,
                to_column_id=to_column_id,
                evidence=evidence,
                join_kind=join_kind,
                join_expression=join_expression,
                origin=origin,
                created_by_user_id=created_by_user_id,
                created_at=now,
            )
            session.add(row)
            session.flush()
            return _row_to_join(row)

    def delete_join(self, join_id: str) -> bool:
        from backend.core.db import session_scope
        from backend.metadata.models import CatalogJoinRow

        with session_scope() as session:
            row = session.get(CatalogJoinRow, join_id)
            if row is None:
                return False
            session.delete(row)
            session.flush()
            return True




def _sql_persist_object(session: Any, obj: CatalogObjectRecord, *, now: datetime) -> None:
    """Write a fully-merged CatalogObjectRecord (no merge rules)."""
    from sqlalchemy.orm import selectinload

    from backend.metadata.models import (
        CatalogColumnRow,
        CatalogForeignKeyRow,
        CatalogIndexRow,
        CatalogObjectRow,
    )

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
        # semantics fields intentionally not overwritten from plan merges

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
    from backend.metadata.models import CatalogColumnRow

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
    )


def _row_to_join(row: object) -> CatalogJoinRecord:
    from backend.metadata.models import CatalogJoinRow

    assert isinstance(row, CatalogJoinRow)
    return CatalogJoinRecord(
        id=row.id,
        from_column_id=row.from_column_id,
        to_column_id=row.to_column_id,
        evidence=row.evidence,
        join_kind=row.join_kind,
        join_expression=row.join_expression,
        origin=row.origin,
        created_by_user_id=row.created_by_user_id,
        created_at=row.created_at,
    )


def _row_to_object(row: object) -> CatalogObjectRecord:
    from backend.metadata.models import CatalogObjectRow

    assert isinstance(row, CatalogObjectRow)
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
    return CatalogObjectRecord(
        id=row.id,
        source_id=row.source_id,
        locator_key=row.locator_key,
        object_type=row.object_type,
        schema_name=row.schema_name,
        name=row.name,
        ddl=row.ddl,
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



