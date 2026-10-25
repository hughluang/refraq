"""Dataset Query node type."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from sqlglot import parse
from sqlglot.errors import SqlglotError

import backend.entity.datasets as entity_datasets
from backend.channel.dataset_ref import DATASET_REFERENCE_SCHEMA, dataset_reference
from backend.channel.dataset_registry import (
    DatasetColumnSpec,
    DatasetQuotaExceeded,
    DatasetRegistry,
    get_dataset_store,
)
from backend.channel.errors import TemporalTargetIncompatible
from backend.channel.node_support import render_field
from backend.channel.nodes.spec import (
    ERROR_OUTPUT,
    MAIN_INPUT,
    MAIN_OUTPUT,
    EngineHooks,
    NodeResult,
    NodeType,
    OutputView,
    Problem,
    ReferenceResolver,
)
from backend.channel.run_store import get_run_store
from backend.channel.nodes.volume.materialize import _CHUNK_ROWS
from backend.metadata.source_statements import (
    SourceStatementRejected,
    stream_source_statement,
)

__all__ = ["NODE_TYPE"]

_DEFAULT_TIMEOUT_SEC = 300
_ONE_STATEMENT = "SQL must be exactly one statement"
_TIMEOUT_MESSAGE = "Dataset Query exceeded the statement timeout"

_OUTPUT: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["dataset", "count"],
    "properties": {
        "dataset": DATASET_REFERENCE_SCHEMA,
        "count": {"type": "integer", "minimum": 0},
    },
}

# ``create_table_from_query`` opens its own owner connection. The listener sets
# the configured wall clock on that transaction. ``get_entity_engine`` is the
# engine that helper already uses.
_TIMEOUT_MS: ContextVar[str | None] = ContextVar("dataset_query_timeout_ms", default=None)
_ARMING: ContextVar[bool] = ContextVar("dataset_query_timeout_arming", default=False)
_LISTENING: set[int] = set()
_LISTENING_LOCK = threading.Lock()


def _refine(
    config: Mapping[str, Any],
    upstream: Mapping[str, Any],
    resolver: Any,
) -> dict[str, Any]:
    del config, upstream, resolver
    return {"main": _OUTPUT, "error": None}


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node["config"]
    statement, error = render_field(
        hooks, config.get("sql"), {"type": "string"}, path="sql"
    )
    if error is not None:
        return error
    source = config["source"]
    if source.get("kind") == "source":
        timeout_sec = int(config.get("statement_timeout_sec", _DEFAULT_TIMEOUT_SEC))
        return _execute_source(
            node,
            hooks,
            str(statement),
            str(source["source_id"]),
            timeout_sec,
        )
    if source.get("kind") != "entity":
        return _node_failed("Dataset Query source must be the entity database")
    if not _exactly_one_postgres_statement(str(statement)):
        return NodeResult(
            status="failed",
            error_code="CHANNEL_SQL_NOT_ONE_STATEMENT",
            error_message=_ONE_STATEMENT,
        )
    timeout_sec = int(config.get("statement_timeout_sec", _DEFAULT_TIMEOUT_SEC))
    try:
        with _wall_clock(timeout_sec):
            record = DatasetRegistry(get_dataset_store()).create_from_query(
                job_id=hooks.run_id,
                node_id=str(node["id"]),
                seq=_execution_seq(node, hooks),
                query=str(statement),
            )
    except DatasetQuotaExceeded:
        return _quota_failed()
    except DBAPIError as exc:
        return _node_failed(_db_message(exc))
    except ValueError as exc:
        return _node_failed(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _node_failed(str(exc))
    return _succeeded(record)


class _StreamHalted(Exception):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


def _execute_source(
    node: Mapping[str, Any],
    hooks: EngineHooks,
    statement: str,
    source_id: str,
    timeout_sec: int,
) -> NodeResult:
    deadline = time.monotonic() + timeout_sec
    stream = None
    try:
        _halt_if_needed(hooks, deadline)
        stream = stream_source_statement(
            source_id,
            statement,
            chunk_rows=_CHUNK_ROWS,
            deadline=deadline,
        )
        record = DatasetRegistry(get_dataset_store()).create_from_chunks(
            job_id=hooks.run_id,
            node_id=str(node["id"]),
            seq=_execution_seq(node, hooks),
            columns=[
                DatasetColumnSpec(
                    column.name,
                    column.normalized_type,
                    precision=column.precision,
                    scale=column.scale,
                    with_time_zone=column.with_time_zone,
                    temporal_kind=column.temporal_kind,
                    nullable=column.nullable,
                )
                for column in stream.columns
            ],
            chunks=_guarded_chunks(stream.chunks, hooks, deadline),
        )
    except _StreamHalted as halted:
        if halted.kind == "timeout":
            return _node_failed(_TIMEOUT_MESSAGE)
        raise
    except SourceStatementRejected:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_SQL_NOT_ONE_STATEMENT",
            error_message=_ONE_STATEMENT,
        )
    except DatasetQuotaExceeded:
        return _quota_failed()
    except TemporalTargetIncompatible as exc:
        return NodeResult(
            status="failed",
            error_code=exc.code,
            error_message=exc.message,
            error_detail=exc.extra_members(),
        )
    except DBAPIError as exc:
        return _node_failed(_db_message(exc))
    except Exception as exc:  # noqa: BLE001
        return _node_failed(str(exc))
    finally:
        if stream is not None:
            stream.close()
    return _succeeded(record)


def _halt_if_needed(hooks: EngineHooks, deadline: float) -> None:
    if hooks.cancelled():
        raise _StreamHalted("cancelled")
    if hooks.superseded():
        raise _StreamHalted("superseded")
    if time.monotonic() >= deadline:
        raise _StreamHalted("timeout")


def _guarded_chunks(
    chunks: Iterator[Sequence[Sequence[Any]]],
    hooks: EngineHooks,
    deadline: float,
) -> Iterator[Sequence[Sequence[Any]]]:
    iterator = iter(chunks)
    while True:
        _halt_if_needed(hooks, deadline)
        try:
            chunk = next(iterator)
        except StopIteration:
            return
        yield chunk


def _check(config: Mapping[str, Any], resolver: ReferenceResolver) -> list[Problem]:
    source = config["source"]
    if source.get("kind") != "source":
        return []
    source_id = source["source_id"]
    if resolver.source_exists(source_id):
        return []
    return [
        Problem(
            "CHANNEL_REFERENCE_UNRESOLVED",
            f"Source does not resolve: {source_id}",
        )
    ]


def _execution_seq(node: Mapping[str, Any], hooks: EngineHooks) -> int:
    node_id = str(node["id"])
    running = [
        record
        for record in get_run_store().list_executions(hooks.run_id)
        if record.node_id == node_id and record.status == "running"
    ]
    if running:
        return running[-1].seq
    return hooks.on_start(node)


def _exactly_one_postgres_statement(sql: str) -> bool:
    """Same count as the entity statement helper. One trailing semicolon is ignored."""
    cleaned = (sql or "").strip()
    body = cleaned[:-1].strip() if cleaned.endswith(";") else cleaned
    if not body:
        return False
    try:
        statements = [item for item in parse(body, read="postgres") if item is not None]
    except SqlglotError:
        return False
    return len(statements) == 1


def _arm_statement_timeout(conn: Any) -> None:
    if _ARMING.get():
        return
    timeout_ms = _TIMEOUT_MS.get()
    if timeout_ms is None:
        return
    token = _ARMING.set(True)
    try:
        conn.execute(
            text("SELECT set_config('statement_timeout', :ms, true)"),
            {"ms": timeout_ms},
        )
        conn.execute(
            text("SELECT set_config('lock_timeout', :ms, true)"),
            {"ms": timeout_ms},
        )
    finally:
        _ARMING.reset(token)


def _listen(engine: Any) -> None:
    key = id(engine)
    with _LISTENING_LOCK:
        if key in _LISTENING:
            return
        event.listen(engine, "begin", _arm_statement_timeout)
        _LISTENING.add(key)


@contextmanager
def _wall_clock(timeout_sec: int) -> Iterator[None]:
    _listen(entity_datasets.get_entity_engine())
    token = _TIMEOUT_MS.set(str(max(1, int(timeout_sec)) * 1000))
    try:
        yield
    finally:
        _TIMEOUT_MS.reset(token)


def _succeeded(record: Any) -> NodeResult:
    reference = dataset_reference(
        dataset_id=record.id,
        columns=record.columns,
        count=record.row_count,
    )
    return NodeResult(
        status="succeeded",
        output={"dataset": reference, "count": record.row_count},
    )


def _node_failed(message: str) -> NodeResult:
    return NodeResult(
        status="failed",
        error_code="CHANNEL_NODE_FAILED",
        error_message=message,
    )


def _quota_failed() -> NodeResult:
    return NodeResult(
        status="failed",
        error_code=DatasetQuotaExceeded.code,
        error_message="Dataset storage is already at the capacity ceiling",
    )


def _db_message(exc: DBAPIError) -> str:
    origin = exc.orig
    text_value = str(origin or exc).strip()
    return text_value or "SQL statement failed"


NODE_TYPE = NodeType(
    type_id="volume.dataset_query",
    family="volume",
    label="Dataset Query",
    summary=(
        "Turns one query on the entity database or a registered Source "
        "into a dataset reference."
    ),
    description=(
        "The source selects the entity database or a registered Source. "
        "On the entity database the statement is loaded into a dataset table "
        "in one step and the node returns a dataset reference. "
        "PostgreSQL and Oracle run the read in a read-only transaction "
        "and stream it into the dataset. "
        "SQL Server does not change isolation, and a long read is not a snapshot."
    ),
    trigger=False,
    inputs=(MAIN_INPUT,),
    outputs=(MAIN_OUTPUT, ERROR_OUTPUT),
    config_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "source": {
                "type": "object",
                "additionalProperties": False,
                "title": "Source",
                "description": "Entity database or a registered Source.",
                "x-refraq-ref": "sql_source",
                "required": ["kind"],
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["entity", "source"],
                        "title": "Kind",
                        "description": (
                            "entity selects the entity database. "
                            "source selects a registered Source."
                        ),
                    },
                    "source_id": {
                        "type": "string",
                        "minLength": 1,
                        "title": "Source",
                        "description": "Registered Source id. Required when kind is source.",
                    },
                },
                "allOf": [
                    {
                        "if": {
                            "properties": {"kind": {"const": "source"}},
                            "required": ["kind"],
                        },
                        "then": {"required": ["source_id"]},
                    },
                    {
                        "if": {
                            "properties": {"kind": {"const": "entity"}},
                            "required": ["kind"],
                        },
                        "then": {"properties": {"source_id": False}},
                    },
                ],
            },
            "sql": {
                "type": "string",
                "minLength": 1,
                "title": "SQL",
                "description": (
                    "One SQL statement. Each {{ }} result is spliced as text. "
                    "The statement is loaded into a dataset table."
                ),
                "x-refraq-template": {"type": "string"},
            },
            "statement_timeout_sec": {
                "type": "integer",
                "minimum": 1,
                "maximum": 3600,
                "default": _DEFAULT_TIMEOUT_SEC,
                "title": "Statement timeout",
                "description": (
                    "Seconds for the whole import. "
                    "The server cancels the statement at this wall clock. "
                    "Default 300."
                ),
            },
        },
        "required": ["source", "sql"],
    },
    output_view=OutputView(kind="dataset", dataset="dataset", metrics=("count",)),
    execute=_execute,
    refine=_refine,
    check=_check,
)
