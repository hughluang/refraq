"""Entity Table port: Recording for memory and test binds; Postgres when persistent."""

from __future__ import annotations

import threading
from typing import Protocol

from sqlalchemy import text

from backend.core.config import get_settings, require_entity_database_url
from backend.entity.ddl import (
    comment_table_sql,
    create_table_statements,
    create_view_sql,
    drop_view_sql,
    qualified_table,
)
from backend.entity.entity_db import get_entity_engine
from backend.entity.records import AttributeRecord

__all__ = [
    "EntityTableHasRows",
    "EntityTableNameConflict",
    "EntityTablePort",
    "PostgresEntityTablePort",
    "RecordingEntityTablePort",
    "bind_entity_table_port",
    "get_entity_table_port",
    "reset_entity_table_port",
]


class EntityTablePort(Protocol):
    def table_exists(self, schema: str, table: str) -> bool: ...

    def drop_table(self, schema: str, table: str) -> None: ...

    def drop_head(self, schema: str, table: str, view: str) -> None: ...

    def create_physical_table(
        self,
        schema: str,
        table: str,
        attributes: list[AttributeRecord],
        *,
        comment: str | None = None,
    ) -> None: ...

    def swap_stem_view(
        self,
        schema: str,
        stem: str,
        *,
        physical: str,
        expected_target: str | None,
    ) -> None: ...

    def drop_stem_view(self, schema: str, stem: str) -> None: ...

    def revert_physical_table(self, schema: str, table: str) -> None: ...


class RecordingEntityTablePort:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self._tables: dict[tuple[str, str], dict[str, AttributeRecord]] = {}
        self._views: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()

    def table_exists(self, schema: str, table: str) -> bool:
        with self._lock:
            return (schema, table) in self._tables

    def drop_table(self, schema: str, table: str) -> None:
        sql = f"DROP TABLE {qualified_table(schema, table)}"
        with self._lock:
            self.statements.append(sql)
            self._tables.pop((schema, table), None)

    def drop_head(self, schema: str, table: str, view: str) -> None:
        with self._lock:
            self.statements.append(drop_view_sql(schema, view))
            self._views.pop((schema, view), None)
            self.statements.append(f"DROP TABLE {qualified_table(schema, table)}")
            self._tables.pop((schema, table), None)

    def create_physical_table(
        self,
        schema: str,
        table: str,
        attributes: list[AttributeRecord],
        *,
        comment: str | None = None,
    ) -> None:
        with self._lock:
            if (schema, table) in self._tables or (schema, table) in self._views:
                raise EntityTableNameConflict(table)
            statements = create_table_statements(schema, table, attributes)
            if comment is not None:
                statements.append(comment_table_sql(schema, table, comment))
            self.statements.extend(statements)
            self._tables[(schema, table)] = {attr.name: attr for attr in attributes}

    def swap_stem_view(
        self,
        schema: str,
        stem: str,
        *,
        physical: str,
        expected_target: str | None,
    ) -> None:
        with self._lock:
            if (schema, stem) in self._tables:
                raise EntityTableNameConflict(stem)
            current = self._views.get((schema, stem))
            if current != expected_target:
                raise EntityTableNameConflict(stem)
            if current is not None:
                self.statements.append(drop_view_sql(schema, stem))
            self.statements.append(create_view_sql(schema, stem, physical))
            self._views[(schema, stem)] = physical

    def drop_stem_view(self, schema: str, stem: str) -> None:
        with self._lock:
            self.statements.append(drop_view_sql(schema, stem))
            self._views.pop((schema, stem), None)

    def revert_physical_table(self, schema: str, table: str) -> None:
        with self._lock:
            if (schema, table) not in self._tables:
                return
            self.statements.append(f"DROP TABLE {qualified_table(schema, table)}")
            self._tables.pop((schema, table), None)


class PostgresEntityTablePort:
    def table_exists(self, schema: str, table: str) -> bool:
        engine = get_entity_engine()
        with engine.connect() as conn:
            return _relation_kind(conn, schema, table) == "r"

    def drop_table(self, schema: str, table: str) -> None:
        engine = get_entity_engine()
        q = qualified_table(schema, table)
        with engine.begin() as conn:
            _drop_empty_table(conn, q)

    def drop_head(self, schema: str, table: str, view: str) -> None:
        engine = get_entity_engine()
        with engine.begin() as conn:
            qualified = qualified_table(schema, table)
            is_table = _relation_kind(conn, schema, table) == "r"
            if is_table:
                _lock_and_assert_empty(conn, qualified)
            if _relation_kind(conn, schema, view) == "v":
                conn.execute(text(drop_view_sql(schema, view)))
            if is_table:
                conn.execute(text(f"DROP TABLE {qualified}"))  # type: ignore[union-attr]

    def create_physical_table(
        self,
        schema: str,
        table: str,
        attributes: list[AttributeRecord],
        *,
        comment: str | None = None,
    ) -> None:
        engine = get_entity_engine()
        statements = create_table_statements(schema, table, attributes)
        if comment is not None:
            statements.append(comment_table_sql(schema, table, comment))
        with engine.begin() as conn:
            if _relation_kind(conn, schema, table) is not None:
                raise EntityTableNameConflict(table)
            for sql in statements:
                conn.execute(text(sql))

    def swap_stem_view(
        self,
        schema: str,
        stem: str,
        *,
        physical: str,
        expected_target: str | None,
    ) -> None:
        engine = get_entity_engine()
        with engine.begin() as conn:
            kind = _relation_kind(conn, schema, stem)
            if expected_target is None:
                if kind is not None:
                    raise EntityTableNameConflict(stem)
            else:
                if kind != "v" or _view_base_table(conn, schema, stem) != expected_target:
                    raise EntityTableNameConflict(stem)
                conn.execute(text(drop_view_sql(schema, stem)))
            conn.execute(text(create_view_sql(schema, stem, physical)))

    def drop_stem_view(self, schema: str, stem: str) -> None:
        engine = get_entity_engine()
        with engine.begin() as conn:
            conn.execute(text(drop_view_sql(schema, stem)))

    def revert_physical_table(self, schema: str, table: str) -> None:
        engine = get_entity_engine()
        q = qualified_table(schema, table)
        with engine.begin() as conn:
            if _relation_kind(conn, schema, table) != "r":
                return
            _drop_empty_table(conn, q)


def _lock_and_assert_empty(conn: object, qualified: str) -> None:
    """Hold the table exclusively, then read emptiness on that same snapshot.

    ACCESS EXCLUSIVE waits out writers. Under READ COMMITTED the following
    SELECT sees the rows those writers committed, so a drop cannot land
    between the check and DROP TABLE.
    """
    conn.execute(text(f"LOCK TABLE {qualified} IN ACCESS EXCLUSIVE MODE"))  # type: ignore[union-attr]
    nonempty = bool(
        conn.execute(  # type: ignore[union-attr]
            text(f"SELECT EXISTS (SELECT 1 FROM {qualified})")
        ).scalar()
    )
    if nonempty:
        raise EntityTableHasRows(qualified)


def _drop_empty_table(conn: object, qualified: str) -> None:
    _lock_and_assert_empty(conn, qualified)
    conn.execute(text(f"DROP TABLE {qualified}"))  # type: ignore[union-attr]


def _relation_kind(conn: object, schema: str, name: str) -> str | None:
    kind = conn.execute(  # type: ignore[union-attr]
        text(
            "SELECT c.relkind FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :schema AND c.relname = :name"
        ),
        {"schema": schema, "name": name},
    ).scalar()
    if kind is None:
        return None
    return str(kind)


def _view_base_table(conn: object, schema: str, view: str) -> str | None:
    name = conn.execute(  # type: ignore[union-attr]
        text(
            "SELECT ref.relname "
            "FROM pg_class v "
            "JOIN pg_namespace n ON n.oid = v.relnamespace "
            "JOIN pg_rewrite rw ON rw.ev_class = v.oid "
            "JOIN pg_depend d ON d.objid = rw.oid AND d.deptype = 'n' "
            "JOIN pg_class ref ON ref.oid = d.refobjid AND ref.relkind = 'r' "
            "WHERE n.nspname = :schema AND v.relname = :view AND ref.oid <> v.oid"
        ),
        {"schema": schema, "view": view},
    ).scalar()
    if name is None:
        return None
    return str(name)


class EntityTableHasRows(Exception):
    """Raised when a drop finds rows while holding the table exclusively."""

    def __init__(self, table: str) -> None:
        super().__init__(table)
        self.table = table


class EntityTableNameConflict(Exception):
    """Raised when publish would occupy a name already present in the schema."""

    def __init__(self, table: str) -> None:
        super().__init__(table)
        self.table = table


_bound: EntityTablePort | None = None
_recording: RecordingEntityTablePort | None = None
_lock = threading.Lock()


def bind_entity_table_port(port: EntityTablePort) -> None:
    global _bound
    _bound = port


def get_entity_table_port() -> EntityTablePort:
    if _bound is not None:
        return _bound
    settings = get_settings()
    if settings.store_backend == "memory":
        return _recording_port()
    require_entity_database_url(settings.entity_database_url)
    return PostgresEntityTablePort()


def _recording_port() -> RecordingEntityTablePort:
    global _recording
    with _lock:
        if _recording is None:
            _recording = RecordingEntityTablePort()
        return _recording


def reset_entity_table_port() -> None:
    global _bound, _recording
    _bound = None
    with _lock:
        _recording = None
