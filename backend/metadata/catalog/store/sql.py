"""SQL CatalogStore persistence adapter."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from typing import Any

from backend.core.db import session_scope
from backend.metadata.catalog.fk_join_sync import (
    _PROTECTED_JOIN_ORIGINS,
    _fk_edges_for_object,
)
from backend.metadata.catalog.identity import (
    _incoming_covers_existing,
    _match_existing_for_incoming,
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
    CatalogWriteAborted,
    new_column_id,
    new_fk_id,
    new_index_id,
    new_join_id,
)
from backend.metadata.catalog.search_rank import _paginate, _search_rank


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
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from backend.core.db import session_scope
        from backend.metadata.models import (
            CatalogColumnRow,
            CatalogForeignKeyRow,
            CatalogIndexRow,
            CatalogObjectRow,
        )

        now = datetime.utcnow()
        incoming_keys = {(o.schema_name, o.name, o.object_type): o for o in objects}

        with session_scope() as session:
            stmt = (
                select(CatalogObjectRow)
                .where(CatalogObjectRow.source_id == source_id)
                .options(
                    selectinload(CatalogObjectRow.columns),
                    selectinload(CatalogObjectRow.foreign_keys),
                    selectinload(CatalogObjectRow.indexes),
                )
            )
            if schema_scope is not None:
                stmt = stmt.where(CatalogObjectRow.schema_name == schema_scope)
            existing_rows = list(session.scalars(stmt).all())
            existing_by_key = {
                (r.schema_name, r.name, r.object_type): r for r in existing_rows
            }

            for key, row in list(existing_by_key.items()):
                if _incoming_covers_existing(
                    existing_schema=row.schema_name,
                    existing_name=row.name,
                    existing_type=row.object_type,
                    incoming_keys=incoming_keys,
                ):
                    continue
                row.is_present = False
                row.last_structure_job_id = job_id
                row.updated_at = now
                for col in row.columns:
                    col.is_present = False
                    col.updated_at = now
                for fk in row.foreign_keys:
                    fk.is_present = False
                    fk.updated_at = now
                for idx in row.indexes:
                    idx.is_present = False
                    idx.updated_at = now
                _sql_tombstone_fk_joins(session, row)

            touched_object_ids: list[str] = []
            for key, incoming in incoming_keys.items():
                obj_locator = _recompute_object_locator(
                    engine=engine,
                    kind=kind,
                    source_key=source_key,
                    schema_name=incoming.schema_name,
                    object_type=incoming.object_type,
                    name=incoming.name,
                )
                row = _match_existing_for_incoming(
                    schema_name=incoming.schema_name,
                    name=incoming.name,
                    object_type=incoming.object_type,
                    existing_by_key=existing_by_key,
                )
                if row is None:
                    obj = CatalogObjectRow(
                        id=incoming.id,
                        source_id=source_id,
                        locator_key=obj_locator,
                        object_type=incoming.object_type,
                        schema_name=incoming.schema_name,
                        name=incoming.name,
                        ddl=incoming.ddl,
                        comment=incoming.comment,
                        primary_key_json=_dumps_json(incoming.primary_key),
                        is_present=True,
                        business_name=None,
                        business_description=None,
                        object_category=None,
                        grain_description=None,
                        business_primary_key_json=None,
                        business_domain_id=None,
                        evidence_summary_json=None,
                        open_questions_json=None,
                        semantic_source=None,
                        business_semantics_ready=False,
                        semantics_updated_at=None,
                        last_structure_job_id=job_id,
                        collected_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(obj)
                    for col in incoming.columns:
                        col_locator = _recompute_column_locator(
                            engine=engine,
                            kind=kind,
                            source_key=source_key,
                            schema_name=incoming.schema_name,
                            object_type=incoming.object_type,
                            name=incoming.name,
                            column_name=col.name,
                            field_kind=col.field_kind,
                        )
                        session.add(
                            CatalogColumnRow(
                                id=col.id,
                                object_id=incoming.id,
                                locator_key=col_locator,
                                name=col.name,
                                ordinal=col.ordinal,
                                data_type=col.data_type,
                                nullable=col.nullable,
                                default_value=col.default_value,
                                comment=col.comment,
                                is_present=True,
                                business_name=None,
                                business_description=None,
                                column_semantics_json=None,
                                enum_catalog_json=None,
                                semantic_source=None,
                                field_kind=col.field_kind or "column",
                                created_at=now,
                                updated_at=now,
                            )
                        )
                    for fk in incoming.foreign_keys:
                        session.add(
                            CatalogForeignKeyRow(
                                id=new_fk_id(),
                                object_id=incoming.id,
                                name=fk.name,
                                columns_json=_dumps_json(fk.columns) or "[]",
                                ref_schema=fk.ref_schema,
                                ref_table=fk.ref_table,
                                ref_columns_json=_dumps_json(fk.ref_columns) or "[]",
                                is_present=True,
                                created_at=now,
                                updated_at=now,
                            )
                        )
                    for idx in incoming.indexes:
                        session.add(
                            CatalogIndexRow(
                                id=new_index_id(),
                                object_id=incoming.id,
                                name=idx.name,
                                columns_json=_dumps_json(idx.columns) or "[]",
                                is_unique=idx.is_unique,
                                is_present=True,
                                created_at=now,
                                updated_at=now,
                            )
                        )
                    touched_object_ids.append(incoming.id)
                    continue

                row.locator_key = obj_locator
                row.object_type = incoming.object_type
                row.ddl = incoming.ddl
                row.comment = incoming.comment
                row.primary_key_json = _dumps_json(incoming.primary_key)
                row.is_present = True
                row.last_structure_job_id = job_id
                row.collected_at = now
                row.updated_at = now
                # never touch semantics fields

                col_by_name = {c.name: c for c in row.columns}
                seen: set[str] = set()
                for col in incoming.columns:
                    seen.add(col.name)
                    col_locator = _recompute_column_locator(
                        engine=engine,
                        kind=kind,
                        source_key=source_key,
                        schema_name=incoming.schema_name,
                        object_type=incoming.object_type,
                        name=incoming.name,
                        column_name=col.name,
                        field_kind=col.field_kind,
                    )
                    prev = col_by_name.get(col.name)
                    if prev is None:
                        session.add(
                            CatalogColumnRow(
                                id=new_column_id(),
                                object_id=row.id,
                                locator_key=col_locator,
                                name=col.name,
                                ordinal=col.ordinal,
                                data_type=col.data_type,
                                nullable=col.nullable,
                                default_value=col.default_value,
                                comment=col.comment,
                                is_present=True,
                                business_name=None,
                                business_description=None,
                                column_semantics_json=None,
                                enum_catalog_json=None,
                                semantic_source=None,
                                field_kind=col.field_kind or "column",
                                created_at=now,
                                updated_at=now,
                            )
                        )
                    else:
                        prev.locator_key = col_locator
                        prev.ordinal = col.ordinal
                        prev.data_type = col.data_type
                        prev.nullable = col.nullable
                        prev.default_value = col.default_value
                        prev.comment = col.comment
                        prev.field_kind = col.field_kind or prev.field_kind
                        prev.is_present = True
                        prev.updated_at = now
                for name, prev in col_by_name.items():
                    if name not in seen:
                        prev.is_present = False
                        prev.updated_at = now

                _sql_upsert_fks(session, row, incoming.foreign_keys, now=now)
                _sql_upsert_indexes(session, row, incoming.indexes, now=now)
                _sql_tombstone_fk_joins(session, row)
                touched_object_ids.append(row.id)

            session.flush()

            # Sync FK joins for the whole Source after structure is present.
            _sql_sync_fk_joins_for_source(session, source_id=source_id, now=now)
            session.flush()

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
                if origin == "foreign_key" and existing.origin in _PROTECTED_JOIN_ORIGINS:
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




def _sql_upsert_fks(
    session: Any,
    row: Any,
    incoming: list[CatalogForeignKeyRecord],
    *,
    now: datetime,
) -> None:
    from backend.metadata.models import CatalogForeignKeyRow

    by_name = {fk.name: fk for fk in row.foreign_keys}
    seen: set[str] = set()
    for fk in incoming:
        seen.add(fk.name)
        prev = by_name.get(fk.name)
        if prev is None:
            session.add(
                CatalogForeignKeyRow(
                    id=new_fk_id(),
                    object_id=row.id,
                    name=fk.name,
                    columns_json=_dumps_json(fk.columns) or "[]",
                    ref_schema=fk.ref_schema,
                    ref_table=fk.ref_table,
                    ref_columns_json=_dumps_json(fk.ref_columns) or "[]",
                    is_present=True,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            prev.columns_json = _dumps_json(fk.columns) or "[]"
            prev.ref_schema = fk.ref_schema
            prev.ref_table = fk.ref_table
            prev.ref_columns_json = _dumps_json(fk.ref_columns) or "[]"
            prev.is_present = True
            prev.updated_at = now
    for name, prev in by_name.items():
        if name not in seen:
            prev.is_present = False
            prev.updated_at = now


def _sql_upsert_indexes(
    session: Any,
    row: Any,
    incoming: list[CatalogIndexRecord],
    *,
    now: datetime,
) -> None:
    from backend.metadata.models import CatalogIndexRow

    by_name = {idx.name: idx for idx in row.indexes}
    seen: set[str] = set()
    for idx in incoming:
        seen.add(idx.name)
        prev = by_name.get(idx.name)
        if prev is None:
            session.add(
                CatalogIndexRow(
                    id=new_index_id(),
                    object_id=row.id,
                    name=idx.name,
                    columns_json=_dumps_json(idx.columns) or "[]",
                    is_unique=idx.is_unique,
                    is_present=True,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            prev.columns_json = _dumps_json(idx.columns) or "[]"
            prev.is_unique = idx.is_unique
            prev.is_present = True
            prev.updated_at = now
    for name, prev in by_name.items():
        if name not in seen:
            prev.is_present = False
            prev.updated_at = now


def _sql_tombstone_fk_joins(session: Any, row: Any) -> None:
    """Remove foreign_key-origin joins whose from-column belongs to this object."""
    from sqlalchemy import select

    from backend.metadata.models import CatalogJoinRow

    col_ids = [c.id for c in row.columns]
    if not col_ids:
        return
    joins = list(
        session.scalars(
            select(CatalogJoinRow).where(
                CatalogJoinRow.origin == "foreign_key",
                CatalogJoinRow.from_column_id.in_(col_ids),
            )
        ).all()
    )
    for join in joins:
        session.delete(join)


def _sql_sync_fk_joins_for_source(
    session: Any, *, source_id: str, now: datetime
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from backend.metadata.models import CatalogJoinRow, CatalogObjectRow

    rows = list(
        session.scalars(
            select(CatalogObjectRow)
            .where(CatalogObjectRow.source_id == source_id)
            .options(
                selectinload(CatalogObjectRow.columns),
                selectinload(CatalogObjectRow.foreign_keys),
            )
        ).all()
    )
    present_records = [_row_to_object(r) for r in rows if r.is_present]
    expected: dict[tuple[str, str], tuple[str, str]] = {}
    for obj in present_records:
        for from_id, to_id, evidence, expression in _fk_edges_for_object(
            obj, present_objects=present_records
        ):
            expected[(from_id, to_id)] = (evidence, expression)

    source_col_ids = {c.id for r in rows for c in r.columns}
    if source_col_ids:
        joins = list(
            session.scalars(
                select(CatalogJoinRow).where(
                    CatalogJoinRow.origin == "foreign_key",
                    CatalogJoinRow.from_column_id.in_(source_col_ids),
                )
            ).all()
        )
        for join in joins:
            if (join.from_column_id, join.to_column_id) not in expected:
                session.delete(join)

    for (from_id, to_id), (evidence, expression) in expected.items():
        existing = session.scalars(
            select(CatalogJoinRow).where(
                CatalogJoinRow.from_column_id == from_id,
                CatalogJoinRow.to_column_id == to_id,
            )
        ).first()
        if existing is not None:
            if existing.origin in _PROTECTED_JOIN_ORIGINS:
                continue
            existing.evidence = evidence
            existing.join_kind = "INNER"
            existing.join_expression = expression
            existing.origin = "foreign_key"
        else:
            session.add(
                CatalogJoinRow(
                    id=new_join_id(),
                    from_column_id=from_id,
                    to_column_id=to_id,
                    evidence=evidence,
                    join_kind="INNER",
                    join_expression=expression,
                    origin="foreign_key",
                    created_by_user_id=None,
                    created_at=now,
                )
            )


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



