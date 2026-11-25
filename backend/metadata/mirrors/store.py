"""SQL and rollback-capable memory persistence for mirror management."""

from collections import defaultdict
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from threading import RLock

from sqlalchemy import and_, delete, func, or_, select, text
from sqlalchemy.orm import load_only

from backend.core.db import session_scope
from backend.metadata.catalog.store import get_catalog_store
from backend.metadata.capture.engines import CAPTURE_ENGINE_CODES, mirror_eligible
from backend.metadata.models import CatalogObjectRow, SourceCaptureBindingRow, SourceRow
from backend.metadata.mirrors.fleet_store import MemoryFleetStore, SqlFleetStore
from backend.metadata.mirrors.history_models import HistoryGateRow
from backend.metadata.mirrors.recovery_store import RecoveryRow
from backend.metadata.mirrors.lifecycle import registry_scope
from backend.metadata.mirrors.status_projection import pending_opens, refresh_source_status
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

    def published_scope(self, session, source_id):
        return registry_scope(self.scope_rows(session, source_id))

    def binding(self, session, object_id):
        if object_id in self.bindings:
            return deepcopy(self.bindings[object_id])
        obj = get_catalog_store().get_object(object_id)
        source = get_source_store().get_source(obj.source_id) if obj else None
        return catalog_binding(obj, source)

    def preview_binding(self, session, object_id):
        return self.binding(session, object_id)

    def get(self, session, mirror_id):
        return deepcopy(self.mirrors.get(mirror_id))

    def get_by_object(self, session, source_id, object_id):
        return next((deepcopy(row) for row in self.mirrors.values()
                     if row["source_id"] == source_id and row["table_identity"] == object_id), None)

    def catalog_tables(self, session, *, visible_ids, object_id, q, include_bound, limit, offset):
        sources, _ = get_source_store().list_sources(visible_ids=visible_ids)
        items = []
        for source in sources:
            objects, _ = get_catalog_store().list_objects(source.id, include_absent=True)
            mirrors = {m["table_identity"]: m for m in self.scope_rows(session, source.id)}
            for obj in objects:
                bound = mirrors.get(obj.id)
                eligible = mirror_eligible(source_kind=source.kind, engine=source.engine,
                                           object_type=obj.object_type, is_present=obj.is_present)
                if not (eligible or (bound and include_bound)):
                    continue
                if object_id is not None and obj.id != object_id:
                    continue
                if q and q.casefold() not in f"{obj.schema_name}.{obj.name}".casefold():
                    continue
                items.append((obj, source, bound))
        items.sort(key=lambda row: (row[1].key, row[0].schema_name, row[0].name, row[0].id))
        return items[offset:offset + limit], len(items)

    def pending_opens(self, session, mirror_ids):
        result = defaultdict(list)
        for op in self.operations.values():
            if op["mirror_id"] in mirror_ids and op["kind"] == "open" and op["state"] == "pending":
                result[op["mirror_id"]].append(op)
        return result

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

    def database(self, session):
        """Memory mirrors have no Management database session to join."""
        return None

    def history_gate(self, session, mirror_id, *, lock=False):
        return None

    def history_epoch(self, session, mirror):
        return mirror.get("history_epoch")

    def available_history_epoch(self, session, mirror, *, lock=False):
        return mirror["history_epoch"]

    def source(self, session, source_id):
        return get_source_store().get_source(source_id)

    def catalog_object(self, session, object_id):
        return get_catalog_store().get_object(object_id)

    def isolate_read(self, session):
        """Memory reads already run under the store lock."""

    def registry_rows(self, source_store):
        """Read every Mirror, Source capture binding and pending Open under the capture and registry locks."""
        with ExitStack() as stack:
            stack.enter_context(source_store.capture_lock)
            stack.enter_context(self.lock)
            rows = deepcopy(list(self.mirrors.values()))
            bindings = deepcopy(source_store.capture_bindings)
            pending = deepcopy([op for op in self.operations.values()
                                if op["kind"] == "open" and op["state"] == "pending"])
        return rows, bindings, pending

    def fleet(self, diagnostic_store, *, source_store, catalog_store, now):
        return MemoryFleetStore(self, diagnostic_store, source_store=source_store, catalog_store=catalog_store, now=now)


class SqlMirrorStore:
    transaction = staticmethod(session_scope)

    def lock_registry(self, session):
        if session.bind.dialect.name == "postgresql":
            session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": "mirror-management-registry"})

    def lock_sources(self, session, source_ids):
        if source_ids:
            session.scalars(select(SourceRow.id).where(SourceRow.id.in_(source_ids))
                            .order_by(SourceRow.id).with_for_update()).all()

    def published_scope(self, session, source_id):
        table = MirrorRow.state["qualified_table"].as_string()
        revision = MirrorRow.state["control"]["control_revision"].as_integer()
        rows = session.execute(select(MirrorRow.id, table, MirrorRow.table_identity, revision, MirrorRow.enabled)
                               .where(MirrorRow.source_id == source_id))
        return sorted((dict(mirror_id=mid, qualified_table=name, table_identity=identity, mirror_revision=rev,
                            included=enabled) for mid, name, identity, rev, enabled in rows),
                      key=lambda entry: (entry["qualified_table"], entry["mirror_id"]))

    def binding(self, session, object_id):
        obj = session.get(CatalogObjectRow, object_id)
        if obj is None:
            return None
        source = session.scalar(select(SourceRow).where(SourceRow.id == obj.source_id).with_for_update())
        obj = session.scalar(select(CatalogObjectRow).where(CatalogObjectRow.id == object_id).with_for_update().execution_options(populate_existing=True))
        return catalog_binding(obj, source)

    def preview_binding(self, session, object_id):
        with session.no_autoflush:
            obj = session.get(CatalogObjectRow, object_id, populate_existing=True)
            source = session.get(SourceRow, obj.source_id, populate_existing=True) if obj else None
            return catalog_binding(obj, source)

    def get(self, session, mirror_id):
        return session.scalar(select(MirrorRow.state).where(MirrorRow.id == mirror_id))

    def get_by_object(self, session, source_id, object_id):
        return session.scalar(select(MirrorRow.state).where(
            MirrorRow.source_id == source_id, MirrorRow.table_identity == object_id
        ))

    def catalog_tables(self, session, *, visible_ids, object_id, q, include_bound, limit, offset):
        obj = CatalogObjectRow
        eligible = and_(SourceRow.engine.in_(CAPTURE_ENGINE_CODES), SourceRow.kind == "database",
                        obj.is_present.is_(True), obj.object_type == "table")
        filters = [or_(eligible, MirrorRow.id.is_not(None)) if include_bound else eligible]
        if visible_ids is not None:
            filters.append(SourceRow.id.in_(visible_ids))
        if object_id is not None:
            filters.append(obj.id == object_id)
        name = obj.schema_name + "." + obj.name
        postgres = session.get_bind().dialect.name == "postgresql"
        if q:
            if postgres:
                filters.append(func.casefold(name.collate("pg_unicode_fast")).contains(q.casefold(), autoescape=True))
            else:
                filters.append(name.icontains(q, autoescape=True))
        query = (select(obj, SourceRow, MirrorRow.state)
                 .join(SourceRow, SourceRow.id == obj.source_id)
                 .outerjoin(MirrorRow, and_(MirrorRow.source_id == obj.source_id, MirrorRow.table_identity == obj.id))
                 .where(*filters))
        total = session.scalar(select(func.count()).select_from(query.with_only_columns(obj.id).subquery()))
        order = (SourceRow.key, obj.schema_name, obj.name, obj.id)
        if postgres:
            order = tuple(col.collate("C") for col in order)
        page = query.options(
            load_only(obj.id, obj.schema_name, obj.name, obj.source_id, obj.object_type, obj.is_present,
                      obj.source_size_bytes, obj.estimated_rows),
            load_only(SourceRow.id, SourceRow.key, SourceRow.name, SourceRow.kind, SourceRow.engine),
        ).order_by(*order).limit(limit).offset(offset)
        return session.execute(page).all(), total

    pending_opens = staticmethod(pending_opens)

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
        refresh_source_status(session, state["source_id"])

    def ops(self, session, mirror_id):
        return [deepcopy(row.command) for row in session.scalars(select(MirrorOperationRow).where(MirrorOperationRow.mirror_id == mirror_id))]

    def save_op(self, session, op):
        session.merge(MirrorOperationRow(id=op["id"], mirror_id=op["mirror_id"], command=deepcopy(op)))
        session.flush()
        mirror = session.get(MirrorRow, op["mirror_id"])
        refresh_source_status(session, mirror.source_id)

    def delete(self, session, mirror_id):
        for model in (RecoveryRow, HistoryGateRow, MirrorOperationRow):
            session.execute(delete(model).where(model.mirror_id == mirror_id))
        mirror = session.get(MirrorRow, mirror_id)
        source_id = mirror.source_id
        session.delete(mirror)
        session.flush()
        refresh_source_status(session, source_id)

    def database(self, session):
        return session

    def history_gate(self, session, mirror_id, *, lock=False):
        return session.get(HistoryGateRow, mirror_id, with_for_update=lock)

    def history_epoch(self, session, mirror):
        gate = session.get(HistoryGateRow, mirror["id"])
        return gate.history_epoch if gate is not None else None

    def available_history_epoch(self, session, mirror, *, lock=False):
        gate = session.get(HistoryGateRow, mirror["id"], with_for_update=lock)
        return gate.history_epoch if gate and gate.status == "available" else None

    def source(self, session, source_id):
        return session.get(SourceRow, source_id)

    def catalog_object(self, session, object_id):
        return session.get(CatalogObjectRow, object_id)

    def isolate_read(self, session):
        if session.get_bind().dialect.name == "postgresql":
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})

    def registry_rows(self, source_store):
        with self.transaction() as session:
            rows = list(session.scalars(select(MirrorRow.state)))
            bindings = {row.source_id: row.state for row in session.scalars(select(SourceCaptureBindingRow))}
            pending = list(session.scalars(select(MirrorOperationRow.command).where(
                MirrorOperationRow.command["kind"].as_string() == "open",
                MirrorOperationRow.command["state"].as_string() == "pending")))
        return rows, bindings, pending

    def fleet(self, diagnostic_store, *, source_store, catalog_store, now):
        return SqlFleetStore(self, now=now)


def catalog_binding(obj, source):
    if obj is None or source is None or not mirror_eligible(
            source_kind=source.kind, engine=source.engine, object_type=obj.object_type, is_present=obj.is_present):
        return None
    return dict(source_id=source.id, object_id=obj.id, source_key=source.key, source_name=source.name, source_engine=source.engine, qualified_table=f"{obj.schema_name}.{obj.name}", table_identity=obj.id)
