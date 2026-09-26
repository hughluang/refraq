"""Entity Table port: Recording for memory and test binds; Postgres when persistent."""

from __future__ import annotations

import threading
from typing import Protocol

from sqlalchemy import text

from backend.core.config import get_settings, require_entity_database_url
from backend.entity.ddl import (
    create_table_statements,
    qualified_table,
    rename_table_statements,
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

    def publish_table(
        self,
        schema: str,
        stem: str,
        attributes: list[AttributeRecord],
        *,
        archive_as: str | None,
        archive_attributes: list[AttributeRecord] | None,
    ) -> None: ...

    def revert_publish_table(
        self,
        schema: str,
        stem: str,
        *,
        archive_as: str | None,
        archive_attributes: list[AttributeRecord] | None,
    ) -> None: ...


class RecordingEntityTablePort:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self._tables: dict[tuple[str, str], dict[str, AttributeRecord]] = {}
        self._lock = threading.Lock()

    def table_exists(self, schema: str, table: str) -> bool:
        with self._lock:
            return (schema, table) in self._tables

    def drop_table(self, schema: str, table: str) -> None:
        sql = f"DROP TABLE {qualified_table(schema, table)}"
        with self._lock:
            self.statements.append(sql)
            self._tables.pop((schema, table), None)

    def publish_table(
        self,
        schema: str,
        stem: str,
        attributes: list[AttributeRecord],
        *,
        archive_as: str | None,
        archive_attributes: list[AttributeRecord] | None,
    ) -> None:
        with self._lock:
            archived = False
            if archive_as:
                if (schema, archive_as) in self._tables:
                    raise EntityTableNameConflict(archive_as)
                if (schema, stem) not in self._tables:
                    raise EntityTableNameConflict(stem)
                self._move_table_locked(
                    schema,
                    stem,
                    archive_as,
                    archive_attributes or [],
                )
                archived = True
            if (schema, stem) in self._tables:
                if archived:
                    self._move_table_locked(
                        schema,
                        archive_as or stem,
                        stem,
                        archive_attributes or [],
                    )
                raise EntityTableNameConflict(stem)
            statements = create_table_statements(schema, stem, attributes)
            self.statements.extend(statements)
            self._tables[(schema, stem)] = {attr.name: attr for attr in attributes}

    def revert_publish_table(
        self,
        schema: str,
        stem: str,
        *,
        archive_as: str | None,
        archive_attributes: list[AttributeRecord] | None,
    ) -> None:
        with self._lock:
            if (schema, stem) in self._tables:
                sql = f"DROP TABLE {qualified_table(schema, stem)}"
                self.statements.append(sql)
                self._tables.pop((schema, stem), None)
            if archive_as and (schema, archive_as) in self._tables:
                self._move_table_locked(
                    schema,
                    archive_as,
                    stem,
                    archive_attributes or [],
                )

    def _move_table_locked(
        self,
        schema: str,
        current: str,
        new: str,
        attributes: list[AttributeRecord],
    ) -> None:
        self.statements.extend(
            rename_table_statements(schema, current, new, attributes)
        )
        self._tables[(schema, new)] = self._tables.pop((schema, current))


class PostgresEntityTablePort:
    def table_exists(self, schema: str, table: str) -> bool:
        engine = get_entity_engine()
        with engine.connect() as conn:
            found = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = :schema AND table_name = :table"
                ),
                {"schema": schema, "table": table},
            ).scalar()
        return found is not None

    def drop_table(self, schema: str, table: str) -> None:
        engine = get_entity_engine()
        q = qualified_table(schema, table)
        with engine.begin() as conn:
            nonempty = bool(
                conn.execute(text(f"SELECT EXISTS (SELECT 1 FROM {q})")).scalar()
            )
            if nonempty:
                raise EntityTableHasRows()
            conn.execute(text(f"DROP TABLE {q}"))

    def publish_table(
        self,
        schema: str,
        stem: str,
        attributes: list[AttributeRecord],
        *,
        archive_as: str | None,
        archive_attributes: list[AttributeRecord] | None,
    ) -> None:
        engine = get_entity_engine()
        with engine.begin() as conn:
            if archive_as:
                if _table_exists_on(conn, schema, archive_as):
                    raise EntityTableNameConflict(archive_as)
                if not _table_exists_on(conn, schema, stem):
                    raise EntityTableNameConflict(stem)
                for sql in rename_table_statements(
                    schema, stem, archive_as, archive_attributes or []
                ):
                    conn.execute(text(sql))
            if _table_exists_on(conn, schema, stem):
                raise EntityTableNameConflict(stem)
            for sql in create_table_statements(schema, stem, attributes):
                conn.execute(text(sql))

    def revert_publish_table(
        self,
        schema: str,
        stem: str,
        *,
        archive_as: str | None,
        archive_attributes: list[AttributeRecord] | None,
    ) -> None:
        engine = get_entity_engine()
        with engine.begin() as conn:
            if _table_exists_on(conn, schema, stem):
                nonempty = bool(
                    conn.execute(
                        text(
                            "SELECT EXISTS (SELECT 1 FROM "
                            f"{qualified_table(schema, stem)})"
                        )
                    ).scalar()
                )
                if nonempty:
                    raise EntityTableHasRows()
                conn.execute(text(f"DROP TABLE {qualified_table(schema, stem)}"))
            if archive_as and _table_exists_on(conn, schema, archive_as):
                for sql in rename_table_statements(
                    schema, archive_as, stem, archive_attributes or []
                ):
                    conn.execute(text(sql))


def _table_exists_on(conn: object, schema: str, table: str) -> bool:
    found = conn.execute(  # type: ignore[union-attr]
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = :schema AND table_name = :table"
        ),
        {"schema": schema, "table": table},
    ).scalar()
    return found is not None


class EntityTableHasRows(Exception):
    """Raised when drop finds rows in the same transaction as DROP TABLE."""


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
