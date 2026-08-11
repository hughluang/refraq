"""Controlled query and Catalog Sample domain service (HTTP shared)."""

from __future__ import annotations

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass
from typing import Any

from backend.admin.audit import persist_audit_event
from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.metadata.catalog import service as catalog_service
from backend.metadata.connectors.base import (
    ConnectorError,
    QueryResult,
    endpoint_from_access,
)
from backend.metadata.connectors.registry import get_connector
from backend.metadata.errors import (
    JobSourceDisabled,
    QueryFailed,
    QueryRowLimit,
    QueryTimeout,
    SampleFilterInvalid,
    SourceEngineUnsupported,
)
from backend.metadata.query.compile_sample import (
    SampleFilterSpec,
    SampleOrderSpec,
    compile_sample_sql,
)
from backend.metadata.query.guards import assert_readonly_single_statement
from backend.metadata.sources.access import decrypt_access_blob
from backend.metadata.sources.service import require_source

DEFAULT_MAX_ROWS = 100
DEFAULT_SAMPLE_LIMIT = 50
_SQL_SUMMARY_MAX = 200


@dataclass(frozen=True)
class QueryOutcome:
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool
    duration_ms: int


@dataclass(frozen=True)
class SampleOutcome:
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool
    duration_ms: int
    offset: int
    limit: int
    has_more: bool
    sql: str | None


def _sql_detail(sql: str, *, max_rows: int, code: str | None = None) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "sql_sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
        "sql_summary": sql[:_SQL_SUMMARY_MAX],
        "max_rows": max_rows,
    }
    if code is not None:
        detail["code"] = code
    return detail


def _audit(
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
    resource_type: str,
    resource_id: str,
    action: str,
    result: str,
    detail: dict[str, Any],
) -> None:
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        result=result,
        detail=detail,
    )


def _execute_readonly(
    *,
    source_id: str,
    sql: str,
    max_rows: int,
    timeout_sec: int,
) -> QueryResult:
    source = require_source(source_id)
    if source.status != "active":
        raise JobSourceDisabled("Source is not usable for query")
    if not source.engine or not source.access_ciphertext:
        raise QueryFailed("Source has no access configuration")

    connector = get_connector(source.engine)
    if connector is None:
        raise SourceEngineUnsupported()

    normalized = assert_readonly_single_statement(sql, engine=source.engine)
    access = decrypt_access_blob(source.access_ciphertext)
    endpoint = endpoint_from_access(
        engine=source.engine,
        access=access,
        database_name=source.database_name or "",
        schema_filter=source.schema_filter,
    )

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(
            connector.run_readonly,
            endpoint,
            normalized,
            max_rows=max_rows,
            timeout_sec=timeout_sec,
        )
        try:
            return future.result(timeout=timeout_sec)
        except FuturesTimeout as exc:
            raise QueryTimeout(
                f"Query exceeded the platform timeout of {timeout_sec}s"
            ) from exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def run_controlled_query(
    *,
    source_id: str,
    sql: str,
    max_rows: int | None,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> QueryOutcome:
    settings = get_settings()
    platform_cap = settings.refraq_query_max_rows
    timeout_sec = settings.refraq_query_timeout_sec
    effective_max = DEFAULT_MAX_ROWS if max_rows is None else int(max_rows)
    started = time.perf_counter()

    try:
        if effective_max < 1:
            raise QueryRowLimit(f"max_rows must be at least 1, got {effective_max}")
        if effective_max > platform_cap:
            raise QueryRowLimit(
                f"max_rows {effective_max} exceeds platform cap {platform_cap}"
            )

        result = _execute_readonly(
            source_id=source_id,
            sql=sql,
            max_rows=effective_max,
            timeout_sec=timeout_sec,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        detail = _sql_detail(sql, max_rows=effective_max)
        detail["duration_ms"] = duration_ms
        _audit(
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            resource_type="source",
            resource_id=source_id,
            action="query.run",
            result="success",
            detail=detail,
        )
        return QueryOutcome(
            columns=result.columns,
            rows=result.rows,
            truncated=result.truncated,
            duration_ms=duration_ms,
        )
    except ConnectorError as exc:
        mapped: AppError = (
            QueryTimeout(exc.message)
            if exc.code == "QUERY_TIMEOUT"
            else QueryFailed(exc.message)
        )
        detail = _sql_detail(sql, max_rows=effective_max, code=mapped.code)
        detail["duration_ms"] = int((time.perf_counter() - started) * 1000)
        _audit(
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            resource_type="source",
            resource_id=source_id,
            action="query.run",
            result="failure",
            detail=detail,
        )
        raise mapped from exc
    except AppError as exc:
        detail = _sql_detail(sql, max_rows=effective_max, code=exc.code)
        detail["duration_ms"] = int((time.perf_counter() - started) * 1000)
        _audit(
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            resource_type="source",
            resource_id=source_id,
            action="query.run",
            result="failure",
            detail=detail,
        )
        raise
    except Exception as exc:  # noqa: BLE001 — map unexpected driver/runtime errors
        detail = _sql_detail(sql, max_rows=effective_max, code="QUERY_FAILED")
        detail["duration_ms"] = int((time.perf_counter() - started) * 1000)
        _audit(
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            resource_type="source",
            resource_id=source_id,
            action="query.run",
            result="failure",
            detail=detail,
        )
        raise QueryFailed(str(exc)) from exc


def run_catalog_sample(
    *,
    object_id: str,
    columns: list[str] | None,
    filters: list[SampleFilterSpec],
    order_by: list[SampleOrderSpec],
    offset: int,
    limit: int | None,
    include_sql: bool,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> SampleOutcome:
    settings = get_settings()
    platform_cap = settings.refraq_query_max_rows
    timeout_sec = settings.refraq_query_timeout_sec
    effective_limit = DEFAULT_SAMPLE_LIMIT if limit is None else int(limit)
    effective_offset = int(offset)
    started = time.perf_counter()
    compiled_sql = ""

    try:
        if effective_offset < 0:
            raise SampleFilterInvalid(f"offset must be >= 0, got {effective_offset}")
        if effective_limit < 1:
            raise QueryRowLimit(f"limit must be at least 1, got {effective_limit}")
        if effective_limit > platform_cap:
            raise QueryRowLimit(
                f"limit {effective_limit} exceeds platform cap {platform_cap}"
            )
        if effective_offset + effective_limit > platform_cap:
            raise QueryRowLimit(
                f"offset + limit ({effective_offset + effective_limit}) "
                f"exceeds platform cap {platform_cap}"
            )

        obj = catalog_service.get_object(object_id)
        source = require_source(obj.source_id)
        if not source.engine:
            raise SourceEngineUnsupported()

        known = {c.name for c in obj.columns if c.is_present}
        compiled_sql = compile_sample_sql(
            engine=source.engine,
            schema_name=obj.schema_name,
            object_name=obj.name,
            known_columns=known,
            columns=columns,
            filters=filters,
            order_by=order_by,
            offset=effective_offset,
            limit=effective_limit,
        )

        result = _execute_readonly(
            source_id=obj.source_id,
            sql=compiled_sql,
            max_rows=effective_limit,
            timeout_sec=timeout_sec,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        detail = _sql_detail(compiled_sql, max_rows=effective_limit)
        detail["duration_ms"] = duration_ms
        detail["offset"] = effective_offset
        detail["limit"] = effective_limit
        _audit(
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            resource_type="catalog_object",
            resource_id=obj.id,
            action="catalog.sample",
            result="success",
            detail=detail,
        )
        has_more = len(result.rows) == effective_limit
        return SampleOutcome(
            columns=result.columns,
            rows=result.rows,
            truncated=result.truncated,
            duration_ms=duration_ms,
            offset=effective_offset,
            limit=effective_limit,
            has_more=has_more,
            sql=compiled_sql if include_sql else None,
        )
    except ConnectorError as exc:
        mapped: AppError = (
            QueryTimeout(exc.message)
            if exc.code == "QUERY_TIMEOUT"
            else QueryFailed(exc.message)
        )
        detail = _sql_detail(
            compiled_sql or "",
            max_rows=effective_limit,
            code=mapped.code,
        )
        detail["duration_ms"] = int((time.perf_counter() - started) * 1000)
        _audit(
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            resource_type="catalog_object",
            resource_id=object_id,
            action="catalog.sample",
            result="failure",
            detail=detail,
        )
        raise mapped from exc
    except AppError as exc:
        detail = _sql_detail(
            compiled_sql or "",
            max_rows=effective_limit,
            code=exc.code,
        )
        detail["duration_ms"] = int((time.perf_counter() - started) * 1000)
        _audit(
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            resource_type="catalog_object",
            resource_id=object_id,
            action="catalog.sample",
            result="failure",
            detail=detail,
        )
        raise
    except Exception as exc:  # noqa: BLE001
        detail = _sql_detail(
            compiled_sql or "",
            max_rows=effective_limit,
            code="QUERY_FAILED",
        )
        detail["duration_ms"] = int((time.perf_counter() - started) * 1000)
        _audit(
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            resource_type="catalog_object",
            resource_id=object_id,
            action="catalog.sample",
            result="failure",
            detail=detail,
        )
        raise QueryFailed(str(exc)) from exc
