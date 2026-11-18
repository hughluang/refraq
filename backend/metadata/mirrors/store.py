"""SQL and rollback-capable memory persistence for mirror management."""

from contextlib import contextmanager
from copy import deepcopy
from threading import RLock

from sqlalchemy import select, text

from backend.core.db import session_scope
from backend.metadata.catalog.store import get_catalog_store
from backend.metadata.models import CatalogObjectRow, SourceRow
from backend.metadata.mirrors.models import (
    MirrorIntentReceiptRow, MirrorOperationRow, MirrorPublicationRow,
    MirrorReferenceRow, MirrorRow,
)
from backend.metadata.sources.store import get_source_store


class MemoryMirrorStore:
    def __init__(self):
        self.mirrors = {}
        self.operations = {}
        self.references = {}
        self.publications = {}
        self.receipts = {}
        self.bindings = {}
        self.lock = RLock()

    @contextmanager
    def transaction(self):
        with self.lock:
            before = deepcopy((self.mirrors, self.operations, self.references, self.publications, self.receipts))
            try:
                yield self
            except BaseException:
                (self.mirrors, self.operations, self.references, self.publications, self.receipts) = before
                raise

    def lock_channel(self, session, channel_id):
        if session is not self:
            raise ValueError("Memory mirror calls require the caller's memory transaction")

    def binding(self, session, object_id):
        if object_id in self.bindings:
            return deepcopy(self.bindings[object_id])
        obj = get_catalog_store().get_object(object_id)
        source = get_source_store().get_source(obj.source_id) if obj else None
        return _binding(obj, source)

    def preview_binding(self, session, object_id):
        return self.binding(session, object_id)

    def preview_mirrors(self, session):
        return self.list(session)

    def list(self, session):
        return deepcopy(list(self.mirrors.values()))

    def save(self, session, state):
        old = self.mirrors.get(state["id"])
        if old and any(old[key] != state[key] for key in ("source_id", "table_identity", "object_id", "qualified_table")):
            raise ValueError("Immutable mirror binding")
        self.mirrors[state["id"]] = deepcopy(state)

    def refs(self, session):
        return deepcopy(self.references)

    def replace_refs(self, session, channel_id, version, mirror_ids):
        self.references = {key: value for key, value in self.references.items() if key[0] != channel_id}
        self.references.update({(channel_id, mid): version for mid in mirror_ids})

    def publication(self, session, channel_id):
        return deepcopy(self.publications.get(channel_id))

    def save_publication(self, session, channel_id, version, object_ids):
        self.publications[channel_id] = {"channel_version": version, "object_ids": list(object_ids)}

    def receipt(self, session, operation_id):
        return deepcopy(self.receipts.get(operation_id))

    def save_receipt(self, session, operation_id, request, result):
        self.receipts[operation_id] = deepcopy({"request": request, "result": result})

    def ops(self, session, mirror_id):
        return deepcopy([op for op in self.operations.values() if op["mirror_id"] == mirror_id])

    def save_op(self, session, op):
        self.operations[op["id"]] = deepcopy(op)

    def delete(self, session, mirror_id):
        del self.mirrors[mirror_id]
        self.operations = {key: op for key, op in self.operations.items() if op["mirror_id"] != mirror_id}


class SqlMirrorStore:
    transaction = staticmethod(session_scope)

    def lock_channel(self, session, channel_id):
        self._lock_registry(session)

    def _lock_registry(self, session):
        if session.bind.dialect.name == "postgresql":
            session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": "mirror-management-registry"})

    def binding(self, session, object_id):
        self._lock_registry(session)
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

    def preview_mirrors(self, session):
        with session.no_autoflush:
            return [deepcopy(row.state) for row in session.scalars(
                select(MirrorRow).order_by(MirrorRow.id).execution_options(populate_existing=True)
            )]

    def list(self, session):
        self._lock_registry(session)
        return [deepcopy(row.state) for row in session.scalars(select(MirrorRow).order_by(MirrorRow.id).with_for_update().execution_options(populate_existing=True))]

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

    def refs(self, session):
        return {(row.channel_id, row.mirror_id): row.channel_version for row in session.scalars(select(MirrorReferenceRow))}

    def replace_refs(self, session, channel_id, version, mirror_ids):
        for row in session.scalars(select(MirrorReferenceRow).where(MirrorReferenceRow.channel_id == channel_id)):
            session.delete(row)
        session.flush()
        session.add_all([MirrorReferenceRow(channel_id=channel_id, mirror_id=mid, channel_version=version) for mid in mirror_ids])
        session.flush()

    def publication(self, session, channel_id):
        row = session.get(MirrorPublicationRow, channel_id)
        return {"channel_version": row.channel_version, "object_ids": row.object_ids} if row else None

    def save_publication(self, session, channel_id, version, object_ids):
        session.merge(MirrorPublicationRow(channel_id=channel_id, channel_version=version, object_ids=list(object_ids)))
        session.flush()

    def receipt(self, session, operation_id):
        row = session.get(MirrorIntentReceiptRow, operation_id)
        return {"request": row.request, "result": row.result} if row else None

    def save_receipt(self, session, operation_id, request, result):
        session.add(MirrorIntentReceiptRow(operation_id=operation_id, request=deepcopy(request), result=deepcopy(result)))
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
