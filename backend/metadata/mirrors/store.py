"""SQL and rollback-capable memory persistence for mirror management."""

from contextlib import contextmanager
from copy import deepcopy
from threading import RLock

from sqlalchemy import func, or_, select, text

from backend.core.db import session_scope
from backend.metadata.catalog.store import get_catalog_store
from backend.metadata.models import CatalogObjectRow, SourceRow
from backend.metadata.mirrors.models import MirrorOperationRow, MirrorRow
from backend.metadata.sources.store import get_source_store


class MemoryMirrorStore:
    def __init__(self):
        self.mirrors = {}
        self.operations = {}
        self.bindings = {}
        self.lock = RLock()

    @contextmanager
    def transaction(self):
        with get_source_store().capture_lock, self.lock:
            before = deepcopy((self.mirrors, self.operations))
            try:
                yield self
            except BaseException:
                (self.mirrors, self.operations) = before
                raise

    def lock_registry(self, session):
        if session is not self:
            raise ValueError("Memory mirror calls require the caller's memory transaction")

    def lock_sources(self, session, source_ids):
        self.lock_registry(session)

    def scope_rows(self, session, source_id):
        return [row for row in self.mirrors.values() if row["source_id"] == source_id]

    def binding(self, session, object_id):
        if object_id in self.bindings:
            return deepcopy(self.bindings[object_id])
        obj = get_catalog_store().get_object(object_id)
        source = get_source_store().get_source(obj.source_id) if obj else None
        return _binding(obj, source)

    def preview_binding(self, session, object_id):
        return self.binding(session, object_id)

    def get(self, session, mirror_id):
        return deepcopy(self.mirrors.get(mirror_id))

    def get_by_object(self, session, source_id, object_id):
        return next((deepcopy(row) for row in self.mirrors.values()
                     if row["source_id"] == source_id and row["table_identity"] == object_id), None)

    def page(self, session, *, source_id, status, q, limit, offset):
        needle = (q or "").casefold()
        rows = sorted((
            row for row in self.mirrors.values()
            if (source_id is None or row["source_id"] == source_id)
            and (status is None or row["status"] == status)
            and any(needle in row[key].casefold() for key in ("source_key", "source_name", "qualified_table"))
        ), key=lambda row: (row["source_key"], row["qualified_table"], row["id"]))
        return deepcopy(rows[offset:offset + limit]), len(rows)

    def save(self, session, state):
        old = self.mirrors.get(state["id"])
        if old and any(old[key] != state[key] for key in ("source_id", "table_identity", "object_id", "qualified_table")):
            raise ValueError("Immutable mirror binding")
        self.mirrors[state["id"]] = deepcopy(state)

    def ops(self, session, mirror_id):
        return deepcopy([op for op in self.operations.values() if op["mirror_id"] == mirror_id])

    def save_op(self, session, op):
        self.operations[op["id"]] = deepcopy(op)

    def delete(self, session, mirror_id):
        del self.mirrors[mirror_id]
        self.operations = {key: op for key, op in self.operations.items() if op["mirror_id"] != mirror_id}


class SqlMirrorStore:
    transaction = staticmethod(session_scope)

    def lock_registry(self, session):
        if session.bind.dialect.name == "postgresql":
            session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": "mirror-management-registry"})

    def lock_sources(self, session, source_ids):
        if source_ids:
            session.scalars(select(SourceRow.id).where(SourceRow.id.in_(source_ids))
                            .order_by(SourceRow.id).with_for_update()).all()

    def scope_rows(self, session, source_id):
        return session.scalars(select(MirrorRow.state).where(MirrorRow.source_id == source_id)).all()

    def binding(self, session, object_id):
        obj = session.get(CatalogObjectRow, object_id)
        if obj is None:
            return None
        source = session.scalar(select(SourceRow).where(SourceRow.id == obj.source_id).with_for_update())
        obj = session.scalar(select(CatalogObjectRow).where(CatalogObjectRow.id == object_id).with_for_update().execution_options(populate_existing=True))
        return _binding(obj, source)

    def preview_binding(self, session, object_id):
        with session.no_autoflush:
            obj = session.get(CatalogObjectRow, object_id, populate_existing=True)
            source = session.get(SourceRow, obj.source_id, populate_existing=True) if obj else None
            return _binding(obj, source)

    def get(self, session, mirror_id):
        return session.scalar(select(MirrorRow.state).where(MirrorRow.id == mirror_id))

    def get_by_object(self, session, source_id, object_id):
        return session.scalar(select(MirrorRow.state).where(
            MirrorRow.source_id == source_id, MirrorRow.table_identity == object_id
        ))

    def page(self, session, *, source_id, status, q, limit, offset):
        criteria = []
        if source_id is not None:
            criteria.append(MirrorRow.source_id == source_id)
        if status is not None:
            criteria.append(MirrorRow.state["status"].as_string() == status)
        source_key = MirrorRow.state["source_key"].as_string()
        table = MirrorRow.state["qualified_table"].as_string()
        postgres = session.get_bind().dialect.name == "postgresql"
        if q:
            fields = (source_key, MirrorRow.state["source_name"].as_string(), table)
            if postgres:
                fields = tuple(func.casefold(field.collate("pg_unicode_fast")) for field in fields)
                criteria.append(or_(*(field.contains(q.casefold(), autoescape=True) for field in fields)))
            else:
                criteria.append(or_(*(field.icontains(q, autoescape=True) for field in fields)))
        order = (source_key, table, MirrorRow.id)
        if postgres:
            order = tuple(column.collate("C") for column in order)
        total = session.scalar(select(func.count()).select_from(MirrorRow).where(*criteria))
        rows = session.scalars(select(MirrorRow.state).where(*criteria).order_by(*order)
                               .limit(limit).offset(offset)).all()
        return rows, total

    def save(self, session, state):
        row = session.get(MirrorRow, state["id"])
        if row is None:
            session.add(MirrorRow(id=state["id"], source_id=state["source_id"], table_identity=state["table_identity"], enabled=state["enabled"], state=deepcopy(state)))
        else:
            if any(row.state[key] != state[key] for key in ("source_id", "table_identity", "object_id", "qualified_table")):
                raise ValueError("Immutable mirror binding")
            row.enabled = state["enabled"]
            row.state = deepcopy(state)
        session.flush()

    def ops(self, session, mirror_id):
        return [deepcopy(row.command) for row in session.scalars(select(MirrorOperationRow).where(MirrorOperationRow.mirror_id == mirror_id))]

    def save_op(self, session, op):
        session.merge(MirrorOperationRow(id=op["id"], mirror_id=op["mirror_id"], command=deepcopy(op)))
        session.flush()

    def delete(self, session, mirror_id):
        for row in session.scalars(select(MirrorOperationRow).where(MirrorOperationRow.mirror_id == mirror_id)):
            session.delete(row)
        session.flush()
        session.delete(session.get(MirrorRow, mirror_id))
        session.flush()


def _binding(obj, source):
    if obj is None or source is None or not obj.is_present or obj.object_type != "table" or source.kind != "database" or source.engine != "postgresql":
        return None
    return dict(source_id=source.id, object_id=obj.id, source_key=source.key, source_name=source.name, qualified_table=f"{obj.schema_name}.{obj.name}", table_identity=obj.id)
